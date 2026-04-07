"""Tests for fit/analysis.py — zones, efficiency, run types, weekly agg, ACWR, marathon prediction."""


import pytest

from fit.analysis import (
    compute_hr_zones,
    compute_effort_class,
    compute_speed_per_bpm,
    compute_speed_per_bpm_z2,
    classify_run_type,
    predict_marathon_time,
    compute_weekly_agg,
    enrich_activity,
    _classify_zone_lthr,
    _compute_acwr,
    _compute_streak,
)


# ════════════════════════════════════════════════════════════════
# HR Zone Computation
# ════════════════════════════════════════════════════════════════


class TestHRZones:
    """Tests for compute_hr_zones — parallel max-HR + LTHR models."""

    # ── Happy path ──

    def test_z2_ceiling_at_134(self, config):
        zones = compute_hr_zones(133, config)
        assert zones["hr_zone_maxhr"] == "Z2"
        zones = compute_hr_zones(135, config)
        assert zones["hr_zone_maxhr"] == "Z3"

    def test_parallel_zones_with_lthr(self, config):
        zones = compute_hr_zones(155, config, lthr=172)
        assert zones["hr_zone_maxhr"] is not None
        assert zones["hr_zone_lthr"] is not None

    def test_all_five_zones_maxhr(self, config):
        """Each zone boundary should classify correctly."""
        assert compute_hr_zones(100, config)["hr_zone_maxhr"] == "Z1"
        assert compute_hr_zones(120, config)["hr_zone_maxhr"] == "Z2"
        assert compute_hr_zones(140, config)["hr_zone_maxhr"] == "Z3"
        assert compute_hr_zones(160, config)["hr_zone_maxhr"] == "Z4"
        assert compute_hr_zones(180, config)["hr_zone_maxhr"] == "Z5"

    def test_preferred_model_maxhr_default(self, config):
        """When zone_model is max_hr, hr_zone should match hr_zone_maxhr."""
        zones = compute_hr_zones(140, config, lthr=172)
        assert zones["hr_zone"] == zones["hr_zone_maxhr"]

    def test_preferred_model_lthr(self, config):
        """When zone_model is lthr and LTHR is present, hr_zone should match hr_zone_lthr."""
        config["profile"]["zone_model"] = "lthr"
        zones = compute_hr_zones(160, config, lthr=172)
        assert zones["hr_zone"] == zones["hr_zone_lthr"]

    def test_effort_class_set_on_zones(self, config):
        zones = compute_hr_zones(140, config)
        assert zones["effort_class"] is not None

    # ── Unhappy path ──

    def test_null_hr(self, config):
        zones = compute_hr_zones(None, config)
        assert zones["hr_zone"] is None
        assert zones["hr_zone_maxhr"] is None
        assert zones["hr_zone_lthr"] is None
        assert zones["effort_class"] is None

    def test_no_lthr_gives_null(self, config):
        zones = compute_hr_zones(155, config, lthr=None)
        assert zones["hr_zone_lthr"] is None
        assert zones["hr_zone_maxhr"] == "Z4"

    def test_hr_zero(self, config):
        """HR of 0 should still classify (falls through to Z1)."""
        zones = compute_hr_zones(0, config)
        assert zones["hr_zone_maxhr"] == "Z1"

    def test_hr_very_high(self, config):
        """HR of 999 should be Z5."""
        zones = compute_hr_zones(999, config)
        assert zones["hr_zone_maxhr"] == "Z5"

    def test_negative_hr(self, config):
        """Negative HR should fall through to Z1 (no boundary match)."""
        zones = compute_hr_zones(-10, config)
        assert zones["hr_zone_maxhr"] == "Z1"

    def test_hr_exactly_at_z2_lower_boundary(self, config):
        """HR exactly at Z2 lower boundary (115)."""
        zones = compute_hr_zones(115, config)
        assert zones["hr_zone_maxhr"] == "Z2"

    def test_hr_exactly_at_z3_boundary(self, config):
        """HR exactly at Z3 boundary (134)."""
        zones = compute_hr_zones(134, config)
        assert zones["hr_zone_maxhr"] == "Z3"

    def test_hr_exactly_at_z5_boundary(self, config):
        """HR exactly at Z5 boundary (173)."""
        zones = compute_hr_zones(173, config)
        assert zones["hr_zone_maxhr"] == "Z5"

    def test_lthr_zero_treated_as_falsy(self, config):
        """LTHR=0 should be treated as no LTHR."""
        zones = compute_hr_zones(140, config, lthr=0)
        assert zones["hr_zone_lthr"] is None

    def test_lthr_preferred_but_missing_falls_back_to_maxhr(self, config):
        """When lthr model preferred but no LTHR, fall back to max_hr."""
        config["profile"]["zone_model"] = "lthr"
        zones = compute_hr_zones(140, config, lthr=None)
        assert zones["hr_zone"] == zones["hr_zone_maxhr"]

    def test_zones_missing_from_config(self, config):
        """If zones_max_hr is missing from config, _classify_zone still returns Z1."""
        config["profile"]["zones_max_hr"] = {}
        zones = compute_hr_zones(150, config)
        assert zones["hr_zone_maxhr"] == "Z1"


