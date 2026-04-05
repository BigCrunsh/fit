"""Tests for fit/db.py — migration runner, schema, transactions."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from fit.db import get_db, _discover_migrations, _get_applied_versions


MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


# ════════════════════════════════════════════════════════════════
# Schema and Migration Basics
# ════════════════════════════════════════════════════════════════


class TestMigrationRunner:
    # Happy
    def test_applies_schema(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            assert "activities" in tables
            assert "daily_health" in tables
            assert "calibration" in tables
            assert "checkins" in tables
            assert "body_comp" in tables
            assert "weather" in tables
            assert "goals" in tables
            assert "training_phases" in tables
            assert "goal_log" in tables
            assert "weekly_agg" in tables
            assert "schema_version" in tables
            conn.close()

    def test_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn1 = get_db(config, migrations_dir=MIGRATIONS_DIR)
            v1 = sorted(r[0] for r in conn1.execute("SELECT version FROM schema_version").fetchall())
            conn1.close()

            conn2 = get_db(config, migrations_dir=MIGRATIONS_DIR)
            v2 = sorted(r[0] for r in conn2.execute("SELECT version FROM schema_version").fetchall())
            conn2.close()

            assert v1 == v2

    def test_row_factory_is_set(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
            assert conn.row_factory == sqlite3.Row
            conn.close()

    def test_wal_mode_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
            conn.close()

    def test_foreign_keys_enabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1
            conn.close()

    def test_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            deep_path = f"{tmpdir}/a/b/c/test.db"
            config = {"sync": {"db_path": deep_path}}
            conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
            assert Path(deep_path).exists()
            conn.close()

    def test_schema_version_tracks_all_migrations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
            versions = _get_applied_versions(conn)
            assert 1 in versions  # at minimum, 001_schema.sql
            conn.close()

    # Unhappy
    def test_no_migrations_dir(self):
        """Non-existent migrations dir should not crash — just skip."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=Path(tmpdir) / "nonexistent_migrations")
            # Only schema_version table exists (created before migrations)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            assert "schema_version" in tables
            conn.close()

    def test_empty_migrations_dir(self):
        """Empty migrations dir should apply nothing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir) / "empty_migrations"
            mdir.mkdir()
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=mdir)
            versions = _get_applied_versions(conn)
            assert len(versions) == 0
            conn.close()

    def test_sql_migration_failure_rolls_back(self):
        """A bad SQL migration should rollback and raise RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir) / "bad_migrations"
            mdir.mkdir()
            (mdir / "001_bad.sql").write_text("INVALID SQL STATEMENT;")
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            with pytest.raises(RuntimeError, match="Migration 001"):
                get_db(config, migrations_dir=mdir)

    def test_python_migration_failure_rolls_back(self):
        """A Python migration that raises should rollback."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir) / "bad_py_migrations"
            mdir.mkdir()
            # First, a valid SQL migration to create something
            (mdir / "001_ok.sql").write_text("CREATE TABLE test_tbl (id INTEGER);")
            (mdir / "002_bad.py").write_text(
                "def run(conn):\n    raise ValueError('intentional error')\n"
            )
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            with pytest.raises(RuntimeError, match="Migration 002"):
                get_db(config, migrations_dir=mdir)

    def test_python_migration_missing_run_function(self):
        """Python migration without run() should raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir) / "norun_migrations"
            mdir.mkdir()
            (mdir / "001_norun.py").write_text("x = 1\n")
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            with pytest.raises(RuntimeError, match="Migration 001"):
                get_db(config, migrations_dir=mdir)

    def test_double_apply_prevention(self):
        """Running migrations twice should not re-apply."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir) / "count_migrations"
            mdir.mkdir()
            (mdir / "001_create.sql").write_text("CREATE TABLE counter (n INTEGER);")
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}

            conn1 = get_db(config, migrations_dir=mdir)
            conn1.execute("INSERT INTO counter VALUES (1)")
            conn1.commit()
            conn1.close()

            # Second call should NOT re-run 001
            conn2 = get_db(config, migrations_dir=mdir)
            count = conn2.execute("SELECT COUNT(*) FROM counter").fetchone()[0]
            assert count == 1  # still just the one we inserted manually
            conn2.close()

    def test_partial_failure_stops_further_migrations(self):
        """If migration 2 fails, migration 3 should not be applied."""
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir) / "partial_migrations"
            mdir.mkdir()
            (mdir / "001_ok.sql").write_text("CREATE TABLE tbl1 (id INTEGER);")
            (mdir / "002_bad.sql").write_text("INVALID SQL;")
            (mdir / "003_ok.sql").write_text("CREATE TABLE tbl3 (id INTEGER);")
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            with pytest.raises(RuntimeError, match="Migration 002"):
                get_db(config, migrations_dir=mdir)

            # tbl1 should exist (from 001), tbl3 should NOT
            conn = sqlite3.connect(f"{tmpdir}/test.db")
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            assert "tbl1" in tables
            assert "tbl3" not in tables
            conn.close()


# ════════════════════════════════════════════════════════════════
# Migration Discovery
# ════════════════════════════════════════════════════════════════


class TestDiscoverMigrations:
    # Happy
    def test_discovers_sql_and_py(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir)
            (mdir / "001_first.sql").write_text("")
            (mdir / "002_second.py").write_text("")
            migrations = _discover_migrations(mdir)
            assert len(migrations) == 2
            assert migrations[0]["version"] == 1
            assert migrations[1]["version"] == 2

    def test_sorted_by_version(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir)
            (mdir / "003_third.sql").write_text("")
            (mdir / "001_first.sql").write_text("")
            (mdir / "002_second.sql").write_text("")
            migrations = _discover_migrations(mdir)
            assert [m["version"] for m in migrations] == [1, 2, 3]

    # Unhappy
    def test_ignores_non_migration_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir)
            (mdir / "001_first.sql").write_text("")
            (mdir / "README.md").write_text("")
            (mdir / "notes.txt").write_text("")
            migrations = _discover_migrations(mdir)
            assert len(migrations) == 1

    def test_ignores_files_without_version_prefix(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mdir = Path(tmpdir)
            (mdir / "abc_noversion.sql").write_text("")
            (mdir / "001_valid.sql").write_text("")
            migrations = _discover_migrations(mdir)
            assert len(migrations) == 1

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            migrations = _discover_migrations(Path(tmpdir))
            assert migrations == []


# ════════════════════════════════════════════════════════════════
# Schema Validation
# ════════════════════════════════════════════════════════════════


class TestSchemaValidation:
    def test_views_created(self):
        """Schema should create expected views."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
            views = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            ).fetchall()]
            assert "v_run_days" in views
            assert "v_all_training" in views
            conn.close()

    def test_indexes_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = {"sync": {"db_path": f"{tmpdir}/test.db"}}
            conn = get_db(config, migrations_dir=MIGRATIONS_DIR)
            indexes = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()]
            assert "idx_activities_date" in indexes
            assert "idx_activities_type" in indexes
            assert "idx_calibration_metric" in indexes
            conn.close()
