"""Tests for fit/calibration.py — staleness, extraction, lifecycle, status."""

from datetime import date, timedelta


from fit.calibration import (
    add_calibration,
    derive_confidence,
    derive_flags,
    extract_lthr_from_race,
    extract_max_hr_from_activity,
    get_active_calibration,
    get_calibration_history,
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
        add_calibration(db, "lthr", 172, "race_candidate", "medium", date.today())
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
        add_calibration(db, "lthr", 172, "race_candidate", "high", date.today(),
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
        add_calibration(db, "vo2max", 49, "device_vo2max", "medium", date.today())
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
        add_calibration(db, "aet", 145, "drift_test", "medium", today)
        add_calibration(db, "weight", 78, "scale", "high", today)
        add_calibration(db, "vo2max", 49, "device_vo2max", "medium", today)
        status = get_calibration_status(db)
        assert len(status) == 5  # max_hr, lthr, aet, weight, vo2max
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
        assert len(status) == 5  # max_hr, lthr, aet, weight, vo2max
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


# ════════════════════════════════════════════════════════════════
# Max HR Extraction from Activity
# ════════════════════════════════════════════════════════════════


class TestMaxHRExtraction:
    """extract_max_hr_from_activity returns the observed peak when it raises
    the current calibration — the body just showed a higher max."""

    # Happy
    def test_higher_than_current(self):
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 195}, current_max_hr=192,
        )
        assert observed == 195.0

    def test_no_prior_calibration(self):
        """When current_max_hr is None, any plausible reading is accepted."""
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 188}, current_max_hr=None,
        )
        assert observed == 188.0

    # Unhappy — must NOT raise calibration on noise / non-improvements
    def test_equal_to_current_no_update(self):
        """Calibration should only move when there's a real improvement."""
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 192}, current_max_hr=192,
        )
        assert observed is None

    def test_one_bpm_above_ignored_as_noise(self):
        """+1 bpm is treated as sensor noise, not a real new max."""
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 193}, current_max_hr=192,
        )
        assert observed is None

    def test_two_bpm_above_accepted(self):
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 194}, current_max_hr=192,
        )
        assert observed == 194.0

    def test_below_current_no_update(self):
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 180}, current_max_hr=192,
        )
        assert observed is None

    def test_implausibly_high_rejected(self):
        """>215 bpm is almost always a strap glitch."""
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 220}, current_max_hr=192,
        )
        assert observed is None

    def test_implausibly_low_rejected(self):
        """<140 bpm is too low to be a trained adult runner's max."""
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 130}, current_max_hr=None,
        )
        assert observed is None

    def test_cycling_ignored(self):
        """HR-max derived from cycling has different physiology — skip."""
        observed = extract_max_hr_from_activity(
            {"type": "cycling", "max_hr": 200}, current_max_hr=192,
        )
        assert observed is None

    def test_track_running_accepted(self):
        """track_running is in RUNNING_TYPES; peaks there should auto-raise."""
        observed = extract_max_hr_from_activity(
            {"type": "track_running", "max_hr": 200}, current_max_hr=192,
        )
        assert observed == 200.0

    def test_trail_running_accepted(self):
        """trail_running is in RUNNING_TYPES; peaks there should auto-raise."""
        observed = extract_max_hr_from_activity(
            {"type": "trail_running", "max_hr": 198}, current_max_hr=192,
        )
        assert observed == 198.0

    def test_missing_max_hr_field(self):
        observed = extract_max_hr_from_activity(
            {"type": "running"}, current_max_hr=192,
        )
        assert observed is None

    def test_zero_max_hr(self):
        observed = extract_max_hr_from_activity(
            {"type": "running", "max_hr": 0}, current_max_hr=192,
        )
        assert observed is None

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


# ════════════════════════════════════════════════════════════════
# Flag taxonomy + confidence rubric (calibration-history change)
# ════════════════════════════════════════════════════════════════


