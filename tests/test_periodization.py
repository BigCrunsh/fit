"""Tests for Run Story, periodization feedback, heat acclimatization, and pacing strategy."""

import sqlite3
from datetime import date, timedelta

import pytest

from fit.periodization import (
    evaluate_phase_readiness,
    generate_pacing_strategy,
    generate_run_story,
    compute_heat_acclimatization,
    _format_pace,
    _format_time,
    _count_consecutive_build_weeks,
)


@pytest.fixture
def db():
    """In-memory DB with full schema for periodization tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE activities (
            id TEXT PRIMARY KEY, date DATE, type TEXT, name TEXT,
            distance_km REAL, duration_min REAL, pace_sec_per_km REAL,
            avg_hr INTEGER, speed_per_bpm REAL, run_type TEXT,
            temp_at_start_c REAL, humidity_at_start_pct REAL,
            training_load REAL, hr_zone TEXT, splits_status TEXT,
            max_hr INTEGER, rpe INTEGER, srpe REAL,
            hr_zone_maxhr TEXT, hr_zone_lthr TEXT, effort_class TEXT,
            speed_per_bpm_z2 REAL, max_hr_used INTEGER, lthr_used INTEGER,
            subtype TEXT, avg_cadence REAL, elevation_gain_m REAL,
            calories INTEGER, vo2max REAL, aerobic_te REAL,
            avg_stride_m REAL, avg_speed REAL, start_lat REAL, start_lon REAL,
            fit_file_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE daily_health (
            date DATE PRIMARY KEY, training_readiness INTEGER,
            sleep_duration_hours REAL, resting_heart_rate INTEGER,
            hrv_last_night REAL, avg_spo2 REAL,
            total_steps INTEGER, total_distance_m REAL,
            total_calories INTEGER, active_calories INTEGER,
            max_heart_rate INTEGER, min_heart_rate INTEGER,
            avg_stress_level INTEGER, max_stress_level INTEGER,
            body_battery_high INTEGER, body_battery_low INTEGER,
            deep_sleep_hours REAL, light_sleep_hours REAL,
            rem_sleep_hours REAL, awake_hours REAL, deep_sleep_pct REAL,
            readiness_level TEXT, hrv_weekly_avg REAL, hrv_status TEXT,
            avg_respiration REAL
        );
        CREATE TABLE checkins (
            date DATE PRIMARY KEY, hydration TEXT, alcohol REAL DEFAULT 0,
            alcohol_detail TEXT, legs TEXT, eating TEXT,
            water_liters REAL, energy TEXT, rpe INTEGER,
            sleep_quality TEXT, notes TEXT
        );
        CREATE TABLE weather (
            date DATE PRIMARY KEY, temp_c REAL, humidity_pct REAL,
            temp_max_c REAL, temp_min_c REAL, wind_speed_kmh REAL,
            precipitation_mm REAL, conditions TEXT
        );
        CREATE TABLE weekly_agg (
            week TEXT PRIMARY KEY, run_count INTEGER, run_km REAL,
            run_avg_pace REAL, run_avg_hr REAL, longest_run_km REAL,
            run_avg_cadence REAL, easy_run_count INTEGER,
            quality_session_count INTEGER, cross_train_count INTEGER,
            cross_train_min REAL, total_load REAL, total_activities INTEGER,
            acwr REAL, avg_readiness REAL, avg_sleep REAL, avg_rhr REAL,
            avg_hrv REAL, weight_avg REAL,
            z1_min REAL, z2_min REAL, z3_min REAL, z4_min REAL, z5_min REAL,
            z12_pct REAL, z45_pct REAL, training_days INTEGER,
            consecutive_weeks_3plus INTEGER, monotony REAL, strain REAL,
            cycling_km REAL, cycling_min REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, type TEXT,
            target_time TEXT, target_pace REAL, target_value REAL,
            target_unit TEXT, target_date DATE, active BOOLEAN DEFAULT 1,
            race_id INTEGER
        );
        CREATE TABLE training_phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INTEGER,
            phase TEXT, name TEXT, start_date DATE, end_date DATE,
            z12_pct_target REAL, z45_pct_target REAL,
            weekly_km_min REAL, weekly_km_max REAL,
            targets TEXT, actuals TEXT, status TEXT DEFAULT 'planned',
            notes TEXT, created_at DATETIME, updated_at DATETIME
        );
        CREATE TABLE race_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, name TEXT,
            distance TEXT, distance_km REAL, status TEXT,
            target_time TEXT, result_time TEXT, garmin_time TEXT,
            result_pace REAL, activity_id TEXT, organizer TEXT
        );
        CREATE TABLE activity_splits (
            activity_id TEXT NOT NULL, split_num INTEGER NOT NULL,
            distance_km REAL, time_sec REAL, pace_sec_per_km REAL,
            avg_hr REAL, avg_cadence REAL, elevation_gain_m REAL,
            avg_speed_m_s REAL, time_above_z2_ceiling_sec REAL,
            start_distance_m REAL, end_distance_m REAL,
            PRIMARY KEY (activity_id, split_num)
        );
    """)
    return conn


