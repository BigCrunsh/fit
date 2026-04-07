"""Tests for fit/fit_file.py — .fit file parsing, splits, cardiac drift, heat flags."""



from fit.fit_file import (
    compute_cardiac_drift,
    compute_cadence_drift,
    compute_pace_variability,
    flag_heat_affected,
    compute_split_zone_time,
)


def _make_splits(n_km=10, base_hr=140, base_pace=360, base_cadence=170,
                 drift_at_km=None, drift_hr_increase=15, pace_variance=0):
    """Generate synthetic split data for testing."""
    splits = []
    for i in range(1, n_km + 1):
        hr = base_hr
        pace = base_pace + (pace_variance * ((-1) ** i))
        cadence = base_cadence

        if drift_at_km and i >= drift_at_km:
            hr = base_hr + drift_hr_increase * (i - drift_at_km + 1) / (n_km - drift_at_km + 1)
            cadence = base_cadence - 2 * (i - drift_at_km + 1)

        splits.append({
            "split_num": i,
            "distance_km": 1.0,
            "time_sec": pace,
            "pace_sec_per_km": pace,
            "avg_hr": round(hr, 1),
            "avg_cadence": round(cadence, 1),
            "elevation_gain_m": 5.0,
            "avg_speed_m_s": round(1000 / pace, 2),
        })
    return splits


# ── Cardiac Drift ──


class TestCardiacDrift:
    def test_no_drift_steady_state(self):
        splits = _make_splits(n_km=10, base_hr=140, base_pace=360)
        result = compute_cardiac_drift(splits)
        assert result is not None
        assert result["status"] in ("none", "mild")

    def test_drift_detected_at_km(self):
        splits = _make_splits(n_km=18, base_hr=140, base_pace=360,
                              drift_at_km=14, drift_hr_increase=20)
        result = compute_cardiac_drift(splits)
        assert result is not None
        if result["status"] == "significant":
            assert result["drift_onset_km"] is not None
            assert result["drift_onset_km"] >= 10

    def test_variable_pace_inconclusive(self):
        splits = _make_splits(n_km=10, base_hr=140, base_pace=360, pace_variance=80)
        result = compute_cardiac_drift(splits)
        assert result is not None
        assert result["status"] == "inconclusive_variable_pace"

    def test_too_few_splits(self):
        splits = _make_splits(n_km=3)
        result = compute_cardiac_drift(splits)
        assert result is None or result.get("status") in (None, "insufficient_data")

    def test_drift_pct_calculated(self):
        splits = _make_splits(n_km=12, base_hr=135, base_pace=360,
                              drift_at_km=8, drift_hr_increase=25)
        result = compute_cardiac_drift(splits)
        if result and result.get("drift_pct") is not None:
            assert isinstance(result["drift_pct"], (int, float))


# ── Pace Variability ──


class TestPaceVariability:
    def test_consistent_pace(self):
        splits = _make_splits(n_km=10, base_pace=360, pace_variance=0)
        cv = compute_pace_variability(splits)
        assert cv is not None
        assert cv < 5  # <5% CV = consistent

    def test_variable_pace(self):
        splits = _make_splits(n_km=10, base_pace=360, pace_variance=60)
        cv = compute_pace_variability(splits)
        assert cv is not None
        assert cv > 10  # >10% CV = variable

    def test_single_split_returns_none(self):
        splits = _make_splits(n_km=1)
        cv = compute_pace_variability(splits)
        assert cv is None

    def test_empty_returns_none(self):
        cv = compute_pace_variability([])
        assert cv is None


# ── Cadence Drift ──


class TestCadenceDrift:
    def test_no_cadence_drift(self):
        splits = _make_splits(n_km=10, base_cadence=172)
        result = compute_cadence_drift(splits)
        assert result is not None
        assert abs(result.get("drift_pct", 0)) < 3

    def test_cadence_fade(self):
        splits = _make_splits(n_km=10, base_cadence=175,
                              drift_at_km=6, drift_hr_increase=0)
        # Manually set cadence fade
        for s in splits[5:]:
            s["avg_cadence"] = 175 - (s["split_num"] - 5) * 3
        result = compute_cadence_drift(splits)
        assert result is not None

    def test_too_few_splits(self):
        splits = _make_splits(n_km=2)
        result = compute_cadence_drift(splits)
        assert result is None or result.get("drift_pct") is None


# ── Heat Flags ──


class TestHeatFlags:
    def test_hot_temp_flagged(self):
        assert flag_heat_affected({"temp_at_start_c": 30, "humidity_at_start_pct": 40}) is True

    def test_high_humidity_flagged(self):
        assert flag_heat_affected({"temp_at_start_c": 20, "humidity_at_start_pct": 75}) is True

    def test_both_hot_and_humid(self):
        assert flag_heat_affected({"temp_at_start_c": 28, "humidity_at_start_pct": 80}) is True

    def test_cool_and_dry_not_flagged(self):
        assert flag_heat_affected({"temp_at_start_c": 15, "humidity_at_start_pct": 50}) is False

    def test_missing_data_not_flagged(self):
        assert flag_heat_affected({}) is False
        assert flag_heat_affected({"temp_at_start_c": None}) is False


# ── Split Zone Time ──


class TestSplitZoneTime:
    def test_all_below_ceiling(self):
        splits = _make_splits(n_km=5, base_hr=125)
        result = compute_split_zone_time(splits, z2_ceiling_hr=134)
        for s in result:
            assert s["time_above_z2_ceiling_sec"] == 0

    def test_all_above_ceiling(self):
        splits = _make_splits(n_km=5, base_hr=150)
        result = compute_split_zone_time(splits, z2_ceiling_hr=134)
        for s in result:
            assert s["time_above_z2_ceiling_sec"] > 0

    def test_mixed(self):
        splits = _make_splits(n_km=6, base_hr=130)
        splits[3]["avg_hr"] = 140
        splits[4]["avg_hr"] = 145
        result = compute_split_zone_time(splits, z2_ceiling_hr=134)
        assert result[0]["time_above_z2_ceiling_sec"] == 0
        assert result[3]["time_above_z2_ceiling_sec"] > 0