class TestDeriveFlags:
    def test_implausible_max_hr(self):
        # 220 > 215 upper envelope
        flags = derive_flags("max_hr", 220, "race_candidate", None)
        assert "implausible_value" in flags

    def test_implausible_lthr(self):
        # 120 < 130 lower envelope
        flags = derive_flags("lthr", 120, "race_candidate", None)
        assert "implausible_value" in flags

    def test_plausible_no_flag(self):
        flags = derive_flags("max_hr", 195, "race_candidate", None)
        assert flags == []

    def test_agrees_with_prior_within_tolerance(self):
        prior = {"value": 172, "date": (date.today() - timedelta(days=30)).isoformat()}
        flags = derive_flags("lthr", 171, "race_candidate", prior)
        assert "agrees_with_prior" in flags

    def test_outside_tolerance_no_agreement(self):
        prior = {"value": 172, "date": (date.today() - timedelta(days=30)).isoformat()}
        flags = derive_flags("lthr", 180, "race_candidate", prior)
        assert "agrees_with_prior" not in flags

    def test_unexpected_drop_within_12_weeks(self):
        # max_hr: drop >2 in <12 weeks
        prior = {"value": 195, "date": (date.today() - timedelta(days=30)).isoformat()}
        flags = derive_flags("max_hr", 188, "race_candidate", prior)
        assert "unexpected_direction" in flags

    def test_old_drop_not_flagged(self):
        # Same drop but >12 weeks → real age-related decline, not anomaly
        prior = {"value": 195, "date": (date.today() - timedelta(days=200)).isoformat()}
        flags = derive_flags("max_hr", 188, "race_candidate", prior)
        assert "unexpected_direction" not in flags

    def test_new_peak_max_hr_upward(self):
        prior = {"value": 192, "date": (date.today() - timedelta(days=200)).isoformat()}
        flags = derive_flags("max_hr", 200, "race_candidate", prior)
        assert "new_peak" in flags

    def test_no_new_peak_for_activity_max(self):
        """activity_max (non-race) doesn't get new_peak — too weak a context."""
        prior = {"value": 192, "date": (date.today() - timedelta(days=200)).isoformat()}
        flags = derive_flags("max_hr", 200, "activity_max", prior)
        assert "new_peak" not in flags
        assert "weak_context" in flags

    def test_weak_context_on_activity_max(self):
        flags = derive_flags("max_hr", 195, "activity_max", None)
        assert "weak_context" in flags


class TestDeriveConfidence:
    def test_manual_is_high(self):
        assert derive_confidence("manual", []) == "high"

    def test_implausible_demotes_to_low(self):
        assert derive_confidence("manual", ["implausible_value"]) == "low"

    def test_weak_context_is_low(self):
        assert derive_confidence("activity_max", ["weak_context"]) == "low"

    def test_unexpected_direction_is_low(self):
        assert derive_confidence("race_candidate", ["unexpected_direction"]) == "low"

    def test_agreement_is_high(self):
        assert derive_confidence("race_candidate", ["agrees_with_prior"]) == "high"

    def test_new_peak_is_high(self):
        assert derive_confidence("race_candidate", ["new_peak"]) == "high"

    def test_default_race_candidate_is_medium(self):
        assert derive_confidence("race_candidate", []) == "medium"

    def test_blocker_beats_agreement(self):
        """An implausible reading can't be rescued by also agreeing."""
        assert derive_confidence("race_candidate", ["agrees_with_prior", "implausible_value"]) == "low"


class TestGetActiveCalibrationConfidenceAware:
    """get_active_calibration should prefer higher confidence over newer date."""

    def test_high_beats_newer_low(self, db):
        # Insert older high, newer low — high should win
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active) "
            "VALUES ('max_hr', 192, 'manual', 'high', date('now', '-60 days'), 0)"
        )
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
            "VALUES ('max_hr', 220, 'race_candidate', 'low', date('now', '-10 days'), 1, '[\"implausible_value\"]')"
        )
        db.commit()
        active = get_active_calibration(db, "max_hr")
        assert active["value"] == 192

    def test_newer_wins_within_same_confidence(self, db):
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active) "
            "VALUES ('max_hr', 192, 'manual', 'high', date('now', '-60 days'), 0)"
        )
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active) "
            "VALUES ('max_hr', 195, 'manual', 'high', date('now', '-10 days'), 1)"
        )
        db.commit()
        active = get_active_calibration(db, "max_hr")
        assert active["value"] == 195

    def test_stale_high_loses_to_fresh_medium(self, db):
        """When the high-conf row is past staleness, the fresh medium wins."""
        # lthr staleness threshold is 56 days
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active) "
            "VALUES ('lthr', 172, 'manual', 'high', date('now', '-200 days'), 0)"
        )
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active) "
            "VALUES ('lthr', 175, 'race_candidate', 'medium', date('now', '-10 days'), 1)"
        )
        db.commit()
        active = get_active_calibration(db, "lthr")
        # Only fresh row was in pool
        assert active["value"] == 175


