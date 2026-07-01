"""Tests for narratives module: race countdown."""

import sqlite3
from datetime import date, timedelta

import pytest

from fit.narratives import generate_race_countdown


@pytest.fixture
def db():
    """In-memory DB with full schema for narrative tests."""
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
        CREATE TABLE body_comp (
            date DATE PRIMARY KEY, weight_kg REAL NOT NULL,
            body_fat_pct REAL, muscle_mass_kg REAL, visceral_fat REAL,
            bmi REAL, source TEXT DEFAULT 'apple_health'
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
        CREATE TABLE calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT, metric TEXT, value REAL,
            method TEXT, confidence TEXT, date DATE, source_activity_id TEXT,
            notes TEXT, active INTEGER DEFAULT 1
        );
    """)
    return conn


# ── Trend Badges ──


class TestRaceCountdown:
    def test_no_race_returns_none(self, db):
        """No upcoming race should return None."""
        result = generate_race_countdown(db)
        assert result is None

    def test_far_race_no_taper(self, db):
        """Race > 21 days away should not have taper rules."""
        race_date = (date.today() + timedelta(days=60)).isoformat()
        db.execute("""
            INSERT INTO race_calendar (date, name, distance, status)
            VALUES (?, 'Berlin Marathon', 'Marathon', 'registered')
        """, (race_date,))
        db.commit()

        result = generate_race_countdown(db)
        assert result is not None
        assert result["days_remaining"] == 60
        assert result["taper_rules"] is None

    def test_taper_period_returns_rules(self, db):
        """Race <= 21 days away should include taper rules."""
        race_date = (date.today() + timedelta(days=10)).isoformat()
        db.execute("""
            INSERT INTO race_calendar (date, name, distance, status)
            VALUES (?, 'Berlin Marathon', 'Marathon', 'registered')
        """, (race_date,))
        db.commit()

        result = generate_race_countdown(db)
        assert result is not None
        assert result["days_remaining"] == 10
        assert result["taper_rules"] is not None
        assert "50%" in result["taper_rules"]


# ── Walk-Break Detection ──


