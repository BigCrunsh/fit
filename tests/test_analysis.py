"""Tests for fit/analysis.py — zones, efficiency, run types, ACWR."""

from fit.analysis import (
    compute_hr_zones,
    compute_effort_class,
    compute_speed_per_bpm,
    compute_speed_per_bpm_z2,
    classify_run_type,
    predict_marathon_time,
)


class TestHRZones:
    def test_z2_ceiling_at_134(self, config):
        zones = compute_hr_zones(133, config)
        assert zones["hr_zone_maxhr"] == "Z2"
        zones = compute_hr_zones(135, config)
        assert zones["hr_zone_maxhr"] == "Z3"

    def test_parallel_zones_with_lthr(self, config):
        zones = compute_hr_zones(155, config, lthr=172)
        assert zones["hr_zone_maxhr"] is not None
        assert zones["hr_zone_lthr"] is not None

    def test_no_lthr_gives_null(self, config):
        zones = compute_hr_zones(155, config, lthr=None)
        assert zones["hr_zone_lthr"] is None
        assert zones["hr_zone_maxhr"] == "Z4"

    def test_null_hr(self, config):
        zones = compute_hr_zones(None, config)
        assert zones["hr_zone"] is None


class TestEffortClass:
    def test_five_levels(self):
        assert compute_effort_class("Z1") == "Recovery"
        assert compute_effort_class("Z2") == "Easy"
        assert compute_effort_class("Z3") == "Moderate"
        assert compute_effort_class("Z4") == "Hard"
        assert compute_effort_class("Z5") == "Very Hard"

    def test_null(self):
        assert compute_effort_class(None) is None


class TestSpeedPerBPM:
    def test_higher_is_better(self):
        slow = compute_speed_per_bpm(10.0, 60, 150)
        fast = compute_speed_per_bpm(10.0, 50, 150)
        assert fast > slow

    def test_null_inputs(self):
        assert compute_speed_per_bpm(None, 50, 150) is None
        assert compute_speed_per_bpm(10, 0, 150) is None
        assert compute_speed_per_bpm(10, 50, None) is None

    def test_z2_filter(self):
        assert compute_speed_per_bpm_z2(7, 45, 128, [115, 134]) is not None
        assert compute_speed_per_bpm_z2(7, 45, 165, [115, 134]) is None


class TestRunType:
    def test_race_detection(self):
        assert classify_run_type({"type": "running", "name": "Half Marathon", "distance_km": 21}) == "race"
        assert classify_run_type({"type": "running", "name": "parkrun", "distance_km": 5}) == "race"

    def test_easy_default(self):
        assert classify_run_type({"type": "running", "name": "Easy Run", "distance_km": 7, "hr_zone": "Z2"}) == "easy"

    def test_tempo(self):
        assert classify_run_type({"type": "running", "name": "Tempo", "distance_km": 10, "hr_zone": "Z4"}) == "tempo"

    def test_long_run(self):
        assert classify_run_type({"type": "running", "name": "Sunday", "distance_km": 18, "hr_zone": "Z2"}) == "long"

    def test_recovery(self):
        assert classify_run_type({"type": "running", "name": "Jog", "distance_km": 4, "hr_zone": "Z1"}) == "recovery"

    def test_non_running(self):
        assert classify_run_type({"type": "cycling"}) is None


class TestRacePrediction:
    def test_riegel_from_hm(self):
        preds = predict_marathon_time([
            {"distance_km": 21.1, "time_seconds": 6572, "name": "Oct HM"},
        ], vo2max=49)
        assert len(preds["riegel"]) == 1
        assert preds["riegel"][0]["predicted_seconds"] > 0

    def test_vdot(self):
        preds = predict_marathon_time([], vo2max=49)
        assert preds["vdot"] is not None
        assert preds["vdot"]["predicted_seconds"] > 0

    def test_no_data(self):
        preds = predict_marathon_time([], vo2max=None)
        assert preds["riegel"] == []
        assert preds["vdot"] is None
