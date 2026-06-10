"""Tests for Phase 2 coaching metrics (tasks 4.1-4.14)."""


import pytest

from fit.analysis import (
    classify_run_type,
    compute_srpe,
    compute_weekly_agg,
    detect_training_gap,
    predict_race_time,
)


# ════════════════════════════════════════════════════════════════
# 4.1 Race prediction — VDOT leg is anchored, not table-fed
# ════════════════════════════════════════════════════════════════


class TestRacePredictionVdotLeg:
    """The Daniels VDOT→time table is retired (D1 Phase 2). predict_race_time's vdot
    leg is sourced from the calibrated VDOT anchor (conn-based), never Garmin VO2max via
    the table; without a conn the param is ignored. Anchor coverage: test_forecast_anchor."""

    def test_vdot_leg_none_without_conn(self):
        assert predict_race_time(races=[], vo2max=42)["vdot"] is None
        assert predict_race_time(races=[], vo2max=55)["vdot"] is None


# ════════════════════════════════════════════════════════════════
# 4.2 Long Run Dual Condition
# ════════════════════════════════════════════════════════════════


class TestLongRunDualCondition:
    """Verify long run uses dual condition: >=12km absolute OR (>30% weekly AND >=8km)."""

    def test_absolute_floor_12km(self):
        """>=12km always counts as long regardless of weekly volume."""
        result = classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 13, "hr_zone": "Z2"},
            weekly_km=100,  # 13% of 100 < 30%, but >=12km
        )
        assert result == "long"

    def test_percentage_condition_met(self):
        """8km+ and >30% of weekly volume counts as long."""
        result = classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 9, "hr_zone": "Z2"},
            weekly_km=25,  # 9/25 = 36% > 30%
        )
        assert result == "long"

    def test_neither_condition_met(self):
        """8km but <=30% of weekly volume and <12km should NOT be long."""
        result = classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 9, "hr_zone": "Z2"},
            weekly_km=50,  # 9/50 = 18% < 30%
        )
        assert result == "easy"

    def test_below_8km_not_long(self):
        """7km cannot be long even with 100% of weekly volume."""
        result = classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 7, "hr_zone": "Z2"},
            weekly_km=7,  # 100% of volume but <8km
        )
        assert result == "easy"

    def test_no_weekly_km_uses_absolute(self):
        """Without weekly_km data, only absolute floor applies."""
        result = classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 11, "hr_zone": "Z2"},
            weekly_km=None,
        )
        assert result == "easy"  # <12km, no weekly data
        result2 = classify_run_type(
            {"type": "running", "name": "Run", "distance_km": 13, "hr_zone": "Z2"},
            weekly_km=None,
        )
        assert result2 == "long"  # >=12km absolute


# ════════════════════════════════════════════════════════════════
# 4.3 sRPE Computation
# ════════════════════════════════════════════════════════════════


class TestSRPE:
    """Test sRPE join: checkin RPE * activity duration."""

    def _insert_activity(self, conn, id, date, duration_min=45, training_load=100, rpe=None):
        conn.execute("""
            INSERT INTO activities (id, date, type, name, duration_min, training_load, rpe)
            VALUES (?, ?, 'running', 'Run', ?, ?, ?)
        """, (id, date, duration_min, training_load, rpe))
        conn.commit()

    def test_single_run(self, db):
        """Single run with activity RPE should get sRPE = RPE * duration."""
        self._insert_activity(db, "run1", "2026-04-01", duration_min=45, rpe=7)
        count = compute_srpe(db)
        assert count == 1
        row = db.execute("SELECT srpe FROM activities WHERE id = 'run1'").fetchone()
        assert row["srpe"] == pytest.approx(7 * 45, abs=0.1)

    def test_two_runs_same_day(self, db):
        """Two runs same day: each gets its own sRPE from its own RPE."""
        self._insert_activity(db, "run1", "2026-04-01", duration_min=30, training_load=80, rpe=4)
        self._insert_activity(db, "run2", "2026-04-01", duration_min=60, training_load=200, rpe=8)
        count = compute_srpe(db)
        assert count == 2
        row1 = db.execute("SELECT srpe FROM activities WHERE id = 'run1'").fetchone()
        assert row1["srpe"] == pytest.approx(4 * 30, abs=0.1)
        row2 = db.execute("SELECT srpe FROM activities WHERE id = 'run2'").fetchone()
        assert row2["srpe"] == pytest.approx(8 * 60, abs=0.1)

    def test_no_activity_rpe(self, db):
        """Activity without RPE: no sRPE computed."""
        self._insert_activity(db, "run1", "2026-04-01")
        count = compute_srpe(db)
        assert count == 0
        row = db.execute("SELECT srpe FROM activities WHERE id = 'run1'").fetchone()
        assert row["srpe"] is None

    def test_already_computed(self, db):
        """Already has sRPE: should not recompute."""
        self._insert_activity(db, "run1", "2026-04-01", duration_min=45, rpe=7)
        compute_srpe(db)
        # Run again - should not update
        count = compute_srpe(db)
        assert count == 0


