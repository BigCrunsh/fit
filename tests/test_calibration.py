"""Tests for fit/calibration.py — staleness, extraction, lifecycle, status."""

from datetime import date, timedelta

import pytest

from fit.calibration import (
    STALENESS_THRESHOLDS,
    add_calibration,
    extract_lthr_from_race,
    get_active_calibration,
    get_calibration_status,
    is_stale,
)


# ════════════════════════════════════════════════════════════════
# Active Calibration
# ════════════════════════════════════════════════════════════════


class TestActiveCalibration:
    # Happy
    def test_get_existing(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today())
        cal = get_active_calibration(db, "max_hr")
        assert cal is not None
        assert cal["value"] == 192

    def test_different_metrics_independent(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today())
        add_calibration(db, "lthr", 172, "race_extract", "medium", date.today())
        assert get_active_calibration(db, "max_hr")["value"] == 192
        assert get_active_calibration(db, "lthr")["value"] == 172

    def test_returns_dict(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today())
        cal = get_active_calibration(db, "max_hr")
        assert isinstance(cal, dict)

    def test_new_deactivates_old(self, db):
        add_calibration(db, "max_hr", 190, "manual", "high", date(2025, 1, 1))
        add_calibration(db, "max_hr", 192, "race", "high", date(2025, 6, 1))
        cal = get_active_calibration(db, "max_hr")
        assert cal["value"] == 192
        old = db.execute("SELECT COUNT(*) FROM calibration WHERE metric='max_hr' AND active=0").fetchone()[0]
        assert old == 1

    def test_source_activity_id_stored(self, db):
        add_calibration(db, "lthr", 172, "race_extract", "high", date.today(),
                        source_activity_id="act-123")
        cal = get_active_calibration(db, "lthr")
        assert cal["source_activity_id"] == "act-123"

    def test_notes_stored(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today(), notes="From race")
        cal = get_active_calibration(db, "max_hr")
        assert cal["notes"] == "From race"

    # Unhappy
    def test_get_missing(self, db):
        assert get_active_calibration(db, "max_hr") is None

    def test_get_wrong_metric(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today())
        assert get_active_calibration(db, "lthr") is None

    def test_deactivated_not_returned(self, db):
        add_calibration(db, "max_hr", 190, "manual", "high", date(2025, 1, 1))
        add_calibration(db, "max_hr", 192, "race", "high", date(2025, 6, 1))
        # Only the latest (192) should be returned
        cal = get_active_calibration(db, "max_hr")
        assert cal["value"] == 192

    def test_multiple_adds_only_latest_active(self, db):
        """After 3 adds, only 1 should be active."""
        add_calibration(db, "max_hr", 188, "manual", "low", date(2024, 1, 1))
        add_calibration(db, "max_hr", 190, "manual", "medium", date(2024, 6, 1))
        add_calibration(db, "max_hr", 192, "race", "high", date(2025, 1, 1))
        active_count = db.execute("SELECT COUNT(*) FROM calibration WHERE metric='max_hr' AND active=1").fetchone()[0]
        assert active_count == 1
        cal = get_active_calibration(db, "max_hr")
        assert cal["value"] == 192


# ════════════════════════════════════════════════════════════════
# Staleness
# ════════════════════════════════════════════════════════════════