class TestClassifyZoneLTHR:
    """Tests for LTHR percentage-based zone classification."""

    # Happy
    def test_lthr_zone_at_threshold(self, config):
        """100% of LTHR should be Z5."""
        zones_pct = config["profile"]["zones_lthr"]
        result = _classify_zone_lthr(172, 172, zones_pct)
        assert result == "Z5"

    # Unhappy
    def test_lthr_zone_very_low_hr(self, config):
        """Very low HR relative to LTHR falls to Z1."""
        zones_pct = config["profile"]["zones_lthr"]
        result = _classify_zone_lthr(50, 172, zones_pct)
        assert result == "Z1"

    def test_lthr_zone_empty_config(self):
        """Empty zones config falls through to Z1."""
        result = _classify_zone_lthr(150, 170, {})
        assert result == "Z1"


# ════════════════════════════════════════════════════════════════
# Effort Class
# ════════════════════════════════════════════════════════════════


class TestEffortClass:
    # Happy
    def test_five_levels(self):
        assert compute_effort_class("Z1") == "Recovery"
        assert compute_effort_class("Z2") == "Easy"
        assert compute_effort_class("Z3") == "Moderate"
        assert compute_effort_class("Z4") == "Hard"
        assert compute_effort_class("Z5") == "Very Hard"

    # Unhappy
    def test_null(self):
        assert compute_effort_class(None) is None

    def test_unknown_zone(self):
        """Unknown zone string should return 'Easy' as default."""
        assert compute_effort_class("Z6") == "Easy"

    def test_empty_string(self):
        assert compute_effort_class("") == "Easy"

    def test_lowercase_zone(self):
        """Lowercase 'z1' is not in the mapping, should default to Easy."""
        assert compute_effort_class("z1") == "Easy"


# ════════════════════════════════════════════════════════════════
# Speed Per BPM
# ════════════════════════════════════════════════════════════════


class TestSpeedPerBPM:
    # Happy
    def test_higher_is_better(self):
        slow = compute_speed_per_bpm(10.0, 60, 150)
        fast = compute_speed_per_bpm(10.0, 50, 150)
        assert fast > slow

    def test_known_value(self):
        """10km in 60min at 150bpm = (10000/60)/150 = 1.1111."""
        result = compute_speed_per_bpm(10.0, 60, 150)
        assert result == pytest.approx(1.1111, abs=0.001)

    def test_short_run(self):
        """1km in 5 min at 120 bpm."""
        result = compute_speed_per_bpm(1.0, 5, 120)
        assert result == pytest.approx(1.6667, abs=0.001)

    # Unhappy
    def test_null_distance(self):
        assert compute_speed_per_bpm(None, 50, 150) is None

    def test_null_duration(self):
        assert compute_speed_per_bpm(10, None, 150) is None

    def test_null_hr(self):
        assert compute_speed_per_bpm(10, 50, None) is None

    def test_zero_duration(self):
        assert compute_speed_per_bpm(10, 0, 150) is None

    def test_zero_hr(self):
        assert compute_speed_per_bpm(10, 50, 0) is None

    def test_zero_distance(self):
        """Zero distance with valid duration and HR should return None (falsy 0)."""
        assert compute_speed_per_bpm(0, 50, 150) is None

    def test_negative_duration(self):
        """Negative duration should return None."""
        assert compute_speed_per_bpm(10, -5, 150) is None

    def test_negative_hr(self):
        """Negative HR should return None."""
        assert compute_speed_per_bpm(10, 50, -10) is None

    def test_very_large_values(self):
        """Should still compute without overflow."""
        result = compute_speed_per_bpm(1000.0, 1, 200)
        assert result is not None
        assert result > 0

    def test_all_zeros(self):
        assert compute_speed_per_bpm(0, 0, 0) is None


class TestSpeedPerBPMZ2:
    # Happy
    def test_z2_filter_passes(self):
        assert compute_speed_per_bpm_z2(7, 45, 128, [115, 134]) is not None

    def test_z2_default_range(self):
        """Default range is [115, 134]."""
        result = compute_speed_per_bpm_z2(7, 45, 125)
        assert result is not None

    # Unhappy
    def test_hr_above_z2(self):
        assert compute_speed_per_bpm_z2(7, 45, 165, [115, 134]) is None

    def test_hr_below_z2(self):
        assert compute_speed_per_bpm_z2(7, 45, 100, [115, 134]) is None

    def test_hr_exactly_at_z2_lower(self):
        assert compute_speed_per_bpm_z2(7, 45, 115, [115, 134]) is not None

    def test_hr_exactly_at_z2_upper(self):
        assert compute_speed_per_bpm_z2(7, 45, 134, [115, 134]) is not None

    def test_null_hr(self):
        assert compute_speed_per_bpm_z2(7, 45, None, [115, 134]) is None

    def test_z2_with_zero_distance(self):
        """In Z2 range but zero distance returns None."""
        assert compute_speed_per_bpm_z2(0, 45, 125, [115, 134]) is None


