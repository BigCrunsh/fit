"""Tests for the standardizing calibration anchor layer (VDOT policy).

Model (standardize-calibration-anchors):
  - suggestion = max over observations inside a trailing window (a max can't
    be dragged down by a slow/distorted effort; downward trends show up as
    strong efforts ageing out of the window);
  - active value is *sticky* — the last human-confirmed value, never auto-
    overwritten by the windowed max;
  - stale when the value's source effort is older than the window → the cue to
    prompt a re-test;
  - suggestion.differs flags when sync should prompt accept/reject.
"""

from datetime import date, timedelta

from fit.calibration import _max_in_window, get_calibration_anchor


def _ins(db, metric, value, method, days_ago, confidence="medium", active=0):
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
        "VALUES (?, ?, ?, ?, ?, ?, '[]')",
        (metric, value, method, confidence,
         (date.today() - timedelta(days=days_ago)).isoformat(), active),
    )
    db.commit()


class TestMaxInWindow:
    def test_picks_max_inside_window_excludes_outside(self, db):
        rows = [
            {"value": 35.7, "date": (date.today() - timedelta(days=30)).isoformat()},
            {"value": 40.9, "date": (date.today() - timedelta(days=60)).isoformat()},
            {"value": 41.0, "date": (date.today() - timedelta(days=400)).isoformat()},  # out
        ]
        val, contrib = _max_in_window(rows, 180, date.today())
        assert val == 40.9          # 41.0 is outside the 180d window
        assert len(contrib) == 2

    def test_empty_window_returns_none(self, db):
        rows = [{"value": 41.0, "date": (date.today() - timedelta(days=400)).isoformat()}]
        val, contrib = _max_in_window(rows, 180, date.today())
        assert val is None and contrib == []

    def test_slow_outlier_never_selected(self, db):
        rows = [
            {"value": 35.7, "date": (date.today() - timedelta(days=10)).isoformat()},
            {"value": 40.4, "date": (date.today() - timedelta(days=120)).isoformat()},
        ]
        val, _ = _max_in_window(rows, 180, date.today())
        assert val == 40.4          # the fresh slow trail effort is ignored


class TestVdotAnchor:
    def test_sticky_confirmed_value_not_overwritten_by_low_window_max(self, db):
        """The Müggelturm case: confirmed 41 stays; the trail 35.7 only suggests."""
        _ins(db, "vdot", 41.0, "confirmed", days_ago=220, confidence="high", active=1)
        _ins(db, "vdot", 35.7, "race_observation", days_ago=30, confidence="low")
        a = get_calibration_anchor(db, "vdot")
        assert a["value"] == 41.0                      # sticky — not the 35.7 window max
        assert a["suggestion"]["value"] == 35.7        # surfaced as a suggestion
        assert a["suggestion"]["differs"] is True      # → sync would prompt accept/reject
        assert a["stale"] is True                      # confirmed 41 is older than 180d

    def test_bootstrap_uses_windowed_max_when_no_confirmed(self, db):
        """No confirmed row yet → value falls back to the windowed max."""
        _ins(db, "vdot", 35.7, "race_observation", days_ago=30, confidence="low")
        _ins(db, "vdot", 40.9, "race_observation", days_ago=60, confidence="medium")
        a = get_calibration_anchor(db, "vdot")
        assert a["value"] == 40.9
        assert a["method"] == "policy"

    def test_device_vo2max_excluded_from_observations(self, db):
        """Garmin's optimistic wrist-HR estimate never enters the max."""
        _ins(db, "vdot", 49.0, "device_vo2max", days_ago=10, confidence="medium", active=1)
        _ins(db, "vdot", 38.0, "race_observation", days_ago=20, confidence="medium")
        a = get_calibration_anchor(db, "vdot")
        assert a["suggestion"]["value"] == 38.0        # 49 ignored

    def test_stale_with_no_in_window_evidence(self, db):
        """Confirmed value older than the window, nothing fresh → stale, no suggestion."""
        _ins(db, "vdot", 41.0, "confirmed", days_ago=220, confidence="high", active=1)
        a = get_calibration_anchor(db, "vdot")
        assert a["value"] == 41.0
        assert a["stale"] is True
        assert a["suggestion"] is None

    def test_fresh_confirmed_is_not_stale(self, db):
        _ins(db, "vdot", 40.0, "confirmed", days_ago=30, confidence="high", active=1)
        a = get_calibration_anchor(db, "vdot")
        assert a["stale"] is False

    def test_suggestion_within_threshold_does_not_flag_differs(self, db):
        """A suggestion within differs_materially (1.0) of active shouldn't prompt."""
        _ins(db, "vdot", 41.0, "confirmed", days_ago=200, confidence="high", active=1)
        _ins(db, "vdot", 40.5, "race_observation", days_ago=20)   # within 1.0 of 41.0
        a = get_calibration_anchor(db, "vdot")
        assert a["suggestion"]["differs"] is False


