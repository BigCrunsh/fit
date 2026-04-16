"""Tests for fit/sync.py — upsert functions, race matching, weight import, week computation."""

import csv
import tempfile
from datetime import date
from pathlib import Path


from fit.sync import (
    _upsert_health,
    _upsert_activity,
    _upsert_enriched_activity,
    _match_race_calendar,
    _auto_import_weight,
    _get_affected_weeks,
)


# ════════════════════════════════════════════════════════════════
# _upsert_health
# ════════════════════════════════════════════════════════════════


class TestUpsertHealth:
    """Tests for INSERT ON CONFLICT behavior of health upsert."""

    def _health_row(self, **overrides):
        base = {
            "date": "2025-01-15",
            "total_steps": 8000, "total_distance_m": 6000.0,
            "total_calories": 2000, "active_calories": 700,
            "resting_heart_rate": 55, "max_heart_rate": 140, "min_heart_rate": 48,
            "avg_stress_level": 30, "max_stress_level": 70,
            "body_battery_high": 90, "body_battery_low": 25,
            "sleep_duration_hours": 7.5, "deep_sleep_hours": 1.2,
            "light_sleep_hours": 4.0, "rem_sleep_hours": 1.8, "awake_hours": 0.5,
            "deep_sleep_pct": 16.0,
            "training_readiness": 78, "readiness_level": "PRIME",
            "hrv_weekly_avg": 45, "hrv_last_night": 42, "hrv_status": "BALANCED",
            "avg_respiration": 16.5, "avg_spo2": None,
        }
        base.update(overrides)
        return base

    def test_insert_new_row(self, db):
        _upsert_health(db, self._health_row())
        row = db.execute("SELECT * FROM daily_health WHERE date = '2025-01-15'").fetchone()
        assert row is not None
        assert row["total_steps"] == 8000
        assert row["resting_heart_rate"] == 55

    def test_update_on_conflict(self, db):
        _upsert_health(db, self._health_row(total_steps=8000))
        _upsert_health(db, self._health_row(total_steps=9000))
        row = db.execute("SELECT * FROM daily_health WHERE date = '2025-01-15'").fetchone()
        assert row["total_steps"] == 9000

    def test_spo2_preserved_via_coalesce(self, db):
        # First insert with spo2
        _upsert_health(db, self._health_row(avg_spo2=97))
        # Second insert without spo2
        _upsert_health(db, self._health_row(avg_spo2=None))
        row = db.execute("SELECT avg_spo2 FROM daily_health WHERE date = '2025-01-15'").fetchone()
        assert row["avg_spo2"] == 97


# ════════════════════════════════════════════════════════════════
# _upsert_activity
# ════════════════════════════════════════════════════════════════


class TestUpsertActivity:
    """Tests for activity upsert — derived metrics preserved on re-sync."""

    def _activity(self, **overrides):
        base = {
            "id": "act-001", "date": "2025-01-15", "type": "running",
            "subtype": "manual", "name": "Morning Run",
            "distance_km": 10.0, "duration_min": 50.0, "pace_sec_per_km": 300,
            "avg_hr": 145, "max_hr": 168, "avg_cadence": 172,
            "elevation_gain_m": 100, "calories": 600,
            "vo2max": 48.5, "aerobic_te": 3.2, "training_load": 200,
            "avg_stride_m": 1.15, "avg_speed": 3.33,
            "start_lat": 52.52, "start_lon": 13.405,
        }
        base.update(overrides)
        return base

    def _enriched_activity(self, **overrides):
        base = self._activity()
        base.update({
            "hr_zone_maxhr": "Z2", "hr_zone_lthr": "Z2", "hr_zone": "Z2",
            "speed_per_bpm": 1.38, "speed_per_bpm_z2": 1.38,
            "effort_class": "Easy", "run_type": "easy",
            "max_hr_used": 192, "lthr_used": 172,
        })
        base.update(overrides)
        return base

    def test_insert_new_activity(self, db):
        _upsert_activity(db, self._activity())
        row = db.execute("SELECT * FROM activities WHERE id = 'act-001'").fetchone()
        assert row is not None
        assert row["distance_km"] == 10.0

    def test_preserves_derived_metrics_on_resync(self, db):
        """Key design decision: INSERT ON CONFLICT preserves zones, efficiency, run_type."""
        _upsert_enriched_activity(db, self._enriched_activity())
        # Re-sync with raw data only (no derived fields)
        _upsert_activity(db, self._activity(distance_km=10.5))
        row = db.execute("SELECT * FROM activities WHERE id = 'act-001'").fetchone()
        # Raw field should update
        assert row["distance_km"] == 10.5
        # Derived fields should be preserved (not overwritten to NULL)
        assert row["hr_zone"] == "Z2"
        assert row["effort_class"] == "Easy"
        assert row["speed_per_bpm"] == 1.38

    def test_enriched_insert_stores_all_fields(self, db):
        _upsert_enriched_activity(db, self._enriched_activity())
        row = db.execute("SELECT * FROM activities WHERE id = 'act-001'").fetchone()
        assert row["hr_zone_maxhr"] == "Z2"
        assert row["hr_zone_lthr"] == "Z2"
        assert row["effort_class"] == "Easy"
        assert row["run_type"] == "easy"
        assert row["max_hr_used"] == 192