# ════════════════════════════════════════════════════════════════
# Run Type Classification
# ════════════════════════════════════════════════════════════════


class TestRunType:
    # ── Happy: all 7 types ──

    def test_no_name_based_race_detection(self):
        """Classifier does NOT detect races from names — race_calendar handles that."""
        assert classify_run_type({"type": "running", "name": "Half Marathon Race", "distance_km": 21}) != "race"

    def test_race_name_classified_as_training(self):
        """Even 'Race' in name → classified as training (easy/tempo/long), not race."""
        result = classify_run_type({"type": "running", "name": "10km Race", "distance_km": 10, "hr_zone": "Z4"})
        assert result != "race"
        assert result in ("easy", "tempo", "long", "intervals", "recovery", "progression")

    def test_progression_run(self):
        assert classify_run_type({"type": "running", "name": "Progression Run", "distance_km": 10}) == "progression"

    def test_negative_split(self):
        assert classify_run_type({"type": "running", "name": "Negative split session", "distance_km": 8}) == "progression"

    def test_intervals(self):
        assert classify_run_type({"type": "running", "name": "Interval training", "distance_km": 8}) == "intervals"

    def test_fartlek(self):
        assert classify_run_type({"type": "running", "name": "Fartlek", "distance_km": 8}) == "intervals"

    def test_speed_work(self):
        assert classify_run_type({"type": "running", "name": "Speed repeats", "distance_km": 6}) == "intervals"

    def test_tempo_by_name(self):
        assert classify_run_type({"type": "running", "name": "Tempo", "distance_km": 10, "hr_zone": "Z4"}) == "tempo"

    def test_tempo_by_zone_and_distance(self):
        """Z3/Z4 + distance >= 6 = tempo even without keyword."""
        assert classify_run_type({"type": "running", "name": "Tuesday Run", "distance_km": 8, "hr_zone": "Z4"}) == "tempo"

    def test_long_run(self):
        assert classify_run_type({"type": "running", "name": "Sunday", "distance_km": 18, "hr_zone": "Z2"}) == "long"

    def test_recovery(self):
        assert classify_run_type({"type": "running", "name": "Jog", "distance_km": 4, "hr_zone": "Z1"}) == "recovery"

    def test_easy_default(self):
        assert classify_run_type({"type": "running", "name": "Easy Run", "distance_km": 7, "hr_zone": "Z2"}) == "easy"

    # ── Unhappy ──

    def test_non_running(self):
        assert classify_run_type({"type": "cycling"}) is None

    def test_empty_name(self):
        """Empty name, moderate distance, Z2 => easy."""
        assert classify_run_type({"type": "running", "name": "", "distance_km": 7, "hr_zone": "Z2"}) == "easy"

    def test_none_name(self):
        """None name should not raise."""
        result = classify_run_type({"type": "running", "name": None, "distance_km": 7, "hr_zone": "Z2"})
        assert result == "easy"

    def test_missing_name_key(self):
        """Missing 'name' key should not raise."""
        result = classify_run_type({"type": "running", "distance_km": 7, "hr_zone": "Z2"})
        assert result == "easy"

    def test_missing_distance(self):
        """Missing distance_km should default to 0."""
        result = classify_run_type({"type": "running", "name": "Morning jog"})
        assert result is not None  # should still classify

    def test_missing_type(self):
        """Missing 'type' key returns None."""
        result = classify_run_type({})
        assert result is None

    def test_long_run_absolute_floor(self):
        """12km+ is always long regardless of weekly volume."""
        assert classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 12, "hr_zone": "Z2"},
            weekly_km=100,
        ) == "long"

    def test_long_run_pct_of_weekly(self):
        """9km is long when weekly volume is 25km (>30% = 7.5km AND >=8km)."""
        assert classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 9, "hr_zone": "Z2"},
            weekly_km=25,
        ) == "long"

    def test_not_long_below_8km_floor(self):
        """7km is NOT long even if >30% of weekly volume (below 8km minimum)."""
        assert classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 7, "hr_zone": "Z2"},
            weekly_km=15,
        ) == "easy"

    def test_not_long_below_30_pct(self):
        """9km is NOT long when weekly volume is 60km (9/60 = 15% < 30%)."""
        assert classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 9, "hr_zone": "Z2"},
            weekly_km=60,
        ) == "easy"

    def test_long_run_no_weekly_km(self):
        """Without weekly_km, only absolute floor (12km) applies."""
        assert classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 11, "hr_zone": "Z2"},
        ) == "easy"
        assert classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 12, "hr_zone": "Z2"},
        ) == "long"

    def test_tempo_by_zone_but_short_distance(self):
        """Z4 but distance < 6 is NOT tempo, defaults to easy."""
        result = classify_run_type({"type": "running", "name": "Quick", "distance_km": 4, "hr_zone": "Z4"})
        assert result == "easy"

    def test_short_distance_not_race(self):
        """Short run with race-like name is NOT race (race_calendar handles that)."""
        result = classify_run_type({"type": "running", "name": "5k race", "distance_km": 3})
        assert result != "race"

    def test_half_marathon_name_not_race(self):
        """HM name is NOT auto-race (race_calendar handles that)."""
        result = classify_run_type({"type": "running", "name": "Half Marathon Race", "distance_km": 21, "hr_zone": "Z4"})
        assert result != "race"


