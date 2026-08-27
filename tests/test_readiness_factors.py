"""Readiness is Garmin's number — this pins down WHY it reads what it reads.

The bug this suite guards: a readiness score of 1 was reported as a CRITICAL
recovery problem when Garmin's own factor breakdown said the only bad input was
64 hours of recovery time still counting down from a hard session two days
earlier — HRV, load ratio, sleep history and stress history were all "GOOD".
Storing the factors makes "why is readiness 1?" answerable from the database
instead of by inference, and `readiness_breakdown` is the single source of that
answer for the alert message and the coaching context.
"""

from fit.wellness import readiness_breakdown
from fit.sync import _upsert_health

# Field names verified against a live `get_training_readiness` response
# (2026-08-27) — not guessed from documentation.
GARMIN_READING = {
    "calendarDate": "2026-08-27", "score": 1, "level": "POOR",
    "recoveryTime": 3849, "recoveryTimeFactorPercent": 16,
    "sleepScore": 66, "sleepScoreFactorPercent": 49,
    "hrvFactorPercent": 76, "acwrFactorPercent": 85,
    "sleepHistoryFactorPercent": 83, "stressHistoryFactorPercent": 77,
    "feedbackShort": "LET_YOUR_BODY_RECOVER", "acuteLoad": 622,
    "timestampLocal": "2026-08-27T06:20:03.0", "inputContext": "AFTER_WAKEUP_RESET",
}


def _health_row(db, **cols):
    keys = ", ".join(cols)
    vals = ", ".join(f":{k}" for k in cols)
    db.execute(f"INSERT INTO daily_health (date, {keys}) VALUES (date('now'), {vals})", cols)
    db.commit()


# ── the migration ──

class TestReadinessFactorColumns:
    def test_factor_columns_exist_and_round_trip(self, db):
        _health_row(db, training_readiness=1, readiness_level="POOR",
                    readiness_recovery_time_min=3849, readiness_recovery_factor_pct=16,
                    readiness_sleep_factor_pct=49, readiness_hrv_factor_pct=76,
                    readiness_acwr_factor_pct=85, readiness_sleep_history_pct=83,
                    readiness_stress_history_pct=77,
                    readiness_feedback="LET_YOUR_BODY_RECOVER", sleep_score=66)
        row = db.execute("SELECT * FROM daily_health").fetchone()
        assert row["readiness_recovery_time_min"] == 3849
        assert row["readiness_feedback"] == "LET_YOUR_BODY_RECOVER"
        assert row["sleep_score"] == 66

    def test_factors_are_nullable_for_history_without_them(self, db):
        # Every row synced before this migration has NULL factors — reading such a
        # row must not raise, since backfilling Garmin's breakdown is not possible.
        _health_row(db, training_readiness=75)
        row = db.execute("SELECT * FROM daily_health").fetchone()
        assert row["readiness_recovery_factor_pct"] is None


# ── the explanation ──

class TestReadinessBreakdown:
    def test_names_recovery_time_as_the_driver(self, db):
        _health_row(db, training_readiness=1, readiness_level="POOR",
                    readiness_recovery_time_min=3849, readiness_recovery_factor_pct=16,
                    readiness_sleep_factor_pct=49, readiness_hrv_factor_pct=76,
                    readiness_acwr_factor_pct=85, readiness_sleep_history_pct=83,
                    readiness_stress_history_pct=77)
        b = readiness_breakdown(db)
        assert b["score"] == 1
        assert b["driver"] == "recovery time"
        assert b["recovery_time_h"] == 64        # 3849 min, rounded
        # the other factors are reported as fine, so the summary can say so
        assert set(b["healthy"]) >= {"HRV", "load ratio", "sleep history", "stress history"}
        assert "recovery time" in b["summary"] and "64h" in b["summary"]

    def test_names_hrv_as_driver_when_hrv_is_the_low_factor(self, db):
        _health_row(db, training_readiness=22, readiness_level="LOW",
                    readiness_recovery_time_min=0, readiness_recovery_factor_pct=95,
                    readiness_sleep_factor_pct=80, readiness_hrv_factor_pct=12,
                    readiness_acwr_factor_pct=88, readiness_sleep_history_pct=79,
                    readiness_stress_history_pct=90)
        b = readiness_breakdown(db)
        assert b["driver"] == "HRV"
        # no recovery-time debt, so the summary must not blame a hard session
        assert b["recovery_time_h"] is None
        assert "counting down" not in b["summary"]
        assert "recovery time" in b["healthy"]      # rated 95 — reported as fine, not as a cause

    def test_no_factors_stored_yields_no_driver_not_a_guess(self, db):
        _health_row(db, training_readiness=30, readiness_level="LOW")
        b = readiness_breakdown(db)
        assert b["score"] == 30
        assert b["driver"] is None
        assert b["summary"] is None            # never invent a reason we don't have

    def test_no_readiness_data_at_all(self, db):
        b = readiness_breakdown(db)
        assert b["score"] is None and b["driver"] is None

    def test_reads_the_latest_day_that_has_a_score(self, db):
        # A newer row with no readiness (Garmin hadn't answered yet) must not
        # blank the breakdown — fall through to the last day that has one.
        db.execute("INSERT INTO daily_health (date, training_readiness, "
                   "readiness_hrv_factor_pct) VALUES (date('now','-1 day'), 44, 30)")
        db.execute("INSERT INTO daily_health (date, resting_heart_rate) "
                   "VALUES (date('now'), 55)")
        db.commit()
        b = readiness_breakdown(db)
        assert b["score"] == 44 and b["driver"] == "HRV"

    def test_recovery_time_debt_reported_even_when_another_factor_is_lower(self, db):
        # Recovery time isn't the lowest factor here, but 40h of debt is still the
        # actionable context ("you are inside a hard session's shadow").
        _health_row(db, training_readiness=18, readiness_level="LOW",
                    readiness_recovery_time_min=2400, readiness_recovery_factor_pct=40,
                    readiness_sleep_factor_pct=15, readiness_hrv_factor_pct=70,
                    readiness_acwr_factor_pct=80, readiness_sleep_history_pct=75,
                    readiness_stress_history_pct=70)
        b = readiness_breakdown(db)
        assert b["driver"] == "sleep"
        assert b["recovery_time_h"] == 40
        assert "40h" in b["summary"]           # debt still surfaced alongside the driver


