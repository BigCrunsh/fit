"""Wellness baselines and deviation states — the SSOT consumed by alerts, coach context, and chart.

Baseline = rolling median of the trailing window that PRECEDES the evaluated days
(an ongoing illness must not absorb into its own baseline). Missing days break
consecutive streaks. Sleep and waking respiration series are never mixed.
"""

from datetime import date, timedelta

from fit.wellness import wellness_snapshot

CFG = {"coaching": {"respiration_delta_brpm": 2.0, "rhr_delta_bpm": 5, "wellness_baseline_days": 28}}


def _day(offset: int) -> str:
    """ISO date `offset` days before today (offset 0 = today)."""
    return (date.today() - timedelta(days=offset)).isoformat()


def _insert(db, offset: int, **cols):
    keys = ["date"] + list(cols.keys())
    vals = [_day(offset)] + list(cols.values())
    db.execute(
        f"INSERT INTO daily_health ({','.join(keys)}) VALUES ({','.join('?' * len(vals))})",
        vals,
    )


def _fill_baseline(db, start_offset: int, days: int, **cols):
    """Insert `days` consecutive rows ending at start_offset (exclusive of newer days)."""
    for i in range(days):
        _insert(db, start_offset + i, **cols)


# ── respiration ──


class TestRespirationDeviation:
    def test_two_elevated_nights_flags_elevated(self, db):
        _fill_baseline(db, 2, 28, avg_sleep_respiration=15.0)
        _insert(db, 1, avg_sleep_respiration=17.2)
        _insert(db, 0, avg_sleep_respiration=17.5)
        db.commit()
        r = wellness_snapshot(db, CFG)["respiration"]
        assert r["series"] == "sleep"
        assert r["baseline"] == 15.0          # evaluation nights excluded from baseline
        assert r["consecutive_elevated"] == 2
        assert r["elevated"] is True

    def test_single_elevated_night_not_elevated(self, db):
        _fill_baseline(db, 2, 28, avg_sleep_respiration=15.0)
        _insert(db, 1, avg_sleep_respiration=15.2)
        _insert(db, 0, avg_sleep_respiration=18.0)
        db.commit()
        r = wellness_snapshot(db, CFG)["respiration"]
        assert r["consecutive_elevated"] == 1
        assert r["elevated"] is False

    def test_boundary_exactly_baseline_plus_delta_counts(self, db):
        _fill_baseline(db, 2, 28, avg_sleep_respiration=15.0)
        _insert(db, 1, avg_sleep_respiration=17.0)
        _insert(db, 0, avg_sleep_respiration=17.0)
        db.commit()
        r = wellness_snapshot(db, CFG)["respiration"]
        assert r["elevated"] is True

    def test_insufficient_baseline_no_deviation_state(self, db):
        # 10 obs < 14 minimum → baseline undefined, never elevated
        _fill_baseline(db, 2, 10, avg_sleep_respiration=15.0)
        _insert(db, 1, avg_sleep_respiration=19.0)
        _insert(db, 0, avg_sleep_respiration=19.0)
        db.commit()
        r = wellness_snapshot(db, CFG)["respiration"]
        assert r["baseline"] is None
        assert r["elevated"] is False

    def test_waking_fallback_when_sleep_series_thin(self, db):
        # sleep: only 5 obs (no baseline possible); waking: full history + elevation
        _fill_baseline(db, 2, 28, avg_respiration=15.0)
        _insert(db, 1, avg_respiration=17.5)
        _insert(db, 0, avg_respiration=17.5)
        for i in range(5):
            db.execute("UPDATE daily_health SET avg_sleep_respiration = 16.0 WHERE date = ?", (_day(i),))
        db.commit()
        r = wellness_snapshot(db, CFG)["respiration"]
        assert r["series"] == "waking"
        assert r["elevated"] is True

    def test_series_not_mixed_sleep_preferred(self, db):
        # Sleep series is calm; waking series is wildly elevated — sleep must win untainted
        _fill_baseline(db, 0, 30, avg_sleep_respiration=15.0, avg_respiration=15.0)
        db.execute("UPDATE daily_health SET avg_respiration = 25.0 WHERE date >= ?", (_day(1),))
        db.commit()
        r = wellness_snapshot(db, CFG)["respiration"]
        assert r["series"] == "sleep"
        assert r["elevated"] is False

    def test_no_respiration_data_at_all(self, db):
        r = wellness_snapshot(db, CFG)["respiration"]
        assert r["series"] is None
        assert r["baseline"] is None and r["latest"] is None
        assert r["elevated"] is False