# ════════════════════════════════════════════════════════════════
# Race Prediction
# ════════════════════════════════════════════════════════════════


class TestRacePrediction:
    # Happy
    def test_riegel_from_hm(self):
        preds = predict_marathon_time(races=[
            {"distance_km": 21.1, "time_seconds": 6572, "name": "Oct HM"},
        ], vo2max=49)
        assert len(preds["riegel"]) == 1
        assert preds["riegel"][0]["predicted_seconds"] > 0

    def test_riegel_from_10k(self):
        preds = predict_marathon_time(races=[
            {"distance_km": 10, "time_seconds": 2700, "name": "10k"},
        ])
        assert len(preds["riegel"]) == 1
        assert preds["riegel"][0]["predicted_seconds"] > 6572  # longer than from HM

    def test_vdot_prediction(self):
        preds = predict_marathon_time(races=[], vo2max=49)
        assert preds["vdot"] is not None
        assert preds["vdot"]["predicted_seconds"] > 0
        assert preds["vdot"]["predicted_pace_sec_km"] > 0

    def test_multiple_races(self):
        preds = predict_marathon_time(races=[
            {"distance_km": 10, "time_seconds": 2700, "name": "10k"},
            {"distance_km": 21.1, "time_seconds": 6000, "name": "HM"},
        ])
        assert len(preds["riegel"]) == 2

    # Unhappy
    def test_no_data(self):
        preds = predict_marathon_time(races=[], vo2max=None)
        assert preds["riegel"] == []
        assert preds["vdot"] is None

    def test_no_races(self):
        preds = predict_marathon_time(races=[])
        assert preds["riegel"] == []

    def test_zero_distance_race(self):
        """Race with d1=0 should be skipped."""
        preds = predict_marathon_time(races=[
            {"distance_km": 0, "time_seconds": 3000},
        ])
        assert preds["riegel"] == []

    def test_zero_time_race(self):
        """Race with t1=0 should be skipped."""
        preds = predict_marathon_time(races=[
            {"distance_km": 10, "time_seconds": 0},
        ])
        assert preds["riegel"] == []

    def test_negative_distance(self):
        """Negative distance should be skipped (d1 > 0 fails)."""
        preds = predict_marathon_time(races=[
            {"distance_km": -5, "time_seconds": 3000},
        ])
        assert preds["riegel"] == []

    def test_distance_longer_than_marathon(self):
        """Distance >= marathon should be skipped (d1 < marathon_km)."""
        preds = predict_marathon_time(races=[
            {"distance_km": 50, "time_seconds": 18000},
        ])
        assert preds["riegel"] == []

    def test_very_short_distance(self):
        """Very short race distance (1km) still computes."""
        preds = predict_marathon_time(races=[
            {"distance_km": 1, "time_seconds": 180, "name": "1km TT"},
        ])
        assert len(preds["riegel"]) == 1
        assert preds["riegel"][0]["predicted_seconds"] > 0

    def test_vdot_too_low(self):
        """VO2max <= 30 gives no VDOT prediction."""
        preds = predict_marathon_time(races=[], vo2max=30)
        assert preds["vdot"] is None

    def test_vdot_barely_above_threshold(self):
        preds = predict_marathon_time(races=[], vo2max=31)
        assert preds["vdot"] is not None

    def test_vdot_very_high(self):
        """Very high VO2max should not go below table minimum."""
        preds = predict_marathon_time(races=[], vo2max=100)
        assert preds["vdot"]["predicted_seconds"] > 0

    def test_missing_race_keys(self):
        """Race dict with missing keys should be skipped gracefully."""
        preds = predict_marathon_time(races=[{}])
        assert preds["riegel"] == []

    def test_race_with_name_missing(self):
        """Race without name uses distance as default label."""
        preds = predict_marathon_time(races=[
            {"distance_km": 10, "time_seconds": 2700},
        ])
        assert preds["riegel"][0]["from_race"] == "10.0km"


# ════════════════════════════════════════════════════════════════
# Weekly Aggregation
# ════════════════════════════════════════════════════════════════


