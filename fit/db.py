"""Database connection and transaction-safe migration runner."""

import importlib.util
import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def get_db(config: dict, migrations_dir: Path | None = None) -> sqlite3.Connection:
    """Get a database connection and run any pending migrations.

    Args:
        config: Merged config dict (needs sync.db_path).
        migrations_dir: Directory containing migration files. Defaults to ./migrations/.

    Returns:
        SQLite connection with row_factory set to sqlite3.Row.
    """
    db_path = Path(config["sync"]["db_path"]).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    logger.info("Connected to database: %s", db_path)

    _ensure_schema_version_table(conn)

    if migrations_dir is None:
        migrations_dir = Path.cwd() / "migrations"

    if migrations_dir.exists():
        _run_pending_migrations(conn, migrations_dir)

    return conn


def _ensure_schema_version_table(conn: sqlite3.Connection) -> None:
    """Create the schema_version tracking table if it doesn't exist."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def _get_applied_versions(conn: sqlite3.Connection) -> set[int]:
    """Get the set of already-applied migration version numbers."""
    cursor = conn.execute("SELECT version FROM schema_version")
    return {row[0] for row in cursor.fetchall()}


def _discover_migrations(migrations_dir: Path) -> list[dict[str, Any]]:
    """Discover migration files sorted by version number.

    Supports NNN_name.sql and NNN_name.py files.
    """
    migrations = []
    for path in sorted(migrations_dir.iterdir()):
        if path.suffix not in (".sql", ".py"):
            continue
        name = path.stem
        parts = name.split("_", 1)
        if not parts[0].isdigit():
            continue
        version = int(parts[0])
        migrations.append({
            "version": version,
            "name": name,
            "path": path,
            "type": path.suffix,
        })
    return sorted(migrations, key=lambda m: m["version"])


def _run_pending_migrations(conn: sqlite3.Connection, migrations_dir: Path) -> None:
    """Run any migrations not yet applied, each in its own transaction."""
    applied = _get_applied_versions(conn)
    migrations = _discover_migrations(migrations_dir)
    pending = [m for m in migrations if m["version"] not in applied]

    if not pending:
        logger.debug("No pending migrations")
        return

    logger.info("%d pending migration(s)", len(pending))

    for migration in pending:
        logger.info("Applying migration %03d: %s", migration["version"], migration["name"])
        try:
            if migration["type"] == ".sql":
                # executescript() handles DDL (CREATE TABLE/INDEX/VIEW) correctly
                # but auto-commits. We run it, then record the version separately.
                sql = migration["path"].read_text()
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO schema_version (version, name) VALUES (?, ?)",
                    (migration["version"], migration["name"]),
                )
                conn.commit()
            elif migration["type"] == ".py":
                # Python migrations run inside an explicit transaction
                conn.execute("BEGIN")
                _run_python_migration(conn, migration["path"])
                conn.execute(
                    "INSERT INTO schema_version (version, name) VALUES (?, ?)",
                    (migration["version"], migration["name"]),
                )
                conn.commit()

            logger.info("Migration %03d applied successfully", migration["version"])

        except Exception as e:
            conn.rollback()
            logger.error("Migration %03d FAILED: %s — rolled back", migration["version"], e)
            raise RuntimeError(
                f"Migration {migration['version']:03d} ({migration['name']}) failed: {e}"
            ) from e


def _run_python_migration(conn: sqlite3.Connection, path: Path) -> None:
    """Import and run a Python migration's run(conn) function."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    if not hasattr(module, "run"):
        raise AttributeError(f"Python migration {path.name} must define a run(conn) function")

    module.run(conn)