# ── Run Story Tests ──


class TestRunStory:
    def test_no_long_run(self, db):
        result = generate_run_story(db, {})
        assert result is None

    def test_long_run_without_splits(self, db):
        today = date.today().isoformat()
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min,
                pace_sec_per_km, avg_hr, speed_per_bpm, run_type)
            VALUES ('r1', ?, 'running', 'Long Run', 18.0, 100.0, 333, 155, 0.038, 'long')
        """, (today,))
        db.commit()

        result = generate_run_story(db, {})
        assert result is not None
        assert result["distance_km"] == 18.0
        assert result["has_splits"] is False
        assert "18km" in result["narrative"]

    def test_long_run_with_checkin_context(self, db):
        today = date.today().isoformat()
        yesterday = (date.today() - timedelta(days=1)).isoformat()

        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min,
                pace_sec_per_km, avg_hr, speed_per_bpm, run_type)
            VALUES ('r1', ?, 'running', 'Long Run', 18.0, 100.0, 333, 155, 0.038, 'long')
        """, (today,))
        db.execute("""
            INSERT INTO checkins (date, alcohol, sleep_quality, legs, energy)
            VALUES (?, 2, 'Poor', 'Heavy', 'Low')
        """, (yesterday,))
        db.commit()

        result = generate_run_story(db, {})
        assert result is not None
        assert result["checkin"]["alcohol"] == 2
        assert result["checkin"]["sleep_quality"] == "Poor"
        assert "drink" in result["narrative"].lower() or "poor sleep" in result["narrative"].lower()

    def test_long_run_with_splits(self, db):
        today = date.today().isoformat()
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min,
                pace_sec_per_km, avg_hr, speed_per_bpm, run_type, splits_status)
            VALUES ('r1', ?, 'running', 'Long Run', 10.0, 55.0, 330, 150, 0.040, 'long', 'parsed')
        """, (today,))

        for i in range(1, 11):
            hr = 145 + (i * 2 if i > 5 else 0)
            db.execute("""
                INSERT INTO activity_splits (activity_id, split_num, distance_km, time_sec,
                    pace_sec_per_km, avg_hr)
                VALUES ('r1', ?, 1.0, 330, 330, ?)
            """, (i, hr))
        db.commit()

        result = generate_run_story(db, {})
        assert result is not None
        assert result["has_splits"] is True

    def test_long_run_with_weather(self, db):
        today = date.today().isoformat()
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min,
                pace_sec_per_km, avg_hr, speed_per_bpm, run_type)
            VALUES ('r1', ?, 'running', 'Long Run', 18.0, 100.0, 333, 155, 0.038, 'long')
        """, (today,))
        db.execute("""
            INSERT INTO weather (date, temp_c, humidity_pct, conditions)
            VALUES (?, 28.5, 65.0, 'Partly cloudy')
        """, (today,))
        db.commit()

        result = generate_run_story(db, {})
        assert "28°C" in result["narrative"] or "29°C" in result["narrative"]