# ── RHR ──


class TestRhrDeviation:
    def test_three_elevated_days_flags_elevated(self, db):
        _fill_baseline(db, 3, 28, resting_heart_rate=55)
        _insert(db, 2, resting_heart_rate=61)
        _insert(db, 1, resting_heart_rate=60)
        _insert(db, 0, resting_heart_rate=62)
        db.commit()
        r = wellness_snapshot(db, CFG)["rhr"]
        assert r["baseline"] == 55
        assert r["consecutive_elevated"] == 3
        assert r["elevated"] is True

    def test_two_elevated_days_not_elevated(self, db):
        _fill_baseline(db, 2, 28, resting_heart_rate=55)
        _insert(db, 1, resting_heart_rate=61)
        _insert(db, 0, resting_heart_rate=62)
        db.commit()
        r = wellness_snapshot(db, CFG)["rhr"]
        assert r["consecutive_elevated"] == 2
        assert r["elevated"] is False

    def test_missing_day_breaks_streak(self, db):
        # elevated day-3 and day-1 (latest), nothing on day-2 → streak is 1 (gap = unknown)
        _fill_baseline(db, 4, 28, resting_heart_rate=55)
        _insert(db, 3, resting_heart_rate=61)
        _insert(db, 1, resting_heart_rate=61)
        db.commit()
        r = wellness_snapshot(db, CFG)["rhr"]
        assert r["consecutive_elevated"] == 1  # day-2 gap blocks day-3 from joining
        assert r["elevated"] is False

    def test_streak_interrupted_by_normal_day(self, db):
        _fill_baseline(db, 4, 28, resting_heart_rate=55)
        _insert(db, 3, resting_heart_rate=61)
        _insert(db, 2, resting_heart_rate=54)
        _insert(db, 1, resting_heart_rate=61)
        _insert(db, 0, resting_heart_rate=62)
        db.commit()
        r = wellness_snapshot(db, CFG)["rhr"]
        assert r["consecutive_elevated"] == 2
        assert r["elevated"] is False


# ── recovery cliff ──


def _cliff_setup(db, rhr=62, hrv_status="LOW", hrv=None, readiness=38):
    """28d calm baseline, then a cliff-shaped latest day."""
    _fill_baseline(db, 1, 28, resting_heart_rate=55, hrv_last_night=40.0)
    _insert(db, 0, resting_heart_rate=rhr, hrv_status=hrv_status,
            hrv_last_night=hrv, training_readiness=readiness)
    db.commit()


class TestRecoveryCliff:
    def test_all_three_conditions_fire(self, db):
        _cliff_setup(db)
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is True

    def test_two_of_three_do_not_fire(self, db):
        _cliff_setup(db, hrv_status="BALANCED", hrv=40.0)
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is False

    def test_rhr_normal_blocks(self, db):
        _cliff_setup(db, rhr=56)
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is False

    def test_readiness_ok_blocks(self, db):
        _cliff_setup(db, readiness=75)
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is False

    def test_missing_readiness_blocks(self, db):
        _cliff_setup(db, readiness=None)
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is False

    def test_hrv_ratio_fallback_when_status_missing(self, db):
        # status NULL, hrv 32 < 0.85 × baseline 40 (= 34) → low
        _cliff_setup(db, hrv_status=None, hrv=32.0)
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is True

    def test_hrv_ratio_above_threshold_blocks(self, db):
        _cliff_setup(db, hrv_status=None, hrv=36.0)  # 36 ≥ 34 → not low
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is False

    def test_balanced_status_wins_over_low_ratio(self, db):
        # Garmin status is authoritative when present — ratio only a fallback
        _cliff_setup(db, hrv_status="BALANCED", hrv=20.0)
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is False

    def test_empty_db_no_cliff(self, db):
        assert wellness_snapshot(db, CFG)["recovery_cliff"] is False


# ── defaults ──


class TestConfigDefaults:
    def test_runs_without_config(self, db):
        _fill_baseline(db, 2, 28, avg_sleep_respiration=15.0)
        _insert(db, 1, avg_sleep_respiration=17.5)
        _insert(db, 0, avg_sleep_respiration=17.5)
        db.commit()
        r = wellness_snapshot(db, None)["respiration"]
        assert r["elevated"] is True  # defaults: delta 2.0, window 28
