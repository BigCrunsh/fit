"""Tests for fit/db.py — migration runner."""

import tempfile
from pathlib import Path

from fit.db import get_db


class TestMigrationRunner:
    def test_applies_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=Path(__file__).parent.parent / "migrations")
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            assert "activities" in tables
            assert "daily_health" in tables
            assert "calibration" in tables
            conn.close()

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            mdir = Path(__file__).parent.parent / "migrations"
            conn1 = get_db(config, migrations_dir=mdir)
            v1 = [r[0] for r in conn1.execute("SELECT version FROM schema_version").fetchall()]
            conn1.close()

            conn2 = get_db(config, migrations_dir=mdir)
            v2 = [r[0] for r in conn2.execute("SELECT version FROM schema_version").fetchall()]
            conn2.close()

            assert v1 == v2
