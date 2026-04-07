"""End-to-end integration tests: full pipeline from data to narratives."""

import sqlite3
from datetime import date, timedelta

import pytest


@pytest.fixture
def db():
    """In-memory DB with full schema + realistic test data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE activities (
            id TEXT PRIMARY KEY, date DATE, type TEXT, subtype TEXT, name TEXT,
            distance_km REAL, duration_min REAL, pace_sec_per_km REAL,
            avg_hr INTEGER, max_hr INTEGER, avg_cadence REAL, elevation_gain_m REAL,
            calories INTEGER, vo2max REAL, aerobic_te REAL, training_load REAL,
            avg_stride_m REAL, avg_speed REAL, start_lat REAL, start_lon REAL,
            temp_at_start_c REAL, humidity_at_start_pct REAL,
            rpe INTEGER, run_type TEXT,
            max_hr_used INTEGER, lthr_used INTEGER,
            hr_zone_maxhr TEXT, hr_zone_lthr TEXT, hr_zone TEXT,
            speed_per_bpm REAL, speed_per_bpm_z2 REAL,
            effort_class TEXT, srpe REAL, fit_file_path TEXT, splits_status TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE daily_health (
            date DATE PRIMARY KEY, total_steps INTEGER, total_distance_m REAL,
            total_calories INTEGER, active_calories INTEGER,
            resting_heart_rate INTEGER, max_heart_rate INTEGER, min_heart_rate INTEGER,
            avg_stress_level INTEGER, max_stress_level INTEGER,
            body_battery_high INTEGER, body_battery_low INTEGER,
            sleep_duration_hours REAL, deep_sleep_hours REAL, light_sleep_hours REAL,
            rem_sleep_hours REAL, awake_hours REAL, deep_sleep_pct REAL,
            training_readiness INTEGER, readiness_level TEXT,
            hrv_weekly_avg REAL, hrv_last_night REAL, hrv_status TEXT,
            avg_respiration REAL, avg_spo2 REAL
        );
        CREATE TABLE checkins (
            date DATE PRIMARY KEY, hydration TEXT, alcohol REAL DEFAULT 0,
            alcohol_detail TEXT, legs TEXT, eating TEXT,
            water_liters REAL, energy TEXT, rpe INTEGER,
            sleep_quality TEXT, notes TEXT
        );
        CREATE TABLE body_comp (
            date DATE PRIMARY KEY, weight_kg REAL, body_fat_pct REAL,
            muscle_mass_kg REAL, visceral_fat REAL, bmi REAL, source TEXT
        );
        CREATE TABLE weather (
            date DATE PRIMARY KEY, temp_c REAL, temp_max_c REAL, temp_min_c REAL,
            humidity_pct REAL, wind_speed_kmh REAL, precipitation_mm REAL, conditions TEXT
        );
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            type TEXT NOT NULL, target_time TEXT, target_pace REAL,
            target_value REAL, target_unit TEXT, target_date DATE,
            active BOOLEAN DEFAULT 1, race_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE training_phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INTEGER,
            phase TEXT, name TEXT, start_date DATE, end_date DATE,
            z12_pct_target REAL, z45_pct_target REAL,
            weekly_km_min REAL, weekly_km_max REAL,
            targets TEXT, actuals TEXT, status TEXT DEFAULT 'planned',
            notes TEXT, created_at DATETIME, updated_at DATETIME
        );
        CREATE TABLE goal_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, goal_id INTEGER,
            phase_id INTEGER, type TEXT, description TEXT,
            previous_value TEXT, new_value TEXT, created_at DATETIME
        );
        CREATE TABLE calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT, metric TEXT, value REAL,
            method TEXT, source_activity_id TEXT, confidence TEXT,
            date DATE, notes TEXT, active BOOLEAN DEFAULT 1
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
            consecutive_weeks_3plus INTEGER,
            monotony REAL, strain REAL, cycling_km REAL, cycling_min REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE schema_version (
            version INTEGER PRIMARY KEY, name TEXT, applied_at DATETIME
        );
        CREATE TABLE correlations (
            metric_pair TEXT PRIMARY KEY, lag_days INTEGER,
            spearman_r REAL, pearson_r REAL, p_value REAL,
            sample_size INTEGER, confidence TEXT, status TEXT,
            last_computed DATETIME, data_count_at_compute INTEGER
        );
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, type TEXT,
            message TEXT, data_context TEXT, acknowledged BOOLEAN DEFAULT 0
        );
        CREATE TABLE import_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT,
            file_hash TEXT UNIQUE, row_count INTEGER, rows_imported INTEGER,
            source_type TEXT, imported_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE race_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE NOT NULL,
            name TEXT NOT NULL, organizer TEXT, distance TEXT NOT NULL,
            distance_km REAL, status TEXT DEFAULT 'planned',
            target_time TEXT, result_time TEXT, result_pace REAL,
            activity_id TEXT, garmin_time TEXT, notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE activity_splits (
            activity_id TEXT NOT NULL, split_num INTEGER NOT NULL,
            distance_km REAL, time_sec REAL, pace_sec_per_km REAL,
            avg_hr REAL, avg_cadence REAL, elevation_gain_m REAL,
            avg_speed_m_s REAL, time_above_z2_ceiling_sec REAL,
            start_distance_m REAL, end_distance_m REAL,
            PRIMARY KEY (activity_id, split_num)
        );
        CREATE TABLE planned_workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE NOT NULL,
            workout_name TEXT, workout_type TEXT, target_distance_km REAL,
            target_zone TEXT, structure TEXT, plan_week INTEGER,
            plan_day TEXT, garmin_workout_id TEXT,
            plan_version INTEGER DEFAULT 1, sequence_ordinal INTEGER DEFAULT 1,
            imported_at DATETIME, status TEXT DEFAULT 'active',
            UNIQUE(date, plan_version, sequence_ordinal)
        );
    """)
    return conn