class TestWeeklyAgg:
    """Tests for compute_weekly_agg — requires DB with schema."""

    def _insert_run(self, conn, day, **kwargs):
        defaults = {
            "id": f"run-{day}", "date": day, "type": "running", "name": "Easy Run",
            "distance_km": 7, "duration_min": 45, "pace_sec_per_km": 386,
            "avg_hr": 130, "avg_cadence": 172, "training_load": 100,
            "hr_zone": "Z2", "run_type": "easy",
        }
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        conn.execute(f"INSERT INTO activities ({cols}) VALUES ({placeholders})", list(defaults.values()))
        conn.commit()

    def _insert_cross(self, conn, day, **kwargs):
        defaults = {
            "id": f"cross-{day}", "date": day, "type": "cycling", "name": "Bike",
            "duration_min": 60, "training_load": 80,
        }
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        conn.execute(f"INSERT INTO activities ({cols}) VALUES ({placeholders})", list(defaults.values()))
        conn.commit()

    def _insert_health(self, conn, day, **kwargs):
        defaults = {
            "date": day, "training_readiness": 70, "sleep_duration_hours": 7.5,
            "resting_heart_rate": 55, "hrv_last_night": 45,
        }
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        conn.execute(f"INSERT INTO daily_health ({cols}) VALUES ({placeholders})", list(defaults.values()))
        conn.commit()

    # Happy
    def test_basic_week(self, db):
        """A week with 3 runs should compute correctly."""
        # 2026-W14: Monday = 2026-03-30
        for i, day in enumerate(["2026-03-30", "2026-04-01", "2026-04-03"]):
            self._insert_run(db, day, id=f"run-{i}")
        self._insert_health(db, "2026-03-30")
        result = compute_weekly_agg(db, "2026-W14")
        assert result["run_count"] == 3
        assert result["run_km"] == 21.0
        assert result["easy_run_count"] == 3
        assert result["training_days"] >= 3
        assert result["week"] == "2026-W14"

    def test_week_with_cross_training(self, db):
        """Cross-training contributes to total_load."""
        self._insert_run(db, "2026-03-30", id="run-0")
        self._insert_cross(db, "2026-03-31", id="cross-0")
        result = compute_weekly_agg(db, "2026-W14")
        assert result["run_count"] == 1
        assert result["cross_train_count"] == 1
        assert result["total_load"] == 180  # 100 + 80
        assert result["total_activities"] == 2

    def test_zone_distribution(self, db):
        """Zone time distribution should sum correctly."""
        self._insert_run(db, "2026-03-30", id="r1", duration_min=30, hr_zone="Z2")
        self._insert_run(db, "2026-04-01", id="r2", duration_min=20, hr_zone="Z4")
        result = compute_weekly_agg(db, "2026-W14")
        assert result["z2_min"] == 30.0
        assert result["z4_min"] == 20.0
        assert result["z12_pct"] == pytest.approx(60.0, abs=0.1)
        assert result["z45_pct"] == pytest.approx(40.0, abs=0.1)

    def test_quality_sessions(self, db):
        """Tempo and interval runs count as quality sessions."""
        self._insert_run(db, "2026-03-30", id="r1", run_type="tempo")
        self._insert_run(db, "2026-04-01", id="r2", run_type="intervals")
        self._insert_run(db, "2026-04-02", id="r3", run_type="easy")
        result = compute_weekly_agg(db, "2026-W14")
        assert result["quality_session_count"] == 2
        assert result["easy_run_count"] == 1

    # Unhappy
    def test_empty_week(self, db):
        """Week with no data should return zeros/Nones."""
        result = compute_weekly_agg(db, "2026-W14")
        assert result["run_count"] == 0
        assert result["run_km"] == 0.0
        assert result["run_avg_pace"] is None
        assert result["run_avg_hr"] is None
        assert result["longest_run_km"] is None
        assert result["z12_pct"] is None
        assert result["avg_readiness"] is None
        assert result["acwr"] is None

    def test_week_only_cross_training(self, db):
        """Week with only cross-training, no runs."""
        self._insert_cross(db, "2026-03-30", id="c1")
        self._insert_cross(db, "2026-04-01", id="c2")
        result = compute_weekly_agg(db, "2026-W14")
        assert result["run_count"] == 0
        assert result["cross_train_count"] == 2
        assert result["total_load"] == 160
        assert result["z12_pct"] is None  # no runs → no zone time

    def test_week_with_null_fields(self, db):
        """Activities with NULL optional fields should not crash."""
        self._insert_run(db, "2026-03-30", id="r1", avg_hr=None, avg_cadence=None,
                         pace_sec_per_km=None, training_load=None)
        result = compute_weekly_agg(db, "2026-W14")
        assert result["run_count"] == 1
        assert result["run_avg_hr"] is None
        assert result["run_avg_cadence"] is None
        assert result["run_avg_pace"] is None

    def test_health_data_with_nulls(self, db):
        """Health data with NULL fields should not crash."""
        self._insert_run(db, "2026-03-30", id="r1")
        self._insert_health(db, "2026-03-30", training_readiness=None,
                            sleep_duration_hours=None, resting_heart_rate=None, hrv_last_night=None)
        result = compute_weekly_agg(db, "2026-W14")
        assert result["avg_readiness"] is None
        assert result["avg_sleep"] is None

    def test_longest_run(self, db):
        """Longest run should be tracked."""
        self._insert_run(db, "2026-03-30", id="r1", distance_km=5)
        self._insert_run(db, "2026-04-01", id="r2", distance_km=15)
        self._insert_run(db, "2026-04-03", id="r3", distance_km=8)
        result = compute_weekly_agg(db, "2026-W14")
        assert result["longest_run_km"] == 15.0