# ════════════════════════════════════════════════════════════════
# 4.4 Training Monotony and Strain
# ════════════════════════════════════════════════════════════════


class TestMonotonyStrain:
    """Test monotony = mean/stdev and strain = load * monotony."""

    def _insert_run(self, conn, day, training_load=100, **kwargs):
        defaults = {
            "id": f"run-{day}", "date": day, "type": "running", "name": "Run",
            "distance_km": 7, "duration_min": 45, "training_load": training_load,
            "hr_zone": "Z2", "run_type": "easy",
        }
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        conn.execute(
            f"INSERT INTO activities ({cols}) VALUES ({placeholders})",
            list(defaults.values()),
        )
        conn.commit()

    def test_high_monotony(self, db):
        """Same load every day = high monotony."""
        # 2026-W14: Mon=2026-03-30 to Sun=2026-04-05
        for i, day in enumerate(["2026-03-30", "2026-03-31", "2026-04-01",
                                 "2026-04-02", "2026-04-03", "2026-04-04", "2026-04-05"]):
            self._insert_run(db, day, training_load=100, id=f"run-{i}")
        result = compute_weekly_agg(db, "2026-W14")
        # All 7 days have exactly 100 load => monotony undefined because variance
        # won't be exactly 0 - but since rest days are included,
        # days with 0 load balance it out
        # Actually all 7 days have runs, so daily_loads = [100,100,...,100]
        # stdev should be 0 => monotony = None
        assert result["monotony"] is None
        assert result["strain"] is None

    def test_normal_variation(self, db):
        """Mix of run days and rest days = measurable monotony."""
        # 3 runs in the week
        self._insert_run(db, "2026-03-30", training_load=150, id="r1")
        self._insert_run(db, "2026-04-01", training_load=100, id="r2")
        self._insert_run(db, "2026-04-03", training_load=200, id="r3")
        result = compute_weekly_agg(db, "2026-W14")
        assert result["monotony"] is not None
        assert result["monotony"] > 0
        assert result["strain"] is not None
        assert result["strain"] > 0

    def test_single_day_not_null(self, db):
        """Single training day: stdev > 0 because of rest days."""
        self._insert_run(db, "2026-03-30", training_load=100, id="r1")
        result = compute_weekly_agg(db, "2026-W14")
        # daily_loads = [100, 0, 0, 0, 0, 0, 0] => stdev > 0 => monotony defined
        assert result["monotony"] is not None
        assert result["strain"] is not None

    def test_empty_week_no_monotony(self, db):
        """No activities: all daily loads = 0, stdev = 0 => monotony None."""
        result = compute_weekly_agg(db, "2026-W14")
        assert result["monotony"] is None
        assert result["strain"] is None

    def test_cross_training_excluded(self, db):
        """Monotony/strain count RUNNING only — a big cycling block must not move
        them (consistent with the running-only ACWR)."""
        # 7 running days, one heavier → defined (non-None) monotony/strain.
        days = ["2026-03-30", "2026-03-31", "2026-04-01", "2026-04-02",
                "2026-04-03", "2026-04-04", "2026-04-05"]
        for i, day in enumerate(days):
            self._insert_run(db, day, training_load=120 if i == 0 else 100, id=f"run-{i}")
        base = compute_weekly_agg(db, "2026-W14")
        assert base["monotony"] is not None and base["strain"] is not None
        # Add large cycling loads inside the week — excluded from monotony/strain.
        self._insert_run(db, "2026-04-02", id="bike1", type="cycling", training_load=900)
        self._insert_run(db, "2026-04-04", id="bike2", type="cycling", training_load=900)
        after = compute_weekly_agg(db, "2026-W14")
        assert after["monotony"] == base["monotony"]
        assert after["strain"] == base["strain"]