# ── Periodization Tests ──


class TestPeriodization:
    def _insert_phase(self, db, status="active", z12_target=80, km_min=20, km_max=30):
        db.execute("""
            INSERT INTO training_phases (goal_id, phase, name, start_date, z12_pct_target,
                weekly_km_min, weekly_km_max, targets, status)
            VALUES (1, 'Phase 1', 'Base Building', '2026-01-01', ?, ?, ?,
                '{"run_frequency": [3,4]}', ?)
        """, (z12_target, km_min, km_max, status))
        db.commit()

    def _insert_weeks(self, db, weeks_data):
        for w in weeks_data:
            db.execute("""
                INSERT INTO weekly_agg (week, run_count, run_km, z12_pct, total_load,
                    z1_min, z2_min, z3_min, z4_min, z5_min, z45_pct,
                    training_days, consecutive_weeks_3plus)
                VALUES (?, 3, ?, ?, 300, 10, 30, 5, 2, 0, 5, 4, 4)
            """, (w["week"], w["km"], w.get("z12", 85)))
        db.commit()

    def test_no_active_phase(self, db):
        result = evaluate_phase_readiness(db)
        assert result is None

    def test_insufficient_data(self, db):
        self._insert_phase(db)
        self._insert_weeks(db, [{"week": "2026-W10", "km": 25}])
        result = evaluate_phase_readiness(db)
        assert result["action"] == "insufficient_data"

    def test_advance_recommendation(self, db):
        self._insert_phase(db)
        self._insert_weeks(db, [
            {"week": "2026-W12", "km": 25, "z12": 85},
            {"week": "2026-W11", "km": 24, "z12": 82},
            {"week": "2026-W10", "km": 22, "z12": 80},
        ])
        result = evaluate_phase_readiness(db)
        assert result["action"] == "advance"

    def test_struggling_recommendation(self, db):
        self._insert_phase(db, km_min=30)
        self._insert_weeks(db, [
            {"week": "2026-W12", "km": 18, "z12": 85},
            {"week": "2026-W11", "km": 17, "z12": 82},
            {"week": "2026-W10", "km": 16, "z12": 80},
        ])
        result = evaluate_phase_readiness(db)
        assert result["action"] == "extend"

    def test_deload_recommendation(self, db):
        self._insert_phase(db)
        # Z12 below target so advance doesn't trigger, but volume is rising = no deload
        self._insert_weeks(db, [
            {"week": "2026-W12", "km": 30, "z12": 60},
            {"week": "2026-W11", "km": 28, "z12": 58},
            {"week": "2026-W10", "km": 26, "z12": 55},
            {"week": "2026-W09", "km": 24, "z12": 52},
        ])
        result = evaluate_phase_readiness(db)
        assert result["action"] == "deload"

    def test_taper_recommendation(self, db):
        self._insert_phase(db)
        # Race in 14 days
        race_date = (date.today() + timedelta(days=14)).isoformat()
        db.execute("""
            INSERT INTO race_calendar (date, name, distance, status)
            VALUES (?, 'Berlin Marathon', 'Marathon', 'registered')
        """, (race_date,))
        self._insert_weeks(db, [
            {"week": "2026-W12", "km": 25, "z12": 50},  # not meeting z12 target
            {"week": "2026-W11", "km": 24, "z12": 55},
        ])
        result = evaluate_phase_readiness(db)
        assert result["action"] == "taper"
        assert "taper" in result["message"].lower()


# ── Heat Acclimatization Tests ──


