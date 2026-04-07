"""Tests for race-anchored model: migration 007, get_target_race, milestones, goal progress."""

import sqlite3
from datetime import date, timedelta

import pytest

from fit.goals import get_target_race
from fit.milestones import detect_milestones


@pytest.fixture
def db():
    """In-memory DB with full schema including Phase 2a migrations."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    conn.executescript("""
        CREATE TABLE activities (
            id TEXT PRIMARY KEY, date DATE, type TEXT, name TEXT,
            distance_km REAL, duration_min REAL, pace_sec_per_km REAL,
            avg_hr INTEGER, speed_per_bpm REAL, run_type TEXT,
            vo2max REAL, training_load REAL, hr_zone TEXT,
            srpe REAL, fit_file_path TEXT, splits_status TEXT,
            temp_at_start_c REAL, humidity_at_start_pct REAL,
            max_hr INTEGER, rpe INTEGER,
            hr_zone_maxhr TEXT, hr_zone_lthr TEXT, effort_class TEXT,
            speed_per_bpm_z2 REAL, max_hr_used INTEGER, lthr_used INTEGER,
            subtype TEXT, avg_cadence REAL, elevation_gain_m REAL,
            calories INTEGER, aerobic_te REAL,
            avg_stride_m REAL, avg_speed REAL, start_lat REAL, start_lon REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE race_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE NOT NULL,
            name TEXT NOT NULL, organizer TEXT, distance TEXT NOT NULL,
            distance_km REAL, status TEXT DEFAULT 'planned',
            target_time TEXT, result_time TEXT, result_pace REAL,
            activity_id TEXT REFERENCES activities(id),
            garmin_time TEXT, notes TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            type TEXT NOT NULL, target_time TEXT, target_pace REAL,
            target_value REAL, target_unit TEXT, target_date DATE,
            active BOOLEAN DEFAULT 1, race_id INTEGER REFERENCES race_calendar(id),
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE weekly_agg (
            week TEXT PRIMARY KEY, run_count INTEGER, run_km REAL,
            longest_run_km REAL, consecutive_weeks_3plus INTEGER,
            total_load REAL, acwr REAL,
            z1_min REAL, z2_min REAL, z3_min REAL, z4_min REAL, z5_min REAL,
            z12_pct REAL, z45_pct REAL, run_avg_pace REAL, run_avg_hr REAL,
            run_avg_cadence REAL, easy_run_count INTEGER,
            quality_session_count INTEGER, cross_train_count INTEGER,
            cross_train_min REAL, total_activities INTEGER,
            avg_readiness REAL, avg_sleep REAL, avg_rhr REAL, avg_hrv REAL,
            weight_avg REAL, training_days INTEGER,
            monotony REAL, strain REAL, cycling_km REAL, cycling_min REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE body_comp (
            date DATE PRIMARY KEY, weight_kg REAL, body_fat_pct REAL,
            muscle_mass_kg REAL, visceral_fat REAL, source TEXT
        );
    """)
    return conn


# ── Migration Schema Tests ──


class TestMigration007Schema:
    def test_goals_has_race_id(self, db):
        cols = [r[1] for r in db.execute("PRAGMA table_info(goals)").fetchall()]
        assert "race_id" in cols

    def test_race_calendar_has_garmin_time(self, db):
        cols = [r[1] for r in db.execute("PRAGMA table_info(race_calendar)").fetchall()]
        assert "garmin_time" in cols

    def test_activities_has_srpe(self, db):
        cols = [r[1] for r in db.execute("PRAGMA table_info(activities)").fetchall()]
        assert "srpe" in cols

    def test_weekly_agg_has_monotony(self, db):
        cols = [r[1] for r in db.execute("PRAGMA table_info(weekly_agg)").fetchall()]
        assert "monotony" in cols
        assert "strain" in cols
        assert "cycling_km" in cols
        assert "cycling_min" in cols

    def test_goals_race_id_fk(self, db):
        """race_id FK references race_calendar."""
        db.execute("INSERT INTO race_calendar (date, name, distance, status) VALUES ('2026-09-27', 'Berlin', 'Marathon', 'registered')")
        race_id = db.execute("SELECT id FROM race_calendar").fetchone()[0]
        db.execute("INSERT INTO goals (name, type, race_id) VALUES ('Sub-4', 'race', ?)", (race_id,))
        db.commit()
        goal = db.execute("SELECT race_id FROM goals WHERE name='Sub-4'").fetchone()
        assert goal["race_id"] == race_id


# ── Target Race Resolution ──


class TestGetTargetRace:
    def test_returns_next_registered_race(self, db):
        future = (date.today() + timedelta(days=100)).isoformat()
        db.execute("INSERT INTO race_calendar (date, name, distance, status) VALUES (?, 'Berlin Marathon', 'Marathon', 'registered')", (future,))
        db.commit()

        result = get_target_race(db)
        assert result is not None
        assert result["name"] == "Berlin Marathon"

    def test_returns_none_when_no_races(self, db):
        result = get_target_race(db)
        assert result is None

    def test_ignores_past_races(self, db):
        past = (date.today() - timedelta(days=10)).isoformat()
        db.execute("INSERT INTO race_calendar (date, name, distance, status) VALUES (?, 'Past Race', 'Half', 'completed')", (past,))
        db.commit()

        result = get_target_race(db)
        assert result is None

    def test_returns_anchor_not_nearest(self, db):
        """Target race = longest distance (anchor), not nearest."""
        near = (date.today() + timedelta(days=30)).isoformat()
        far = (date.today() + timedelta(days=200)).isoformat()
        db.execute("INSERT INTO race_calendar (date, name, distance, distance_km, status) VALUES (?, '10K', '10km', 10.0, 'registered')", (near,))
        db.execute("INSERT INTO race_calendar (date, name, distance, distance_km, status) VALUES (?, 'Marathon', 'Marathon', 42.195, 'registered')", (far,))
        db.commit()

        result = get_target_race(db)
        assert result["name"] == "Marathon"  # anchor = longest, not nearest


# ── Milestone Detection ──


class TestMilestones:
    def test_new_longest_run(self, db):
        old_date = (date.today() - timedelta(days=30)).isoformat()
        recent_date = (date.today() - timedelta(days=2)).isoformat()
        db.execute("INSERT INTO activities (id, date, type, distance_km, run_type) VALUES ('r1', ?, 'running', 15.0, 'long')", (old_date,))
        db.execute("INSERT INTO activities (id, date, type, distance_km, run_type) VALUES ('r2', ?, 'running', 18.0, 'long')", (recent_date,))
        db.commit()

        milestones = detect_milestones(db)
        longest = [m for m in milestones if m["type"] == "longest_run"]
        assert len(longest) >= 1
        assert longest[0]["new_value"] == 18.0

    def test_streak_milestone(self, db):
        # Streak = 8 (exact milestone)
        iso = date.today().isocalendar()
        week = f"{iso.year}-W{iso.week:02d}"
        db.execute("INSERT INTO weekly_agg (week, run_count, consecutive_weeks_3plus) VALUES (?, 4, 8)", (week,))
        db.commit()

        milestones = detect_milestones(db)
        streaks = [m for m in milestones if m["type"] == "streak_milestone"]
        assert len(streaks) >= 1

    def test_no_milestones_single_run(self, db):
        recent = (date.today() - timedelta(days=1)).isoformat()
        db.execute("INSERT INTO activities (id, date, type, distance_km, run_type) VALUES ('r1', ?, 'running', 10.0, 'easy')", (recent,))
        db.commit()

        milestones = detect_milestones(db)
        longest = [m for m in milestones if m["type"] == "longest_run"]
        # Single run can't be a "new" longest since there's no previous
        assert len(longest) == 0

    def test_vo2max_peak(self, db):
        old = (date.today() - timedelta(days=60)).isoformat()
        recent = (date.today() - timedelta(days=3)).isoformat()
        db.execute("INSERT INTO activities (id, date, type, vo2max, run_type) VALUES ('r1', ?, 'running', 48.0, 'easy')", (old,))
        db.execute("INSERT INTO activities (id, date, type, vo2max, run_type) VALUES ('r3', ?, 'running', 51.0, 'easy')", (recent,))
        db.commit()

        milestones = detect_milestones(db)
        vo2 = [m for m in milestones if m["type"] == "vo2max_peak"]
        assert len(vo2) >= 1