# ════════════════════════════════════════════════════════════════
# 4.5 Cycling Volume Aggregation
# ════════════════════════════════════════════════════════════════


class TestCyclingVolume:
    """Test cycling_km and cycling_min in weekly_agg."""

    def test_cycling_volume(self, db):
        """Cycling activities should populate cycling_km and cycling_min."""
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min, training_load)
            VALUES ('bike1', '2026-03-30', 'cycling', 'Bike', 30.5, 90, 120)
        """)
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min, training_load)
            VALUES ('bike2', '2026-04-02', 'cycling', 'Bike', 20.0, 60, 80)
        """)
        db.commit()
        result = compute_weekly_agg(db, "2026-W14")
        assert result["cycling_km"] == pytest.approx(50.5, abs=0.1)
        assert result["cycling_min"] == pytest.approx(150.0, abs=0.1)

    def test_no_cycling(self, db):
        """No cycling activities: cycling_km and cycling_min should be 0."""
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min, training_load)
            VALUES ('run1', '2026-03-30', 'running', 'Run', 7, 45, 100)
        """)
        db.commit()
        result = compute_weekly_agg(db, "2026-W14")
        assert result["cycling_km"] == 0.0
        assert result["cycling_min"] == 0.0


# ════════════════════════════════════════════════════════════════
# 4.6 SpO2 Consecutive Day Alert
# ════════════════════════════════════════════════════════════════


class TestSpO2Alert:
    """Test SpO2 illness alert fires on 2+ consecutive days below threshold."""

    def _insert_health(self, conn, date, avg_spo2):
        conn.execute("""
            INSERT INTO daily_health (date, avg_spo2) VALUES (?, ?)
        """, (date, avg_spo2))
        conn.commit()

    def test_two_consecutive_low_spo2(self, db, config):
        """2 consecutive days below threshold should fire alert."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-05", 93.0)
        self._insert_health(db, "2026-04-06", 92.5)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "spo2_low" in types

    def test_one_day_low_no_alert(self, db, config):
        """Single day below threshold should NOT fire alert."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-05", 97.0)
        self._insert_health(db, "2026-04-06", 93.0)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "spo2_low" not in types

    def test_all_normal_no_alert(self, db, config):
        """All normal SpO2 values should NOT fire alert."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-05", 97.0)
        self._insert_health(db, "2026-04-06", 98.0)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "spo2_low" not in types


# ════════════════════════════════════════════════════════════════
# 4.9 Deload Detection
# ════════════════════════════════════════════════════════════════