# ── Garmin payload → database ──

class TestFactorCapture:
    def _api(self, reading=None):
        from unittest.mock import MagicMock
        api = MagicMock()
        # Only the readiness endpoint matters here; the others are wrapped in
        # try/except per-endpoint, so letting them raise keeps this focused.
        for name in ("get_stats", "get_sleep_data", "get_hrv_data", "get_respiration_data",
                     "get_spo2_data"):
            getattr(api, name).side_effect = RuntimeError("not under test")
        api.get_training_readiness.return_value = reading or GARMIN_READING
        return api

    def test_fetch_maps_every_factor_field(self):
        from datetime import date as _date
        from fit.garmin import fetch_health
        h = fetch_health(self._api(), _date(2026, 8, 27), _date(2026, 8, 27))[0]
        assert h["training_readiness"] == 1
        assert h["readiness_recovery_time_min"] == 3849
        assert h["readiness_recovery_factor_pct"] == 16
        assert h["readiness_sleep_factor_pct"] == 49
        assert h["readiness_hrv_factor_pct"] == 76
        assert h["readiness_acwr_factor_pct"] == 85
        assert h["readiness_sleep_history_pct"] == 83
        assert h["readiness_stress_history_pct"] == 77
        assert h["readiness_feedback"] == "LET_YOUR_BODY_RECOVER"
        assert h["sleep_score"] == 66

    def test_reading_without_factors_stores_score_alone(self):
        # Older devices / partial responses: the score must still land, with the
        # unavailable factors simply absent rather than defaulted to zero.
        from datetime import date as _date
        from fit.garmin import fetch_health
        h = fetch_health(self._api({"score": 70, "level": "HIGH", "calendarDate": "2026-08-27"}),
                         _date(2026, 8, 27), _date(2026, 8, 27))[0]
        assert h["training_readiness"] == 70
        assert "readiness_hrv_factor_pct" not in h

    def test_upsert_persists_and_refreshes_factors_with_the_score(self, db):
        # A re-sync later in the day brings a new score; the stored breakdown must
        # move with it, never explain the previous number.
        _upsert_health(db, {"date": "2026-08-27", "training_readiness": 1,
                            "readiness_recovery_time_min": 3849,
                            "readiness_recovery_factor_pct": 16,
                            "readiness_hrv_factor_pct": 76, "sleep_score": 66})
        _upsert_health(db, {"date": "2026-08-27", "training_readiness": 55,
                            "readiness_recovery_time_min": 600,
                            "readiness_recovery_factor_pct": 70,
                            "readiness_hrv_factor_pct": 80})
        db.commit()
        row = db.execute("SELECT * FROM daily_health WHERE date = '2026-08-27'").fetchone()
        assert row["training_readiness"] == 55
        assert row["readiness_recovery_time_min"] == 600
        assert row["readiness_recovery_factor_pct"] == 70
        # sleep_score is a standalone metric, not part of the breakdown — a later
        # response that omits it must not erase it.
        assert row["sleep_score"] == 66