# ════════════════════════════════════════════════════════════════
# ACWR
# ════════════════════════════════════════════════════════════════


class TestACWR:
    def _insert_weekly_agg(self, conn, week, total_load, run_count=3):
        conn.execute("""
            INSERT INTO weekly_agg (week, total_load, run_count) VALUES (?, ?, ?)
        """, (week, total_load, run_count))
        conn.commit()

    # Happy
    def test_acwr_with_history(self, db):
        """ACWR with 4 weeks of history."""
        for i, wk in enumerate(["2026-W10", "2026-W11", "2026-W12", "2026-W13"]):
            self._insert_weekly_agg(db, wk, 200)
        result = _compute_acwr(db, "2026-W14", 300)
        assert result == pytest.approx(1.5, abs=0.01)

    # Unhappy
    def test_acwr_no_history(self, db):
        """No previous weeks → ACWR is None."""
        result = _compute_acwr(db, "2026-W14", 200)
        assert result is None

    def test_acwr_only_one_week_history(self, db):
        """Only 1 previous week → fewer than 2 → None."""
        self._insert_weekly_agg(db, "2026-W13", 200)
        result = _compute_acwr(db, "2026-W14", 200)
        assert result is None

    def test_acwr_two_weeks_insufficient(self, db):
        """2 previous weeks is NOT enough — minimum is 3."""
        self._insert_weekly_agg(db, "2026-W12", 200)
        self._insert_weekly_agg(db, "2026-W13", 200)
        result = _compute_acwr(db, "2026-W14", 200)
        assert result is None

    def test_acwr_three_weeks_minimum(self, db):
        """3 previous weeks is the minimum for ACWR."""
        self._insert_weekly_agg(db, "2026-W11", 200)
        self._insert_weekly_agg(db, "2026-W12", 200)
        self._insert_weekly_agg(db, "2026-W13", 200)
        result = _compute_acwr(db, "2026-W14", 200)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_acwr_zero_chronic_load(self, db):
        """All previous weeks have 0 load → chronic=0 → None."""
        for wk in ["2026-W10", "2026-W11", "2026-W12", "2026-W13"]:
            self._insert_weekly_agg(db, wk, 0)
        result = _compute_acwr(db, "2026-W14", 200)
        assert result is None

    def test_acwr_very_high_spike(self, db):
        """Very high spike should produce high ACWR."""
        for wk in ["2026-W10", "2026-W11", "2026-W12", "2026-W13"]:
            self._insert_weekly_agg(db, wk, 100)
        result = _compute_acwr(db, "2026-W14", 500)
        assert result == pytest.approx(5.0, abs=0.01)

    def test_acwr_cross_year_boundary(self, db):
        """Week 1 should look back into previous year."""
        for wk in ["2025-W50", "2025-W51", "2025-W52", "2026-W01"]:
            self._insert_weekly_agg(db, wk, 200)
        # W02 looks back at W01, W52, W51, W50
        result = _compute_acwr(db, "2026-W02", 200)
        # Should find all 4 previous weeks
        assert result is not None


# ════════════════════════════════════════════════════════════════
# Streak
# ════════════════════════════════════════════════════════════════


class TestStreak:
    def _insert_weekly_agg(self, conn, week, run_count):
        conn.execute("INSERT INTO weekly_agg (week, run_count) VALUES (?, ?)", (week, run_count))
        conn.commit()

    # Happy
    def test_streak_with_history(self, db):
        for wk in ["2026-W11", "2026-W12", "2026-W13"]:
            self._insert_weekly_agg(db, wk, 3)
        result = _compute_streak(db, "2026-W14", 4)
        assert result == 4  # current + 3 previous

    # Unhappy
    def test_streak_current_below_3(self, db):
        """Current week has < 3 runs → streak is 0."""
        self._insert_weekly_agg(db, "2026-W13", 5)
        result = _compute_streak(db, "2026-W14", 2)
        assert result == 0

    def test_streak_broken(self, db):
        """Streak broken by a week with only 2 runs."""
        self._insert_weekly_agg(db, "2026-W11", 4)
        self._insert_weekly_agg(db, "2026-W12", 2)  # break
        self._insert_weekly_agg(db, "2026-W13", 4)
        result = _compute_streak(db, "2026-W14", 3)
        assert result == 2  # only W13 + current

    def test_streak_no_history(self, db):
        result = _compute_streak(db, "2026-W14", 4)
        assert result == 1  # just current week


# ════════════════════════════════════════════════════════════════
# Enrich Activity
# ════════════════════════════════════════════════════════════════