class TestStaleness:
    # Happy
    def test_max_hr_fresh(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today())
        assert is_stale(db, "max_hr") is False

    def test_lthr_fresh(self, db):
        add_calibration(db, "lthr", 172, "time_trial", "high", date.today())
        assert is_stale(db, "lthr") is False

    def test_weight_fresh(self, db):
        add_calibration(db, "weight", 78, "scale", "high", date.today())
        assert is_stale(db, "weight") is False

    def test_vo2max_fresh(self, db):
        add_calibration(db, "vo2max", 49, "garmin_estimate", "medium", date.today())
        assert is_stale(db, "vo2max") is False

    # Unhappy
    def test_max_hr_stale_13_months(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today() - timedelta(days=400))
        assert is_stale(db, "max_hr") is True

    def test_max_hr_exactly_at_threshold(self, db):
        """Exactly 365 days is NOT stale (threshold is >)."""
        add_calibration(db, "max_hr", 192, "manual", "high", date.today() - timedelta(days=365))
        assert is_stale(db, "max_hr") is False

    def test_max_hr_just_past_threshold(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today() - timedelta(days=366))
        assert is_stale(db, "max_hr") is True

    def test_lthr_stale_9_weeks(self, db):
        add_calibration(db, "lthr", 172, "time_trial", "high", date.today() - timedelta(days=63))
        assert is_stale(db, "lthr") is True

    def test_lthr_exactly_at_threshold(self, db):
        """Exactly 56 days (8 weeks) is NOT stale."""
        add_calibration(db, "lthr", 172, "time_trial", "high", date.today() - timedelta(days=56))
        assert is_stale(db, "lthr") is False

    def test_lthr_just_past_threshold(self, db):
        add_calibration(db, "lthr", 172, "time_trial", "high", date.today() - timedelta(days=57))
        assert is_stale(db, "lthr") is True

    def test_weight_stale_8_days(self, db):
        add_calibration(db, "weight", 78, "scale", "high", date.today() - timedelta(days=8))
        assert is_stale(db, "weight") is True

    def test_weight_exactly_at_threshold(self, db):
        add_calibration(db, "weight", 78, "scale", "high", date.today() - timedelta(days=7))
        assert is_stale(db, "weight") is False

    def test_vo2max_stale(self, db):
        add_calibration(db, "vo2max", 49, "garmin", "medium", date.today() - timedelta(days=91))
        assert is_stale(db, "vo2max") is True

    def test_missing_is_stale(self, db):
        assert is_stale(db, "max_hr") is True

    def test_unknown_metric_defaults_to_365(self, db):
        add_calibration(db, "unknown", 42, "manual", "low", date.today())
        assert is_stale(db, "unknown") is False

    def test_future_date_not_stale(self, db):
        """A calibration in the future should not be stale."""
        add_calibration(db, "max_hr", 192, "manual", "high", date.today() + timedelta(days=30))
        assert is_stale(db, "max_hr") is False


# ════════════════════════════════════════════════════════════════
# Calibration Status
# ════════════════════════════════════════════════════════════════


class TestCalibrationStatus:
    # Happy
    def test_all_present_and_fresh(self, db):
        today = date.today()
        add_calibration(db, "max_hr", 192, "race", "high", today)
        add_calibration(db, "lthr", 172, "time_trial", "high", today)
        add_calibration(db, "weight", 78, "scale", "high", today)
        add_calibration(db, "vo2max", 49, "garmin_estimate", "medium", today)
        status = get_calibration_status(db)
        assert len(status) == 4
        assert all(not s["stale"] for s in status)
        assert all(not s["missing"] for s in status)
        assert all(s["retest_prompt"] is None for s in status)

    def test_mixed(self, db):
        add_calibration(db, "max_hr", 192, "manual", "high", date.today())
        status = get_calibration_status(db)
        max_hr = [s for s in status if s["metric"] == "max_hr"][0]
        assert not max_hr["stale"]
        assert not max_hr["missing"]
        lthr = [s for s in status if s["metric"] == "lthr"][0]
        assert lthr["missing"]

    def test_days_ago_and_days_until_stale(self, db):
        add_calibration(db, "max_hr", 192, "race", "high", date.today() - timedelta(days=10))
        status = get_calibration_status(db)
        max_hr = [s for s in status if s["metric"] == "max_hr"][0]
        assert max_hr["days_ago"] == 10
        assert max_hr["days_until_stale"] == 355

    # Unhappy
    def test_all_missing(self, db):
        status = get_calibration_status(db)
        assert len(status) == 4
        assert all(s["missing"] for s in status)
        assert all(s["stale"] for s in status)

    def test_retest_prompts_for_stale(self, db):
        add_calibration(db, "lthr", 172, "time_trial", "high", date.today() - timedelta(days=100))
        status = get_calibration_status(db)
        lthr = [s for s in status if s["metric"] == "lthr"][0]
        assert lthr["retest_prompt"] is not None

    def test_retest_prompt_for_missing(self, db):
        """Missing metrics should also get retest prompts."""
        status = get_calibration_status(db)
        for s in status:
            assert s["retest_prompt"] is not None

    def test_stale_has_no_days_ago(self, db):
        """Stale calibrations should not have days_ago/days_until_stale."""
        add_calibration(db, "max_hr", 192, "manual", "high", date.today() - timedelta(days=400))
        status = get_calibration_status(db)
        max_hr = [s for s in status if s["metric"] == "max_hr"][0]
        assert "days_ago" not in max_hr or max_hr.get("days_ago") is None