def _populate_data(db):
    """Insert realistic mock data for integration testing."""
    today = date.today()

    # Race calendar
    race_date = (today + timedelta(days=174)).isoformat()
    db.execute("""
        INSERT INTO race_calendar (date, name, distance, distance_km, status, target_time)
        VALUES (?, 'Berlin Marathon', 'Marathon', 42.195, 'registered', '3:59:59')
    """, (race_date,))
    race_id = db.execute("SELECT id FROM race_calendar").fetchone()[0]

    # Goals linked to race
    db.execute("INSERT INTO goals (name, type, target_value, target_unit, active, race_id) VALUES ('VO2max', 'metric', 51, 'ml/kg/min', 1, ?)", (race_id,))
    db.execute("INSERT INTO goals (name, type, target_value, target_unit, active, race_id) VALUES ('Weight', 'metric', 75, 'kg', 1, ?)", (race_id,))

    # Training phase
    db.execute("""
        INSERT INTO training_phases (goal_id, phase, name, start_date, z12_pct_target,
            weekly_km_min, weekly_km_max, targets, status)
        VALUES (1, 'Phase 1', 'Base Building', '2026-01-01', 80, 20, 30,
            '{"run_frequency": [3,4]}', 'active')
    """)

    # Weekly aggs (6 weeks)
    for i in range(6):
        week = f"2026-W{10+i:02d}"
        km = 20 + i * 2
        db.execute("""
            INSERT INTO weekly_agg (week, run_count, run_km, longest_run_km,
                z12_pct, z45_pct, total_load, acwr, consecutive_weeks_3plus,
                z1_min, z2_min, z3_min, z4_min, z5_min, training_days,
                run_avg_pace, run_avg_hr, easy_run_count, quality_session_count,
                total_activities, cross_train_count, cross_train_min)
            VALUES (?, 3, ?, ?, 75, 5, 300, 1.1, ?, 10, 30, 5, 2, 0, 4, 360, 148, 2, 1, 3, 0, 0)
        """, (week, km, km * 0.4, i + 1))

    # Activities (last 4 weeks)
    for i in range(12):
        d = (today - timedelta(days=i * 2 + 1)).isoformat()
        dist = 8 + (i % 4) * 3
        db.execute("""
            INSERT INTO activities (id, date, type, name, distance_km, duration_min,
                pace_sec_per_km, avg_hr, speed_per_bpm, run_type, vo2max,
                training_load, hr_zone, effort_class)
            VALUES (?, ?, 'running', 'Run', ?, ?, 360, 148, 0.038, 'easy', 49,
                80, 'Z2', 'Easy')
        """, (f"r{i}", d, dist, dist * 6))

    # Health data
    for i in range(14):
        d = (today - timedelta(days=i)).isoformat()
        db.execute("""
            INSERT INTO daily_health (date, training_readiness, sleep_duration_hours,
                resting_heart_rate, hrv_last_night, avg_spo2)
            VALUES (?, 55, 7.5, 52, 45, 97)
        """, (d,))

    # Checkins
    for i in range(7):
        d = (today - timedelta(days=i * 2)).isoformat()
        db.execute("""
            INSERT INTO checkins (date, hydration, alcohol, legs, eating, energy,
                sleep_quality, rpe)
            VALUES (?, 'Good', 0, 'OK', 'Good', 'Normal', 'Good', 5)
        """, (d,))

    # Body comp
    db.execute("INSERT INTO body_comp (date, weight_kg) VALUES (?, 77.5)", (today.isoformat(),))

    db.commit()