# ════════════════════════════════════════════════════════════════
# _match_race_calendar
# ════════════════════════════════════════════════════════════════


class TestMatchRaceCalendar:
    """Tests for linking race_calendar entries to activities by date."""

    def test_matches_completed_race_to_activity(self, db):
        # Insert a race calendar entry
        db.execute("""
            INSERT INTO race_calendar (name, date, distance, distance_km, status)
            VALUES ('Berlin HM', '2025-03-30', 'Half Marathon', 21.1, 'completed')
        """)
        # Insert a matching running activity
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min)
            VALUES ('act-hm', '2025-03-30', 'running', 21.3, 105.0)
        """)
        db.commit()

        _match_race_calendar(db)

        rc = db.execute("SELECT activity_id FROM race_calendar WHERE name = 'Berlin HM'").fetchone()
        assert rc["activity_id"] == "act-hm"

        act = db.execute("SELECT run_type FROM activities WHERE id = 'act-hm'").fetchone()
        assert act["run_type"] == "race"

    def test_skips_future_registered_races(self, db):
        """Registered races with a future date are not auto-completed."""
        db.execute("""
            INSERT INTO race_calendar (name, date, distance, distance_km, status)
            VALUES ('Future Race', '2099-10-01', '10K', 10.0, 'registered')
        """)
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min)
            VALUES ('act-f', '2099-10-01', 'running', 10.2, 48.0)
        """)
        db.commit()

        _match_race_calendar(db)

        rc = db.execute("SELECT activity_id, status FROM race_calendar WHERE name = 'Future Race'").fetchone()
        assert rc["activity_id"] is None
        assert rc["status"] == "registered"

    def test_auto_completes_past_registered_race(self, db):
        """Registered races whose date has passed get auto-completed when an activity exists."""
        db.execute("""
            INSERT INTO race_calendar (name, date, distance, distance_km, status)
            VALUES ('Past Race', '2025-06-01', '10K', 10.0, 'registered')
        """)
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min)
            VALUES ('act-past', '2025-06-01', 'running', 10.2, 48.0)
        """)
        db.commit()

        _match_race_calendar(db)

        rc = db.execute("SELECT activity_id, status FROM race_calendar WHERE name = 'Past Race'").fetchone()
        assert rc["status"] == "completed"
        assert rc["activity_id"] == "act-past"

    def test_no_auto_complete_without_activity(self, db):
        """Registered races whose date has passed stay registered if no activity exists."""
        db.execute("""
            INSERT INTO race_calendar (name, date, distance, distance_km, status)
            VALUES ('Missed Race', '2025-06-01', '10K', 10.0, 'registered')
        """)
        db.commit()

        _match_race_calendar(db)

        rc = db.execute("SELECT status FROM race_calendar WHERE name = 'Missed Race'").fetchone()
        assert rc["status"] == "registered"

    def test_picks_closest_distance_on_date(self, db):
        """When multiple activities on race day, picks closest distance to race."""
        db.execute("""
            INSERT INTO race_calendar (name, date, distance, distance_km, status)
            VALUES ('Park Run', '2025-02-01', '5K', 5.0, 'completed')
        """)
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min)
            VALUES ('act-short', '2025-02-01', 'running', 3.0, 15.0)
        """)
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min)
            VALUES ('act-close', '2025-02-01', 'running', 5.1, 25.0)
        """)
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km, duration_min)
            VALUES ('act-long', '2025-02-01', 'running', 12.0, 60.0)
        """)
        db.commit()

        _match_race_calendar(db)

        rc = db.execute("SELECT activity_id FROM race_calendar WHERE name = 'Park Run'").fetchone()
        assert rc["activity_id"] == "act-close"