class TestGetCalibrationHistory:
    def test_returns_oldest_first(self, db):
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
            "VALUES ('max_hr', 192, 'manual', 'high', '2025-10-19', 0, '[]')"
        )
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
            "VALUES ('max_hr', 195, 'race_candidate', 'high', '2026-04-15', 1, '[\"new_peak\"]')"
        )
        db.commit()
        rows = get_calibration_history(db, "max_hr")
        assert len(rows) == 2
        assert rows[0]["date"] == "2025-10-19"
        assert rows[1]["date"] == "2026-04-15"
        # flags parsed as a list
        assert rows[0]["flags"] == []
        assert rows[1]["flags"] == ["new_peak"]

    def test_empty_when_metric_unseen(self, db):
        assert get_calibration_history(db, "aet") == []


# ════════════════════════════════════════════════════════════════
# AeT extraction from steady-pace long runs
# ════════════════════════════════════════════════════════════════


from fit.calibration import extract_aet_from_steady_run


class TestExtractAetFromSteadyRun:
    def _splits(self, n: int, pace_sec: float, first_half_hr: float, second_half_hr: float,
                pace_jitter: float = 5.0) -> list[dict]:
        """Build N km splits with given paces (with small jitter) and HR halves."""
        out = []
        mid = n // 2
        for i in range(n):
            hr = first_half_hr if i < mid else second_half_hr
            out.append({
                "split_num": i + 1,
                "distance_km": 1.0,
                "pace_sec_per_km": pace_sec + ((-1) ** i) * pace_jitter,
                "avg_hr": hr,
            })
        return out

    def test_direct_estimate_when_drift_5_to_7(self):
        # drift 6%, avg HR ~150
        splits = self._splits(15, pace_sec=360, first_half_hr=146, second_half_hr=155)
        activity = {"type": "running", "distance_km": 15.0, "avg_hr": 150}
        result = extract_aet_from_steady_run(activity, splits)
        assert result is not None
        assert result["classification"] == "direct_estimate"
        assert 5 <= result["drift_pct"] <= 7

    def test_lower_bound_when_drift_under_5(self):
        splits = self._splits(15, pace_sec=360, first_half_hr=145, second_half_hr=149)
        activity = {"type": "running", "distance_km": 15.0, "avg_hr": 147}
        result = extract_aet_from_steady_run(activity, splits)
        assert result is not None
        assert result["classification"] == "lower_bound"

    def test_upper_bound_when_drift_over_7(self):
        splits = self._splits(15, pace_sec=360, first_half_hr=145, second_half_hr=160)
        activity = {"type": "running", "distance_km": 15.0, "avg_hr": 152}
        result = extract_aet_from_steady_run(activity, splits)
        assert result is not None
        assert result["classification"] == "upper_bound"

    def test_no_extract_for_negative_drift(self):
        """Negative drift (warmup or fueling kicked in) → not a valid AeT signal."""
        splits = self._splits(15, pace_sec=360, first_half_hr=160, second_half_hr=150)
        activity = {"type": "running", "distance_km": 15.0, "avg_hr": 155}
        result = extract_aet_from_steady_run(activity, splits)
        assert result is None

    def test_no_extract_for_too_short(self):
        splits = self._splits(10, pace_sec=360, first_half_hr=145, second_half_hr=152)
        activity = {"type": "running", "distance_km": 10.0, "avg_hr": 148}
        result = extract_aet_from_steady_run(activity, splits)
        assert result is None

    def test_no_extract_for_non_steady_pace(self):
        # Big jitter → pace stddev > 15 sec/km
        splits = self._splits(15, pace_sec=360, first_half_hr=145, second_half_hr=152,
                              pace_jitter=30.0)
        activity = {"type": "running", "distance_km": 15.0, "avg_hr": 148}
        result = extract_aet_from_steady_run(activity, splits)
        assert result is None

    def test_no_extract_for_cycling(self):
        splits = self._splits(20, pace_sec=120, first_half_hr=140, second_half_hr=147)
        activity = {"type": "cycling", "distance_km": 40.0, "avg_hr": 143}
        result = extract_aet_from_steady_run(activity, splits)
        assert result is None

    def test_no_extract_when_no_splits(self):
        activity = {"type": "running", "distance_km": 18.0, "avg_hr": 150}
        result = extract_aet_from_steady_run(activity, [])
        assert result is None

    def test_track_running_accepted(self):
        splits = self._splits(15, pace_sec=300, first_half_hr=148, second_half_hr=157)
        activity = {"type": "track_running", "distance_km": 15.0, "avg_hr": 152}
        result = extract_aet_from_steady_run(activity, splits)
        assert result is not None