class TestFullPipeline:
    def test_narratives_with_race_data(self, db):
        from fit.narratives import generate_trend_badges, generate_race_countdown
        _populate_data(db)

        badges = generate_trend_badges(db)
        assert isinstance(badges, (list, dict))

        countdown = generate_race_countdown(db)
        assert countdown is not None
        assert "Berlin" in countdown.get("message", "") or countdown.get("race_name") == "Berlin Marathon"

    def test_alert_pipeline(self, db):
        from fit.alerts import run_alerts
        _populate_data(db)

        config = {
            "profile": {"max_hr": 192, "zones_max_hr": {"z5": [173, 999], "z4": [154, 173], "z3": [134, 154], "z2": [115, 134], "z1": [0, 115]}},
            "coaching": {"spo2_alert_threshold": 95, "readiness_gate_threshold": 40},
        }
        alerts = run_alerts(db, config)
        assert isinstance(alerts, list)

    def test_correlation_pipeline(self, db):
        from fit.correlations import compute_all_correlations
        _populate_data(db)

        results = compute_all_correlations(db)
        assert isinstance(results, list)

    def test_milestone_detection(self, db):
        from fit.milestones import detect_milestones
        _populate_data(db)

        milestones = detect_milestones(db)
        assert isinstance(milestones, list)

    def test_periodization_evaluation(self, db):
        from fit.periodization import evaluate_phase_readiness
        _populate_data(db)

        result = evaluate_phase_readiness(db)
        assert result is not None
        assert result["action"] in ("advance", "continue", "extend", "deload", "taper", "insufficient_data")

    def test_goal_progress_from_db(self, db):
        _populate_data(db)

        goals = db.execute("SELECT * FROM goals WHERE active = 1").fetchall()
        assert len(goals) >= 2
        for g in goals:
            assert g["race_id"] is not None

    def test_target_race_resolution(self, db):
        from fit.goals import get_target_race
        _populate_data(db)

        race = get_target_race(db)
        assert race is not None
        assert race["name"] == "Berlin Marathon"
        assert race["distance_km"] == 42.195

    def test_wow_context(self, db):
        from fit.narratives import generate_wow_context
        _populate_data(db)

        wow = generate_wow_context(db)
        assert wow is not None

    def test_all_tables_populated(self, db):
        _populate_data(db)

        tables = ["activities", "daily_health", "checkins", "goals",
                   "training_phases", "weekly_agg", "race_calendar", "body_comp"]
        for t in tables:
            count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            assert count > 0, f"Table {t} is empty"