# ════════════════════════════════════════════════════════════════
# _auto_import_weight
# ════════════════════════════════════════════════════════════════


class TestAutoImportWeight:
    """Tests for CSV weight import and deduplication via import_log."""

    def test_imports_csv(self, db):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Weight"])
            writer.writerow(["2025-01-10", "77.5"])
            writer.writerow(["2025-01-11", "77.2"])
            csv_path = Path(f.name)

        _auto_import_weight(db, csv_path)

        rows = db.execute("SELECT * FROM body_comp ORDER BY date").fetchall()
        assert len(rows) == 2
        assert rows[0]["weight_kg"] == 77.5

    def test_skips_duplicate_import(self, db):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Weight"])
            writer.writerow(["2025-01-10", "77.5"])
            csv_path = Path(f.name)

        _auto_import_weight(db, csv_path)
        _auto_import_weight(db, csv_path)  # same file, should skip

        rows = db.execute("SELECT * FROM body_comp").fetchall()
        assert len(rows) == 1  # not duplicated

    def test_skips_existing_dates(self, db):
        # Pre-insert a weight for the same date
        db.execute("INSERT INTO body_comp (date, weight_kg, source) VALUES ('2025-01-10', 78.0, 'checkin')")
        db.commit()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Weight"])
            writer.writerow(["2025-01-10", "77.5"])
            writer.writerow(["2025-01-11", "77.2"])
            csv_path = Path(f.name)

        _auto_import_weight(db, csv_path)

        row = db.execute("SELECT weight_kg FROM body_comp WHERE date = '2025-01-10'").fetchone()
        assert row["weight_kg"] == 78.0  # preserved, not overwritten

    def test_handles_bad_values(self, db):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False, newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Weight"])
            writer.writerow(["2025-01-10", "not-a-number"])
            writer.writerow(["2025-01-11", "77.2"])
            csv_path = Path(f.name)

        _auto_import_weight(db, csv_path)

        rows = db.execute("SELECT * FROM body_comp").fetchall()
        assert len(rows) == 1
        assert rows[0]["date"] == "2025-01-11"

    def test_missing_file_does_nothing(self, db):
        _auto_import_weight(db, Path("/nonexistent/weight.csv"))
        rows = db.execute("SELECT * FROM body_comp").fetchall()
        assert len(rows) == 0


# ════════════════════════════════════════════════════════════════
# _get_affected_weeks
# ════════════════════════════════════════════════════════════════


class TestGetAffectedWeeks:
    """Tests for ISO week computation from date range."""

    def test_single_day(self):
        weeks = _get_affected_weeks([], date(2025, 1, 15), date(2025, 1, 15))
        assert len(weeks) == 1
        assert "2025-W03" in weeks

    def test_week_boundary(self):
        # Sunday Jan 5 and Monday Jan 6 are different ISO weeks
        weeks = _get_affected_weeks([], date(2025, 1, 5), date(2025, 1, 6))
        assert len(weeks) == 2
        assert "2025-W01" in weeks
        assert "2025-W02" in weeks

    def test_seven_day_range(self):
        weeks = _get_affected_weeks([], date(2025, 1, 1), date(2025, 1, 7))
        # Jan 1 = W01, Jan 6-7 = W02
        assert len(weeks) >= 1

    def test_returns_set_of_strings(self):
        weeks = _get_affected_weeks([], date(2025, 1, 1), date(2025, 1, 31))
        assert isinstance(weeks, set)
        for w in weeks:
            assert isinstance(w, str)
            assert "-W" in w