class TestDeloadDetection:
    """Test deload overdue alert."""

    def _insert_weekly(self, conn, week, run_km):
        conn.execute("""
            INSERT INTO weekly_agg (week, run_km, run_count) VALUES (?, ?, 3)
        """, (week, run_km))
        conn.commit()

    def test_four_build_weeks_fires(self, db, config):
        """4+ consecutive build weeks should fire deload alert."""
        from fit.alerts import _check_deload_overdue
        # 6 weeks of increasing volume (no deload)
        for i, wk in enumerate(["2026-W09", "2026-W10", "2026-W11",
                                 "2026-W12", "2026-W13", "2026-W14"]):
            self._insert_weekly(db, wk, 20 + i * 3)
        result = _check_deload_overdue(db, "2026-04-06")
        assert result is not None
        assert result["type"] == "deload_overdue"

    def test_recent_deload_no_alert(self, db, config):
        """Recent deload week should NOT fire alert."""
        from fit.alerts import _check_deload_overdue
        self._insert_weekly(db, "2026-W10", 30)
        self._insert_weekly(db, "2026-W11", 33)
        self._insert_weekly(db, "2026-W12", 36)
        self._insert_weekly(db, "2026-W13", 20)  # deload: dropped >30%
        self._insert_weekly(db, "2026-W14", 30)
        result = _check_deload_overdue(db, "2026-04-06")
        # Only 1 build week since last deload
        assert result is None

    def test_insufficient_data(self, db, config):
        """Fewer than 3 weeks should not fire."""
        from fit.alerts import _check_deload_overdue
        self._insert_weekly(db, "2026-W13", 30)
        self._insert_weekly(db, "2026-W14", 33)
        result = _check_deload_overdue(db, "2026-04-06")
        assert result is None


# ════════════════════════════════════════════════════════════════
# 4.10 Return-to-Run Gap Detection
# ════════════════════════════════════════════════════════════════


class TestReturnToRun:
    """Test training gap detection for return-to-run protocol."""

    def test_no_gap(self, db):
        """Recent run (today) should not detect gap."""
        from datetime import date as dt_date
        today = dt_date.today().isoformat()
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min)
            VALUES ('run1', ?, 'running', 'Run', 7, 45)
        """, (today,))
        db.commit()
        result = detect_training_gap(db)
        assert result is None

    def test_14_day_gap(self, db):
        """14-day gap should trigger return-to-run."""
        from datetime import date as dt_date, timedelta
        old_date = (dt_date.today() - timedelta(days=15)).isoformat()
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min)
            VALUES ('run1', ?, 'running', 'Run', 7, 45)
        """, (old_date,))
        db.commit()
        result = detect_training_gap(db)
        assert result is not None
        assert result["gap_days"] >= 14
        assert result["suppress_acwr_alerts"] is True
        assert len(result["ramp_plan"]) == 4

    def test_no_activities(self, db):
        """No activities at all should return None."""
        result = detect_training_gap(db)
        assert result is None


# ════════════════════════════════════════════════════════════════
# 4.12 Prediction Confidence Band
# ════════════════════════════════════════════════════════════════


class TestPredictionConfidence:
    """Test confidence band based on data quantity."""

    def _insert_weekly(self, conn, week):
        conn.execute("INSERT INTO weekly_agg (week, run_count) VALUES (?, 3)", (week,))
        conn.commit()

    def test_low_confidence_few_weeks(self, db):
        """<8 weeks of data should give low confidence."""
        for i in range(5):
            self._insert_weekly(db, f"2026-W{10 + i:02d}")
        preds = predict_race_time(conn=db, races=[], vo2max=50)
        assert preds["confidence"]["level"] == "low"
        assert preds["confidence"]["margin_seconds"] == 900

    def test_moderate_confidence(self, db):
        """8-15 weeks of data should give moderate confidence."""
        for i in range(12):
            self._insert_weekly(db, f"2026-W{i + 1:02d}")
        preds = predict_race_time(conn=db, races=[], vo2max=50)
        assert preds["confidence"]["level"] == "moderate"
        assert preds["confidence"]["margin_seconds"] == 480

    def test_high_confidence_many_weeks(self, db):
        """16+ weeks should give high confidence."""
        for i in range(20):
            self._insert_weekly(db, f"2026-W{i + 1:02d}")
        preds = predict_race_time(conn=db, races=[], vo2max=50)
        assert preds["confidence"]["level"] == "high"

    def test_high_confidence_with_race(self, db):
        """Having a recent race should give high confidence."""
        races = [{"distance_km": 21.1, "time_seconds": 6000, "name": "HM"}]
        preds = predict_race_time(conn=db, races=races, vo2max=50)
        assert preds["confidence"]["level"] == "high"
        assert preds["confidence"]["margin_seconds"] == 240

    def test_no_conn_low_confidence(self):
        """No DB connection should default to low confidence."""
        preds = predict_race_time(conn=None, races=[], vo2max=50)
        assert preds["confidence"]["level"] == "low"


