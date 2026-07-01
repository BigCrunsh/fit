"""Tests for fit/report/generator.py — dashboard generation edge cases."""

import tempfile
from datetime import date
from pathlib import Path


from fit.report.generator import (
    generate_dashboard,
    _headline,
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
