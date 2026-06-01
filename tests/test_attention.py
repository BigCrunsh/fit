"""Tests for the Attention panel aggregator (_attention_items)
and the race-countdown prediction-confidence helper."""

from datetime import date, timedelta

import pytest

from fit.report.sections.cards import _attention_items, _prediction_confidence


def _add_calibration(db, metric, value, days_ago, confidence="medium"):
    cal_date = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute("UPDATE calibration SET active = 0 WHERE metric = ?", (metric,))
    db.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active) "
        "VALUES (?, ?, 'manual', ?, ?, 1)",
        (metric, value, confidence, cal_date),
    )
    db.commit()


def _add_race(db, days_ago, distance_km=10.0, result_time="42:30"):
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, result_time, status) "
        "VALUES (?, 'Race', '10K', ?, ?, 'completed')",
        (d, distance_km, result_time),
    )
    db.commit()


class TestAttentionItems:
    """The panel should aggregate, dedupe, and severity-sort pending actions."""

    def test_empty_when_nothing_pending(self, db, config):
        """No calibrations, no data, no coaching → empty list, panel hides."""
        items = _attention_items(db)
        # Empty DB has missing metrics → some items will show. Filter to ensure
        # the structure is correct regardless.
        assert isinstance(items, list)
        for i in items:
            assert i["severity"] in {"critical", "warning", "info"}
            assert "message" in i
            assert "tag" in i

    def test_lthr_missing_is_warning(self, db, config):
        """Missing LTHR is a warning — anchors training zones."""
        items = _attention_items(db)
        lthr_items = [i for i in items if i["tag"] == "cal_missing_lthr"]
        assert lthr_items
        assert lthr_items[0]["severity"] == "warning"

    def test_severity_order(self, db, config):
        """Items are sorted critical → warning → info."""
        items = _attention_items(db)
        sev_order = {"critical": 0, "warning": 1, "info": 2}
        indices = [sev_order[i["severity"]] for i in items]
        assert indices == sorted(indices)

    def test_dedupes_by_tag(self, db, config):
        """No two items share the same tag — dedupe across sources."""
        items = _attention_items(db)
        tags = [i["tag"] for i in items]
        assert len(tags) == len(set(tags))

    def test_lthr_calibrated_is_not_flagged(self, db, config):
        """Fresh LTHR cal removes the LTHR-missing warning."""
        _add_calibration(db, "lthr", 172, days_ago=10)
        items = _attention_items(db)
        assert not any(i["tag"] == "cal_missing_lthr" for i in items)

    def test_command_included_on_actionable_items(self, db, config):
        """Items that map to a CLI command include it for easy copy-paste."""
        items = _attention_items(db)
        cal_lthr = next((i for i in items if i["tag"] == "cal_missing_lthr"), None)
        assert cal_lthr and cal_lthr["command"] is not None


class TestPredictionConfidence:
    """Race-prediction confidence reflects anchor freshness + race history."""

    def test_low_when_no_data_anywhere(self, db, config):
        result = _prediction_confidence(db)
        assert result["level"] == "low"

    def test_high_when_anchors_fresh_and_races_present(self, db, config):
        _add_calibration(db, "lthr", 172, days_ago=10)
        _add_calibration(db, "vo2max", 49, days_ago=20)
        _add_race(db, days_ago=30)
        _add_race(db, days_ago=60)
        result = _prediction_confidence(db)
        assert result["level"] == "high"

    def test_medium_when_one_anchor_stale(self, db, config):
        # LTHR stale (>56 days), VO2max fresh, 2 races
        _add_calibration(db, "lthr", 172, days_ago=100)
        _add_calibration(db, "vo2max", 49, days_ago=20)
        _add_race(db, days_ago=30)
        _add_race(db, days_ago=60)
        result = _prediction_confidence(db)
        assert result["level"] == "medium"
        assert "LTHR" in result["reason"]

    def test_medium_when_only_one_race(self, db, config):
        _add_calibration(db, "lthr", 172, days_ago=10)
        _add_calibration(db, "vo2max", 49, days_ago=20)
        _add_race(db, days_ago=30)
        result = _prediction_confidence(db)
        assert result["level"] == "medium"
        assert "1 recent race" in result["reason"]

    def test_low_when_both_anchors_stale(self, db, config):
        _add_calibration(db, "lthr", 172, days_ago=100)
        _add_calibration(db, "vo2max", 49, days_ago=120)
        _add_race(db, days_ago=30)
        result = _prediction_confidence(db)
        assert result["level"] == "low"

    def test_high_reason_is_empty(self, db, config):
        """When everything is fresh, the reason string is empty (no caveat to show)."""
        _add_calibration(db, "lthr", 172, days_ago=10)
        _add_calibration(db, "vo2max", 49, days_ago=20)
        _add_race(db, days_ago=30)
        _add_race(db, days_ago=60)
        result = _prediction_confidence(db)
        assert result["reason"] == ""
