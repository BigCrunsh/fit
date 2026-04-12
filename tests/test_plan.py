"""Tests for plan module: RUNNA_PATTERN, CSV import, adherence, readiness."""

import csv
import sqlite3
import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from fit.plan import (
    RUNNA_PATTERN,
    _parse_calendar_item,
    compute_plan_adherence,
    get_readiness_recommendation,
    import_plan_csv,
    validate_plan_csv,
)


@pytest.fixture
def db():
    """In-memory DB with full schema for plan tests."""
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
        CREATE TABLE planned_workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE NOT NULL,
            workout_name TEXT,
            workout_type TEXT,
            target_distance_km REAL,
            target_zone TEXT,
            structure TEXT,
            plan_week INTEGER,
            plan_day TEXT,
            garmin_workout_id TEXT,
            plan_version INTEGER DEFAULT 1,
            sequence_ordinal INTEGER DEFAULT 1,
            imported_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            UNIQUE(date, plan_version, sequence_ordinal)
        );
        CREATE INDEX idx_planned_date ON planned_workouts(date);
        CREATE INDEX idx_planned_version ON planned_workouts(plan_version, status);
    """)
    return conn


# ── RUNNA_PATTERN Regex ──


class TestRunnaPattern:
    def test_parse_interval_workout(self):
        """Should parse German interval workout name."""
        name = "W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)"
        match = RUNNA_PATTERN.match(name)
        assert match is not None
        assert match.group(1) == "2"
        assert match.group(2) == "Mi"
        assert match.group(3) == "Intervalle"
        assert match.group(4) == "1-km-Wiederholungen"
        assert match.group(5) == "7,5"

    def test_parse_long_run(self):
        """Should parse German long run name."""
        name = "W 5 Sa. Langer Lauf - Aerob (18 km)"
        match = RUNNA_PATTERN.match(name)
        assert match is not None
        assert match.group(1) == "5"
        assert match.group(2) == "Sa"
        assert match.group(3) == "Langer Lauf"
        assert match.group(5) == "18"

    def test_parse_easy_run(self):
        """Should parse Dauerlauf (easy run)."""
        name = "W 3 Do. Dauerlauf (8 km)"
        match = RUNNA_PATTERN.match(name)
        assert match is not None
        assert match.group(3) == "Dauerlauf"

    def test_no_match_for_non_runna(self):
        """Non-Runna names should not match."""
        name = "Morning Run"
        match = RUNNA_PATTERN.match(name)
        assert match is None


# ── Calendar Item Parsing ──


class TestParseCalendarItem:
    def test_parse_runna_formatted_item(self):
        """Should correctly parse a Runna-format calendar item."""
        item = {
            "title": "W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)",
            "date": "2026-04-08T00:00:00",
            "workoutId": "12345",
            "itemType": "workout",
        }
        result = _parse_calendar_item(item)
        assert result is not None
        assert result["plan_week"] == 2
        assert result["plan_day"] == "Mi"
        assert result["workout_type"] == "intervals"
        assert result["target_distance_km"] == 7.5
        assert result["date"] == "2026-04-08"

    def test_parse_non_runna_item_guesses_type(self):
        """Non-Runna items should fall back to type guessing."""
        item = {
            "title": "Recovery jog",
            "date": "2026-04-08T00:00:00",
            "id": "abc",
        }
        result = _parse_calendar_item(item)
        assert result is not None
        assert result["workout_type"] == "recovery"


# ── CSV Import ──


class TestCSVImport:
    def _write_csv(self, tmpdir, rows):
        """Write a CSV file and return its path."""
        path = Path(tmpdir) / "plan.csv"
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return str(path)

    def test_import_valid_csv(self, db):
        """Should import all rows from a valid CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                {"date": "2026-04-06", "name": "Easy Run", "type": "easy",
                 "distance_km": "8", "week": "1"},
                {"date": "2026-04-07", "name": "Rest Day", "type": "rest",
                 "distance_km": "", "week": "1"},
                {"date": "2026-04-08", "name": "Intervals", "type": "intervals",
                 "distance_km": "7.5", "week": "1"},
            ]
            path = self._write_csv(tmpdir, rows)
            count = import_plan_csv(db, path)
            assert count == 3

            stored = db.execute("SELECT * FROM planned_workouts ORDER BY date").fetchall()
            assert len(stored) == 3
            assert stored[0]["workout_type"] == "easy"
            assert stored[0]["target_distance_km"] == 8.0

    def test_import_versioning(self, db):
        """Second import should get a higher plan_version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [{"date": "2026-04-06", "name": "Run", "type": "easy",
                      "distance_km": "8", "week": "1"}]
            path = self._write_csv(tmpdir, rows)
            import_plan_csv(db, path, plan_version=1)
            import_plan_csv(db, path, plan_version=2)

            versions = db.execute(
                "SELECT DISTINCT plan_version FROM planned_workouts ORDER BY plan_version"
            ).fetchall()
            assert len(versions) == 2
            assert versions[0][0] == 1
            assert versions[1][0] == 2


# ── CSV Validation ──


class TestValidateCSV:
    def test_valid_csv_no_issues(self):
        """Valid CSV should return empty issues list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "plan.csv"
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(
                    f, fieldnames=["date", "name", "type", "distance_km"]
                )
                writer.writeheader()
                writer.writerow({
                    "date": "2026-04-06", "name": "Run", "type": "easy",
                    "distance_km": "8",
                })
            issues = validate_plan_csv(str(path))
            assert issues == []

    def test_missing_date_column(self):
        """CSV without date column should report issue."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "plan.csv"
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["name", "type"])
                writer.writeheader()
                writer.writerow({"name": "Run", "type": "easy"})
            issues = validate_plan_csv(str(path))
            assert any("date" in i.lower() for i in issues)

    def test_file_not_found(self):
        """Non-existent file should report issue."""
        issues = validate_plan_csv("/nonexistent/plan.csv")
        assert len(issues) == 1
        assert "not found" in issues[0].lower()


# ── Plan Adherence ──


class TestPlanAdherence:
    def _get_week_str(self):
        today = date.today()
        iso = today.isocalendar()
        return f"{iso.year}-W{iso.week:02d}"

    def test_no_plan_returns_empty(self, db):
        """No planned workouts should return empty compliance."""
        result = compute_plan_adherence(db, self._get_week_str())
        assert result["planned"] == []
        assert result["weekly_compliance_pct"] is None

    def test_matched_workout(self, db):
        """Activity on planned day should be matched."""
        today = date.today().isoformat()
        week_str = self._get_week_str()

        db.execute("""
            INSERT INTO planned_workouts (date, workout_name, workout_type,
                target_distance_km, plan_version, sequence_ordinal, status)
            VALUES (?, 'Easy Run', 'easy', 8.0, 1, 1, 'active')
        """, (today,))
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min,
                effort_class)
            VALUES ('a1', ?, 'running', 8.2, 45, 'Easy')
        """, (today,))
        db.commit()

        result = compute_plan_adherence(db, week_str)
        assert result["weekly_compliance_pct"] == 100
        assert len(result["missed"]) == 0

    def test_missed_and_unplanned(self, db):
        """Missing planned workout + extra activity should be detected."""
        today = date.today()
        # Use Monday of current week to avoid week-boundary issues
        monday = today - timedelta(days=today.weekday())
        tuesday = monday + timedelta(days=1)
        week_str = self._get_week_str()

        # Planned workout on Tuesday, but no activity
        db.execute("""
            INSERT INTO planned_workouts (date, workout_name, workout_type,
                target_distance_km, plan_version, sequence_ordinal, status)
            VALUES (?, 'Tempo Run', 'tempo', 10.0, 1, 1, 'active')
        """, (tuesday.isoformat(),))
        # Unplanned activity on Monday
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min)
            VALUES ('a1', ?, 'running', 5.0, 30)
        """, (monday.isoformat(),))
        db.commit()

        result = compute_plan_adherence(db, week_str)
        assert len(result["missed"]) == 1
        assert len(result["unplanned"]) == 1

    def test_multiple_workouts_same_day(self, db):
        """Multiple planned workouts on the same day should each be tracked."""
        today = date.today().isoformat()
        week_str = self._get_week_str()

        db.execute("""
            INSERT INTO planned_workouts (date, workout_name, workout_type,
                target_distance_km, plan_version, sequence_ordinal, status)
            VALUES (?, 'Morning Easy', 'easy', 5.0, 1, 1, 'active')
        """, (today,))
        db.execute("""
            INSERT INTO planned_workouts (date, workout_name, workout_type,
                target_distance_km, plan_version, sequence_ordinal, status)
            VALUES (?, 'Evening Tempo', 'tempo', 8.0, 1, 2, 'active')
        """, (today,))
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min,
                effort_class)
            VALUES ('a1', ?, 'running', 5.1, 28, 'Easy')
        """, (today,))
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min,
                effort_class)
            VALUES ('a2', ?, 'running', 7.8, 40, 'Hard')
        """, (today,))
        db.commit()

        result = compute_plan_adherence(db, week_str)
        assert result["weekly_compliance_pct"] == 100
        assert len(result["missed"]) == 0


# ── Readiness Recommendation ──


class TestReadinessRecommendation:
    def test_no_planned_workout(self, db):
        """No planned workout today should return appropriate message."""
        config = {}
        result = get_readiness_recommendation(db, config)
        assert result["planned"] is None
        assert result["recommend_swap"] is False
        assert "No planned workout" in result["recommendation"]

    def test_low_readiness_quality_session_swap(self, db):
        """Low readiness + quality session should recommend swap."""
        today = date.today().isoformat()
        db.execute("""
            INSERT INTO planned_workouts (date, workout_name, workout_type,
                target_distance_km, plan_version, sequence_ordinal, status)
            VALUES (?, 'Tempo Run', 'tempo', 10.0, 1, 1, 'active')
        """, (today,))
        db.execute("""
            INSERT INTO daily_health (date, training_readiness)
            VALUES (?, 25)
        """, (today,))
        db.commit()

        config = {"coaching": {"readiness_gate_threshold": 40}}
        result = get_readiness_recommendation(db, config)
        assert result["recommend_swap"] is True
        assert result["readiness"] == 25
        assert "swap" in result["recommendation"].lower()

    def test_low_readiness_easy_session_no_swap(self, db):
        """Low readiness + easy session should NOT recommend swap."""
        today = date.today().isoformat()
        db.execute("""
            INSERT INTO planned_workouts (date, workout_name, workout_type,
                target_distance_km, plan_version, sequence_ordinal, status)
            VALUES (?, 'Easy Run', 'easy', 8.0, 1, 1, 'active')
        """, (today,))
        db.execute("""
            INSERT INTO daily_health (date, training_readiness)
            VALUES (?, 25)
        """, (today,))
        db.commit()

        config = {"coaching": {"readiness_gate_threshold": 40}}
        result = get_readiness_recommendation(db, config)
        assert result["recommend_swap"] is False