class TestEnrichActivity:
    # Happy
    def test_adds_all_derived_fields(self, config):
        activity = {"type": "running", "name": "Easy Run", "distance_km": 7,
                    "duration_min": 45, "avg_hr": 130}
        result = enrich_activity(activity, config, lthr=172)
        assert "hr_zone" in result
        assert "speed_per_bpm" in result
        assert "run_type" in result
        assert "max_hr_used" in result
        assert "lthr_used" in result
        assert result["lthr_used"] == 172

    # Unhappy
    def test_enrich_with_none_values(self, config):
        activity = {"type": "running", "name": "Run", "distance_km": None,
                    "duration_min": None, "avg_hr": None}
        result = enrich_activity(activity, config)
        assert result["hr_zone"] is None
        assert result["speed_per_bpm"] is None
        assert result["run_type"] == "easy"  # type is running, no keyword match → default easy


# ════════════════════════════════════════════════════════════════
# Bug Fix Tests — Phase 2 Section 1
# ════════════════════════════════════════════════════════════════


class TestACWRYearBoundary:
    """Test ACWR year-boundary handling, including 53-week years."""

    def _insert_weekly_agg(self, conn, week, total_load, run_count=3):
        conn.execute(
            "INSERT INTO weekly_agg (week, total_load, run_count) VALUES (?, ?, ?)",
            (week, total_load, run_count),
        )
        conn.commit()

    def test_week53_to_week1_transition(self, db):
        """2020 has 53 weeks. ACWR at 2021-W02 should find 2021-W01, 2020-W53, W52, W51."""
        for wk in ["2020-W51", "2020-W52", "2020-W53", "2021-W01"]:
            self._insert_weekly_agg(db, wk, 200)
        result = _compute_acwr(db, "2021-W02", 300)
        assert result is not None
        assert result == pytest.approx(1.5, abs=0.01)

    def test_week1_looks_back_into_53_week_year(self, db):
        """ACWR at 2021-W01 should look back into 2020's week 53, 52, 51, 50."""
        for wk in ["2020-W50", "2020-W51", "2020-W52", "2020-W53"]:
            self._insert_weekly_agg(db, wk, 200)
        result = _compute_acwr(db, "2021-W01", 400)
        assert result is not None
        assert result == pytest.approx(2.0, abs=0.01)

    def test_normal_year_boundary(self, db):
        """Standard 52-week year boundary (2025→2026)."""
        for wk in ["2025-W50", "2025-W51", "2025-W52", "2026-W01"]:
            self._insert_weekly_agg(db, wk, 150)
        result = _compute_acwr(db, "2026-W02", 150)
        assert result is not None
        assert result == pytest.approx(1.0, abs=0.01)


class TestStreakYearBoundary:
    """Test streak year-boundary handling, including 53-week years."""

    def _insert_weekly_agg(self, conn, week, run_count):
        conn.execute("INSERT INTO weekly_agg (week, run_count) VALUES (?, ?)", (week, run_count))
        conn.commit()

    def test_streak_across_53_week_year(self, db):
        """Streak spanning 2020-W53 → 2021-W01."""
        for wk in ["2020-W52", "2020-W53", "2021-W01"]:
            self._insert_weekly_agg(db, wk, 4)
        result = _compute_streak(db, "2021-W02", 3)
        assert result == 4  # current + 3 previous

    def test_streak_across_normal_year(self, db):
        """Streak spanning 2025-W52 → 2026-W01."""
        for wk in ["2025-W51", "2025-W52", "2026-W01"]:
            self._insert_weekly_agg(db, wk, 3)
        result = _compute_streak(db, "2026-W02", 3)
        assert result == 4


class TestLongRunDualCondition:
    """Test all 3 scenarios for long run detection."""

    def test_absolute_floor_12km(self):
        """>=12km is always long, regardless of weekly volume."""
        result = classify_run_type(
            {"type": "running", "name": "Sunday", "distance_km": 12, "hr_zone": "Z2"},
            weekly_km=100,
        )
        assert result == "long"

    def test_pct_of_weekly_volume(self):
        """10km with 25km weekly = 40% > 30%, and 10km >= 8km → long."""
        result = classify_run_type(
            {"type": "running", "name": "Sunday", "distance_km": 10, "hr_zone": "Z2"},
            weekly_km=25,
        )
        assert result == "long"

    def test_below_both_conditions(self):
        """7km with 50km weekly = 14% < 30%, and 7km < 8km → not long."""
        result = classify_run_type(
            {"type": "running", "name": "Sunday", "distance_km": 7, "hr_zone": "Z2"},
            weekly_km=50,
        )
        assert result == "easy"

    def test_high_pct_but_below_8km_floor(self):
        """6km with 15km weekly = 40% > 30%, but 6km < 8km → not long."""
        result = classify_run_type(
            {"type": "running", "name": "Morning", "distance_km": 6, "hr_zone": "Z2"},
            weekly_km=15,
        )
        assert result == "easy"

    def test_above_8km_but_low_pct(self):
        """9km with 80km weekly = 11% < 30% → not long."""
        result = classify_run_type(
            {"type": "running", "name": "Morning", "distance_km": 9, "hr_zone": "Z2"},
            weekly_km=80,
        )
        assert result == "easy"

    def test_no_weekly_km_provided(self):
        """Without weekly_km, only 12km absolute floor applies."""
        assert classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 11, "hr_zone": "Z2"},
        ) == "easy"
        assert classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 12, "hr_zone": "Z2"},
        ) == "long"