# ════════════════════════════════════════════════════════════════
# LTHR Extraction from Race
# ════════════════════════════════════════════════════════════════


class TestLTHRExtraction:
    # Happy
    def test_from_hm(self):
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race",
            "distance_km": 21.1, "avg_hr": 172, "name": "HM",
        })
        assert lthr is not None
        assert 170 <= lthr <= 175

    def test_from_10k(self):
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race",
            "distance_km": 10, "avg_hr": 178, "name": "10k",
        })
        assert lthr is not None

    def test_from_marathon(self):
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race",
            "distance_km": 42.2, "avg_hr": 165, "name": "Marathon",
        })
        assert lthr is not None
        assert lthr > 165  # marathon correction should increase

    def test_10k_correction_lower(self):
        """10k correction is 0.99, so LTHR should be slightly below avg_hr."""
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race", "distance_km": 12, "avg_hr": 180,
        })
        assert lthr is not None
        assert lthr < 180

    def test_hm_correction_slightly_above(self):
        """HM correction is 1.01, so LTHR should be slightly above avg_hr."""
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race", "distance_km": 21, "avg_hr": 172,
        })
        assert lthr is not None
        assert lthr >= 172

    # Unhappy
    def test_too_short(self):
        """< 10km race should return None."""
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race",
            "distance_km": 5, "avg_hr": 180, "name": "5k",
        })
        assert lthr is None

    def test_not_a_race(self):
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "easy",
            "distance_km": 15, "avg_hr": 145, "name": "Easy",
        })
        assert lthr is None

    def test_cycling_race(self):
        lthr = extract_lthr_from_race({
            "type": "cycling", "run_type": "race",
            "distance_km": 40, "avg_hr": 160,
        })
        assert lthr is None

    def test_no_hr(self):
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race",
            "distance_km": 21, "avg_hr": None,
        })
        assert lthr is None

    def test_zero_hr(self):
        lthr = extract_lthr_from_race({
            "run_type": "race", "distance_km": 21, "avg_hr": 0,
        })
        assert lthr is None

    def test_missing_distance(self):
        lthr = extract_lthr_from_race({
            "run_type": "race", "avg_hr": 172,
        })
        assert lthr is None

    def test_zero_distance(self):
        lthr = extract_lthr_from_race({
            "run_type": "race", "distance_km": 0, "avg_hr": 172,
        })
        assert lthr is None

    def test_missing_run_type(self):
        lthr = extract_lthr_from_race({
            "distance_km": 21, "avg_hr": 172,
        })
        assert lthr is None

    def test_none_run_type(self):
        lthr = extract_lthr_from_race({
            "run_type": None, "distance_km": 21, "avg_hr": 172,
        })
        assert lthr is None

    def test_exactly_10km(self):
        """10km exactly should be included (>= 10)."""
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race", "distance_km": 10, "avg_hr": 178,
        })
        assert lthr is not None

    def test_just_under_10km(self):
        lthr = extract_lthr_from_race({
            "type": "running", "run_type": "race", "distance_km": 9.99, "avg_hr": 178,
        })
        assert lthr is None