class TestMedianFamily:
    def test_lthr_uses_median_not_max(self, db):
        """A hot-day high LTHR estimate must NOT win — median resists it."""
        for v, age in [(170, 20), (172, 60), (173, 100), (181, 10)]:  # 181 = hot-day outlier
            _ins(db, "lthr", v, "race_observation", days_ago=age)
        a = get_calibration_anchor(db, "lthr")
        assert a["suggestion"]["value"] == 172.5   # median of 170/172/173/181, NOT 181
        assert a["suggestion"]["value"] < 181

    def test_aet_median_of_noisy_drift_tests(self, db):
        for v, age in [(146, 10), (155, 30), (152, 50)]:
            _ins(db, "aet", v, "drift_test", days_ago=age)
        a = get_calibration_anchor(db, "aet")
        assert a["suggestion"]["value"] == 152      # median of 146/152/155

    def test_below_min_samples_falls_back_to_recent_low_confidence(self, db):
        """LTHR needs 3; with 2 it uses the most recent at low confidence."""
        _ins(db, "lthr", 170, "race_observation", days_ago=60)
        _ins(db, "lthr", 174, "race_observation", days_ago=10)
        a = get_calibration_anchor(db, "lthr")
        assert a["suggestion"]["value"] == 174       # most recent, not the median
        assert a["suggestion"]["confidence"] == "low"

    def test_maxhr_max_family_365d_window(self, db):
        """MaxHR is a max over a 365-day window (not 180)."""
        _ins(db, "max_hr", 192, "race_candidate", days_ago=300)   # in 365d window
        _ins(db, "max_hr", 188, "activity_max", days_ago=20)
        a = get_calibration_anchor(db, "max_hr")
        assert a["suggestion"]["value"] == 192       # 300d-old peak still counts


class TestBackfillRaceVdot:
    def _seed_race(self, db, aid, days_ago, km, result_time):
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        db.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min) "
            "VALUES (?, ?, 'running', ?, 60)", (aid, d, km))
        db.execute(
            "INSERT INTO race_calendar (date, name, distance, distance_km, status, result_time, activity_id) "
            "VALUES (?, 'Race', ?, ?, 'completed', ?, ?)", (d, f"{km:g}km", km, result_time, aid))
        db.commit()

    def test_writes_informational_rows_idempotently(self, db):
        from fit.calibration import backfill_race_vdot, get_active_calibration
        self._seed_race(db, "r1", 60, 10.0, "0:45:00")
        self._seed_race(db, "r2", 30, 21.1, "1:47:00")
        assert backfill_race_vdot(db) == 2
        assert backfill_race_vdot(db) == 0          # idempotent
        rows = db.execute("SELECT value, method, active FROM calibration WHERE metric='vdot'").fetchall()
        assert len(rows) == 2
        assert all(r["method"] == "race_observation" and r["active"] == 0 for r in rows)
        # Informational → never the active calibration.
        assert get_active_calibration(db, "vdot") is None

    def test_skips_out_of_range_and_missing_time(self, db):
        from fit.calibration import backfill_race_vdot
        self._seed_race(db, "marathon", 40, 42.2, "3:30:00")   # > 25km
        self._seed_race(db, "sprint", 20, 3.0, "0:12:00")      # < 5km
        db.execute("INSERT INTO activities (id, date, type, distance_km) VALUES "
                   "('dns', '2026-01-01', 'running', 10.0)")
        db.execute("INSERT INTO race_calendar (date, name, distance, distance_km, status, activity_id) "
                   "VALUES ('2026-01-01', 'DNS', '10km', 10.0, 'completed', 'dns')")  # no time
        db.commit()
        assert backfill_race_vdot(db) == 0


class TestBackfillEffortVdot:
    def _ins_activity(self, db, aid, days_ago, km, dur, hr):
        d = (date.today() - timedelta(days=days_ago)).isoformat()
        db.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min, avg_hr) "
            "VALUES (?, ?, 'running', ?, ?, ?)", (aid, d, km, dur, hr))
        db.commit()

    def test_writes_effort_observation_for_hard_training(self, db):
        from fit.calibration import add_calibration, backfill_effort_vdot, get_active_calibration
        add_calibration(db, "lthr", 172, "manual", "high", date.today())
        # A hard 10k at HR ≥ LTHR, no race_calendar row → qualifies as a training effort.
        self._ins_activity(db, "hard10k", 20, 10.0, 45.0, 178)
        added = backfill_effort_vdot(db)
        assert added == 1
        assert backfill_effort_vdot(db) == 0          # idempotent
        row = db.execute("SELECT method, active FROM calibration WHERE metric='vdot'").fetchone()
        assert row["method"] == "effort_observation" and row["active"] == 0
        # Informational → never the active calibration.
        assert get_active_calibration(db, "vdot") is None

    def test_skips_effort_already_a_race(self, db):
        from fit.calibration import add_calibration, backfill_effort_vdot
        add_calibration(db, "lthr", 172, "manual", "high", date.today())
        self._ins_activity(db, "dup", 20, 10.0, 45.0, 178)
        # Already represented by a race_observation row for the same activity.
        db.execute("INSERT INTO calibration (metric, value, method, confidence, date, "
                   "source_activity_id, active, flags) VALUES "
                   "('vdot', 41, 'race_observation', 'low', ?, 'dup', 0, '[]')",
                   ((date.today() - timedelta(days=20)).isoformat(),))
        db.commit()
        assert backfill_effort_vdot(db) == 0          # not double-counted


class TestNoPolicyFallback:
    def test_metric_without_policy_uses_legacy_selection(self, db):
        """weight has no aggregation policy → legacy single-row, no suggestion."""
        _ins(db, "weight", 75.4, "scale", days_ago=2, confidence="high", active=1)
        a = get_calibration_anchor(db, "weight")
        assert a["value"] == 75.4
        assert a["suggestion"] is None