class TestAlertSQL:
    """Test that alert queries return correct data."""

    def _insert_weekly_agg(self, conn, week, z12_pct):
        conn.execute(
            "INSERT INTO weekly_agg (week, z12_pct) VALUES (?, ?)",
            (week, z12_pct),
        )
        conn.commit()

    def test_all_runs_too_hard_averages_2_weeks(self, db):
        """The all_runs_too_hard alert should average the last 2 weeks."""
        # Insert 3 weeks: W12=80%, W13=30%, W14=40%
        # Last 2 weeks avg = (30+40)/2 = 35% < 50 → should fire
        self._insert_weekly_agg(db, "2026-W12", 80)
        self._insert_weekly_agg(db, "2026-W13", 30)
        self._insert_weekly_agg(db, "2026-W14", 40)
        row = db.execute("""
            SELECT AVG(z12_pct) as avg_z12 FROM (
                SELECT z12_pct FROM weekly_agg ORDER BY week DESC LIMIT 2
            )
        """).fetchone()
        assert row["avg_z12"] == pytest.approx(35.0, abs=0.1)

    def test_all_runs_too_hard_not_just_max_week(self, db):
        """Old buggy query only looked at max week. Verify we get 2 rows."""
        self._insert_weekly_agg(db, "2026-W13", 45)
        self._insert_weekly_agg(db, "2026-W14", 55)
        rows = db.execute("""
            SELECT z12_pct FROM (
                SELECT z12_pct FROM weekly_agg ORDER BY week DESC LIMIT 2
            )
        """).fetchall()
        assert len(rows) == 2

    def test_single_week_still_works(self, db):
        """With only 1 week of data, query should still return a result."""
        self._insert_weekly_agg(db, "2026-W14", 40)
        row = db.execute("""
            SELECT AVG(z12_pct) as avg_z12 FROM (
                SELECT z12_pct FROM weekly_agg ORDER BY week DESC LIMIT 2
            )
        """).fetchone()
        assert row["avg_z12"] == pytest.approx(40.0, abs=0.1)


class TestSpO2Alert:
    """Test SpO2 consecutive day alert logic."""

    def _insert_health(self, conn, day, avg_spo2):
        conn.execute(
            "INSERT INTO daily_health (date, avg_spo2) VALUES (?, ?)",
            (day, avg_spo2),
        )
        conn.commit()

    def test_spo2_2_consecutive_low_days(self, db):
        """2 consecutive days below threshold should fire alert."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-05", 93.0)
        self._insert_health(db, "2026-04-06", 94.0)
        config = {}
        alerts = run_alerts(db, config)
        spo2_alerts = [a for a in alerts if a["type"] == "spo2_low"]
        assert len(spo2_alerts) == 1
        assert spo2_alerts[0]["data"]["consecutive_days"] == 2

    def test_spo2_no_alert_when_above_threshold(self, db):
        """Days above threshold should not fire."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-05", 97.0)
        self._insert_health(db, "2026-04-06", 96.0)
        config = {}
        alerts = run_alerts(db, config)
        spo2_alerts = [a for a in alerts if a["type"] == "spo2_low"]
        assert len(spo2_alerts) == 0

    def test_spo2_custom_threshold(self, db):
        """Custom threshold from config should be respected."""
        from fit.alerts import run_alerts
        # 94% and 94.5% are below custom threshold of 96%
        self._insert_health(db, "2026-04-05", 94.0)
        self._insert_health(db, "2026-04-06", 94.5)
        config = {"coaching": {"spo2_alert_threshold": 96}}
        alerts = run_alerts(db, config)
        spo2_alerts = [a for a in alerts if a["type"] == "spo2_low"]
        assert len(spo2_alerts) == 1

    def test_spo2_non_consecutive_no_alert(self, db):
        """Low days separated by a normal day should not fire."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-04", 93.0)
        self._insert_health(db, "2026-04-05", 97.0)  # breaks streak
        self._insert_health(db, "2026-04-06", 93.0)
        config = {}
        alerts = run_alerts(db, config)
        spo2_alerts = [a for a in alerts if a["type"] == "spo2_low"]
        # Only 1 consecutive low day (most recent), need 2+
        assert len(spo2_alerts) == 0

    def test_spo2_single_low_day_no_alert(self, db):
        """Only 1 low day should not fire (need 2+)."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-06", 93.0)
        config = {}
        alerts = run_alerts(db, config)
        spo2_alerts = [a for a in alerts if a["type"] == "spo2_low"]
        assert len(spo2_alerts) == 0