class TestHeatAcclimatization:
    def test_insufficient_data(self, db):
        result = compute_heat_acclimatization(db)
        assert result is None

    def test_improving_trend(self, db):
        base_date = date.today() - timedelta(days=42)
        for i in range(6):
            d = (base_date + timedelta(days=i * 7)).isoformat()
            efficiency = 0.035 + (i * 0.001)  # improving
            db.execute("""
                INSERT INTO activities (id, date, type, distance_km, duration_min,
                    avg_hr, speed_per_bpm, temp_at_start_c, run_type)
                VALUES (?, ?, 'running', 10.0, 55.0, 150, ?, 28.0, 'easy')
            """, (f"r{i}", d, efficiency))
        db.commit()

        result = compute_heat_acclimatization(db)
        assert result is not None
        assert result["improving"] is True
        assert result["trend_pct"] > 0

    def test_stable_trend(self, db):
        base_date = date.today() - timedelta(days=42)
        for i in range(6):
            d = (base_date + timedelta(days=i * 7)).isoformat()
            db.execute("""
                INSERT INTO activities (id, date, type, distance_km, duration_min,
                    avg_hr, speed_per_bpm, temp_at_start_c, run_type)
                VALUES (?, ?, 'running', 10.0, 55.0, 150, 0.038, 28.0, 'easy')
            """, (f"r{i}", d))
        db.commit()

        result = compute_heat_acclimatization(db)
        assert result is not None
        assert result["improving"] is False


# ── Pacing Strategy Tests ──


class TestPacingStrategy:
    def test_sub4_pacing(self):
        # 3:52 marathon = 13920 seconds
        result = generate_pacing_strategy(13920, {"profile": {"max_hr": 192}})
        assert result is not None
        assert len(result["segments"]) == 9  # 8 x 5km + 1 x 2.195km
        assert result["target_pace_display"] in ("5:29", "5:30")  # ~330 sec/km
        assert result["hr_ceilings"]["0-15km"] < result["hr_ceilings"]["30-42km"]
        assert len(result["fueling"]) >= 4

    def test_sub5_pacing(self):
        # 4:45 marathon = 17100 seconds
        result = generate_pacing_strategy(17100, {"profile": {"max_hr": 180}})
        assert result is not None
        assert len(result["segments"]) == 9

    def test_negative_split_strategy(self):
        result = generate_pacing_strategy(14400, {"profile": {"max_hr": 192}})
        # First half should be slightly slower than second half
        first_segment = result["segments"][0]
        last_full_segment = result["segments"][-2]  # last 5km segment
        assert first_segment["pace_sec_km"] > last_full_segment["pace_sec_km"]


# ── Helper Tests ──


class TestHelpers:
    def test_format_pace(self):
        assert _format_pace(330) == "5:30"
        assert _format_pace(360) == "6:00"
        assert _format_pace(None) == "—"
        assert _format_pace(0) == "—"

    def test_format_time(self):
        assert _format_time(14400) == "4:00:00"
        assert _format_time(13920) == "3:52:00"
        assert _format_time(3723) == "1:02:03"

    def test_count_consecutive_build_weeks(self):
        # Simulate weeks as Row-like objects
        class FakeRow:
            def __init__(self, km):
                self._data = {"run_km": km}
            def __getitem__(self, key):
                return self._data[key]

        weeks = [FakeRow(30), FakeRow(28), FakeRow(26), FakeRow(24)]
        assert _count_consecutive_build_weeks(weeks) == 4

        # With deload — week order is DESC (newest first)
        # [30, 18, 26]: 30 vs 18 → 30 >= 18*0.7 (yes), 18 vs 26 → 18 < 26*0.7 (no) = 2 build weeks
        weeks_deload = [FakeRow(30), FakeRow(18), FakeRow(26)]
        assert _count_consecutive_build_weeks(weeks_deload) == 2

        # Clear deload: [15, 30, 28] → 15 < 30*0.7=21 → immediate deload = 1
        weeks_clear_deload = [FakeRow(15), FakeRow(30), FakeRow(28)]
        assert _count_consecutive_build_weeks(weeks_clear_deload) == 1
