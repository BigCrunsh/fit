"""Tests for fit/report/generator.py — dashboard generation edge cases."""

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest

from fit.report.generator import (
    generate_dashboard,
    _headline,
    _status_cards,
    _checkin,
    _journey,
    _week_over_week,
    _run_timeline,
)


# ════════════════════════════════════════════════════════════════
# Generator with Empty DB
# ════════════════════════════════════════════════════════════════


class TestGeneratorEmptyDB:
    # Happy (smoke test)
    def test_generates_html_with_empty_db(self, db):
        """Dashboard should generate without crashing on empty DB."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dashboard.html"
            generate_dashboard(db, output)
            assert output.exists()
            content = output.read_text()
            assert "<html" in content.lower() or "<!doctype" in content.lower() or len(content) > 100

    # Unhappy
    def test_headline_empty_db(self, db):
        """Headline with no data should return a non-empty string."""
        result = _headline(db)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_status_cards_empty_db(self, db):
        """Status cards with no health data returns empty list."""
        result = _status_cards(db)
        assert result == []

    def test_checkin_empty_db(self, db):
        """With no user checkins (or backfill data), result should be None or a dict."""
        # Backfill migrations may have populated checkins, so clear them
        db.execute("DELETE FROM checkins")
        db.commit()
        result = _checkin(db)
        assert result is None

    def test_journey_empty_db(self, db):
        result = _journey(db)
        assert result is None

    def test_week_over_week_empty_db(self, db):
        result = _week_over_week(db)
        assert result is None

    def test_run_timeline_empty_db(self, db):
        result = _run_timeline(db)
        assert result == []


# ════════════════════════════════════════════════════════════════
# Generator with NULL Fields
# ════════════════════════════════════════════════════════════════


class TestGeneratorNullFields:
    def _insert_health(self, db, day, **kwargs):
        defaults = {"date": day}
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        db.execute(f"INSERT INTO daily_health ({cols}) VALUES ({placeholders})",
                   list(defaults.values()))
        db.commit()

    def _insert_activity(self, db, day, **kwargs):
        defaults = {"id": f"act-{day}", "date": day, "type": "running"}
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        db.execute(f"INSERT INTO activities ({cols}) VALUES ({placeholders})",
                   list(defaults.values()))
        db.commit()

    def _insert_weekly(self, db, week, **kwargs):
        defaults = {"week": week}
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        db.execute(f"INSERT INTO weekly_agg ({cols}) VALUES ({placeholders})",
                   list(defaults.values()))
        db.commit()

    # Unhappy: all NULL fields
    def test_headline_with_null_readiness(self, db):
        self._insert_health(db, date.today().isoformat(), training_readiness=None)
        result = _headline(db)
        assert isinstance(result, str)

    def test_status_cards_with_null_fields(self, db):
        """Health row with all NULLs should not crash."""
        self._insert_health(db, date.today().isoformat())
        result = _status_cards(db)
        assert isinstance(result, list)

    def test_checkin_with_null_fields(self, db):
        db.execute("INSERT INTO checkins (date) VALUES (?)", (date.today().isoformat(),))
        db.commit()
        result = _checkin(db)
        assert result is not None
        assert result["date"] == date.today().isoformat()

    def test_run_timeline_with_null_fields(self, db):
        self._insert_activity(db, date.today().isoformat(),
                              distance_km=None, hr_zone=None, run_type=None, rpe=None)
        result = _run_timeline(db)
        assert len(result) == 1
        assert result[0]["distance_km"] == "0.0"

    def test_week_over_week_with_null_fields(self, db):
        self._insert_weekly(db, "2026-W13", run_km=None, run_count=None, z12_pct=None, acwr=None)
        self._insert_weekly(db, "2026-W14", run_km=None, run_count=None, z12_pct=None, acwr=None)
        result = _week_over_week(db)
        assert result is not None

    def test_journey_with_goal_no_phases(self, db):
        db.execute("INSERT INTO goals (id, name, type, target_date, active) VALUES (1, 'Marathon', 'marathon', '2026-10-25', 1)")
        db.commit()
        result = _journey(db)
        assert result is None

    def test_journey_with_goal_and_phases(self, db):
        db.execute("INSERT INTO goals (id, name, type, target_date, active) VALUES (1, 'Marathon', 'marathon', '2026-10-25', 1)")
        db.execute("""INSERT INTO training_phases (id, goal_id, phase, name, start_date, end_date, status)
                      VALUES (1, 1, 'P1', 'Base', '2026-04-01', '2026-06-01', 'active')""")
        db.commit()
        result = _journey(db)
        assert result is not None
        assert "Marathon" in result["goal_name"]

    def test_generate_full_dashboard_with_data(self, db):
        """Full dashboard with some data should not crash."""
        today = date.today().isoformat()
        self._insert_health(db, today, training_readiness=70, resting_heart_rate=55,
                            sleep_duration_hours=7.5, hrv_last_night=45, deep_sleep_hours=1.2)
        self._insert_activity(db, today, name="Easy Run", distance_km=7, duration_min=45,
                              avg_hr=130, hr_zone="Z2", run_type="easy", training_load=100)
        self._insert_weekly(db, "2026-W14", run_km=25, run_count=3, acwr=1.0, z12_pct=85)
        self._insert_weekly(db, "2026-W13", run_km=22, run_count=3, acwr=0.95, z12_pct=88)

        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "dashboard.html"
            generate_dashboard(db, output)
            assert output.exists()
            content = output.read_text()
            assert len(content) > 500

    def test_generate_creates_parent_dirs(self, db):
        """Output path with non-existent parent dirs should be created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "a" / "b" / "dashboard.html"
            generate_dashboard(db, output)
            assert output.exists()


# ════════════════════════════════════════════════════════════════
# Week-over-Week
# ════════════════════════════════════════════════════════════════


class TestWeekOverWeek:
    def _insert_weekly(self, db, week, **kwargs):
        defaults = {"week": week}
        defaults.update(kwargs)
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join(["?"] * len(defaults))
        db.execute(f"INSERT INTO weekly_agg ({cols}) VALUES ({placeholders})",
                   list(defaults.values()))
        db.commit()

    # Happy
    def test_two_weeks_comparison(self, db):
        self._insert_weekly(db, "2026-W13", run_km=22, run_count=3, z12_pct=85, acwr=0.95)
        self._insert_weekly(db, "2026-W14", run_km=28, run_count=4, z12_pct=88, acwr=1.1)
        result = _week_over_week(db)
        assert result is not None
        assert "28km" in result or "28" in result
        assert "W" not in result or "ACWR" in result

    # Unhappy
    def test_only_one_week(self, db):
        self._insert_weekly(db, "2026-W14", run_km=25)
        result = _week_over_week(db)
        assert result is None

    def test_zero_weeks(self, db):
        result = _week_over_week(db)
        assert result is None