# ════════════════════════════════════════════════════════════════
# 4.13 Adaptive Readiness Gate
# ════════════════════════════════════════════════════════════════


class TestAdaptiveReadinessGate:
    """Test readiness gate with adaptive threshold."""

    def _insert_health(self, conn, date, readiness):
        conn.execute("""
            INSERT INTO daily_health (date, training_readiness)
            VALUES (?, ?)
        """, (date, readiness))
        conn.commit()

    def test_default_threshold_40(self, db, config):
        """Readiness at 35 (< 40 default threshold) should fire alert."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-06", 35)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "readiness_gate" in types

    def test_above_default_threshold(self, db, config):
        """Readiness at 45 (> 40 default threshold) should NOT fire."""
        from fit.alerts import run_alerts
        self._insert_health(db, "2026-04-06", 45)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "readiness_gate" not in types

    def test_config_override(self, db, config):
        """Config override of readiness threshold."""
        from fit.alerts import run_alerts
        config["coaching"] = {"readiness_gate_threshold": 50}
        self._insert_health(db, "2026-04-06", 45)
        alerts = run_alerts(db, config)
        types = [a["type"] for a in alerts]
        assert "readiness_gate" in types


# ════════════════════════════════════════════════════════════════
# 4.14 Effect Size Filter
# ════════════════════════════════════════════════════════════════


class TestEffectSizeFilter:
    """Test correlation actionability filter: n>=15 AND |r|>=0.2."""

    def test_actionable(self, db):
        """n>=15 and |r|>=0.3 should be actionable."""
        db.execute("""
            INSERT INTO correlations (metric_pair, spearman_r, sample_size, status, confidence)
            VALUES ('test_pair', -0.35, 25, 'computed', 'high')
        """)
        db.commit()
        from fit.correlations import get_actionable_correlations
        results = get_actionable_correlations(db)
        assert len(results) == 1
        assert results[0]["is_actionable"] is True

    def test_not_actionable_small_n(self, db):
        """n<15 should not be actionable even with large |r|."""
        db.execute("""
            INSERT INTO correlations (metric_pair, spearman_r, sample_size, status, confidence)
            VALUES ('test_pair2', -0.5, 10, 'computed', 'moderate')
        """)
        db.commit()
        from fit.correlations import get_actionable_correlations
        results = get_actionable_correlations(db)
        assert len(results) == 0

    def test_not_actionable_small_effect(self, db):
        """n>=15 but |r|<0.2 should not be actionable."""
        db.execute("""
            INSERT INTO correlations (metric_pair, spearman_r, sample_size, status, confidence)
            VALUES ('test_pair3', 0.1, 30, 'computed', 'high')
        """)
        db.commit()
        from fit.correlations import get_actionable_correlations
        results = get_actionable_correlations(db)
        assert len(results) == 0

    def test_boundary_exactly_15_and_0_2(self, db):
        """Exactly n=15 and |r|=0.2 should be actionable."""
        db.execute("""
            INSERT INTO correlations (metric_pair, spearman_r, sample_size, status, confidence)
            VALUES ('test_pair4', 0.2, 15, 'computed', 'moderate')
        """)
        db.commit()
        from fit.correlations import get_actionable_correlations
        results = get_actionable_correlations(db)
        assert len(results) == 1

    def test_null_spearman_r(self, db):
        """NULL spearman_r should not be actionable."""
        db.execute("""
            INSERT INTO correlations (metric_pair, spearman_r, sample_size, status, confidence)
            VALUES ('test_pair5', NULL, 20, 'computed', 'low')
        """)
        db.commit()
        from fit.correlations import get_actionable_correlations
        results = get_actionable_correlations(db)
        assert len(results) == 0
