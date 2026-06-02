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
        _ins(db, "vdot", 35.7, "race_estimate", days_ago=30, confidence="low")
        a = get_calibration_anchor(db, "vdot")
        assert a["value"] == 41.0                      # sticky — not the 35.7 window max
        assert a["suggestion"]["value"] == 35.7        # surfaced as a suggestion
        assert a["suggestion"]["differs"] is True      # → sync would prompt accept/reject
        assert a["stale"] is True                      # confirmed 41 is older than 180d

    def test_bootstrap_uses_windowed_max_when_no_confirmed(self, db):
        """No confirmed row yet → value falls back to the windowed max."""
        _ins(db, "vdot", 35.7, "race_estimate", days_ago=30, confidence="low")
        _ins(db, "vdot", 40.9, "race_estimate", days_ago=60, confidence="medium")
        a = get_calibration_anchor(db, "vdot")
        assert a["value"] == 40.9
        assert a["method"] == "policy"

    def test_garmin_estimate_excluded_from_observations(self, db):
        """Garmin's optimistic wrist-HR estimate never enters the max."""
        _ins(db, "vdot", 49.0, "garmin_estimate", days_ago=10, confidence="medium", active=1)
        _ins(db, "vdot", 38.0, "race_estimate", days_ago=20, confidence="medium")
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
        _ins(db, "vdot", 40.5, "race_estimate", days_ago=20)   # within 1.0 of 41.0
        a = get_calibration_anchor(db, "vdot")
        assert a["suggestion"]["differs"] is False


class TestNoPolicyFallback:
    def test_metric_without_policy_uses_legacy_selection(self, db):
        """weight has no aggregation policy → legacy single-row, no suggestion."""
        _ins(db, "weight", 75.4, "scale", days_ago=2, confidence="high", active=1)
        a = get_calibration_anchor(db, "weight")
        assert a["value"] == 75.4
        assert a["suggestion"] is None