# ════════════════════════════════════════════════════════════════
# Informational methods (race_observation) + LTHR history backfill
# ════════════════════════════════════════════════════════════════


def _add_race(db, activity_id, d, name, distance_km, avg_hr, status="completed"):
    """Insert a completed race + its linked activity into the live-schema db."""
    db.execute(
        "INSERT INTO activities (id, date, type, name, distance_km, duration_min, avg_hr) "
        "VALUES (?, ?, 'running', ?, ?, ?, ?)",
        (activity_id, d, name, distance_km, distance_km * 5.5, avg_hr),
    )
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, status, activity_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (d, name, f"{distance_km:g}km", distance_km, status, activity_id),
    )
    db.commit()


class TestInformationalMethods:
    def test_race_observation_never_active(self, db):
        """A recent race_observation row must not displace an older authoritative one."""
        add_calibration(db, "lthr", 172, "race_candidate", "medium", date(2025, 10, 19))
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
            "VALUES ('lthr', 164, 'race_observation', 'medium', ?, 0, '[]')",
            (date.today().isoformat(),),  # more recent — would win if eligible
        )
        db.commit()
        active = get_active_calibration(db, "lthr")
        assert active["value"] == 172
        assert active["method"] == "race_candidate"

    def test_all_informational_returns_none(self, db):
        """If only race_observation rows exist, there's no active calibration."""
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
            "VALUES ('lthr', 175, 'race_observation', 'medium', ?, 0, '[]')",
            (date.today().isoformat(),),
        )
        db.commit()
        assert get_active_calibration(db, "lthr") is None

    def test_history_still_includes_race_observation(self, db):
        """The chart history shows informational rows even though they're not active."""
        add_calibration(db, "lthr", 172, "race_candidate", "medium", date(2025, 10, 19))
        db.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
            "VALUES ('lthr', 175, 'race_observation', 'medium', '2026-03-22', 0, '[]')",
        )
        db.commit()
        hist = get_calibration_history(db, "lthr")
        methods = {h["method"] for h in hist}
        assert "race_observation" in methods and "race_candidate" in methods


class TestBackfillRaceLthr:
    def test_builds_history_without_changing_active(self, db):
        from fit.calibration import backfill_race_lthr
        add_calibration(db, "lthr", 172, "race_candidate", "medium", date(2025, 10, 19))
        _add_race(db, "r1", "2026-03-22", "Müggelturm HM", 21.15, 173)  # → 175
        _add_race(db, "r2", "2025-07-26", "10k Race", 10.1, 175)        # → 173
        added = backfill_race_lthr(db)
        assert added == 2
        # Active is unchanged — still the authoritative 172.
        assert get_active_calibration(db, "lthr")["value"] == 172
        # But history now carries the race estimates.
        ests = [h for h in get_calibration_history(db, "lthr") if h["method"] == "race_observation"]
        assert sorted(e["value"] for e in ests) == [173, 175]

    def test_idempotent(self, db):
        from fit.calibration import backfill_race_lthr
        _add_race(db, "r1", "2026-03-22", "HM", 21.15, 173)
        assert backfill_race_lthr(db) == 1
        assert backfill_race_lthr(db) == 0  # second run adds nothing

    def test_excludes_sub_10km_races(self, db):
        from fit.calibration import backfill_race_lthr
        _add_race(db, "r1", "2026-04-19", "5K", 4.94, 171)  # too short for LTHR
        assert backfill_race_lthr(db) == 0

    def test_skips_races_without_avg_hr(self, db):
        from fit.calibration import backfill_race_lthr
        db.execute(
            "INSERT INTO activities (id, date, type, name, distance_km, duration_min, avg_hr) "
            "VALUES ('r1', '2026-03-22', 'running', 'HM', 21.0, 120, NULL)"
        )
        db.execute(
            "INSERT INTO race_calendar (date, name, distance, distance_km, status, activity_id) "
            "VALUES ('2026-03-22', 'HM', '21km', 21.0, 'completed', 'r1')"
        )
        db.commit()
        assert backfill_race_lthr(db) == 0
