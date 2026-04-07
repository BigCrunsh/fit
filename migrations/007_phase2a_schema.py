"""Phase 2a schema changes — Python migration for atomic table rebuilds.

Adds:
- goals.race_id (FK to race_calendar)
- race_calendar.activity_id FK enforcement (REFERENCES activities)
- activities.srpe
- weekly_agg: monotony, strain, cycling_km, cycling_min
- Links existing active goals to Berlin Marathon race_calendar entry
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def run(conn: sqlite3.Connection) -> None:
    # FK enforcement is disabled by the migration runner before BEGIN
    # to allow DROP TABLE on parent tables (goals referenced by training_phases).

    # ── 1. Rebuild goals table to add race_id with FK ──
    conn.execute("""
        CREATE TABLE goals_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            type            TEXT NOT NULL,
            target_time     TEXT,
            target_pace     REAL,
            target_value    REAL,
            target_unit     TEXT,
            target_date     DATE,
            active          BOOLEAN DEFAULT 1,
            race_id         INTEGER REFERENCES race_calendar(id),
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        INSERT INTO goals_new (id, name, type, target_time, target_pace,
            target_value, target_unit, target_date, active, race_id, created_at)
        SELECT id, name, type, target_time, target_pace,
            target_value, target_unit, target_date, active, NULL, created_at
        FROM goals
    """)
    conn.execute("DROP TABLE goals")
    conn.execute("ALTER TABLE goals_new RENAME TO goals")
    logger.info("Rebuilt goals table with race_id FK")

    # ── 2. Rebuild race_calendar to enforce activity_id FK ──
    # First, clean up orphan activity_id references that would violate FK
    conn.execute("""
        UPDATE race_calendar SET activity_id = NULL
        WHERE activity_id IS NOT NULL
        AND activity_id NOT IN (SELECT id FROM activities)
    """)

    conn.execute("""
        CREATE TABLE race_calendar_new (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            date            DATE NOT NULL,
            name            TEXT NOT NULL,
            organizer       TEXT,
            distance        TEXT NOT NULL,
            distance_km     REAL,
            status          TEXT DEFAULT 'planned',
            target_time     TEXT,
            result_time     TEXT,
            result_pace     REAL,
            activity_id     TEXT REFERENCES activities(id),
            garmin_time     TEXT,
            notes           TEXT,
            created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Copy with explicit column list to handle schema differences
    conn.execute("""
        INSERT INTO race_calendar_new (id, date, name, organizer, distance, distance_km,
            status, target_time, result_time, result_pace, activity_id, notes, created_at)
        SELECT id, date, name, organizer, distance, distance_km,
            status, target_time, result_time, result_pace, activity_id, notes, created_at
        FROM race_calendar
    """)
    # Copy garmin_time if it exists in the old table
    try:
        conn.execute("""
            UPDATE race_calendar_new SET garmin_time = (
                SELECT rc.garmin_time FROM race_calendar rc WHERE rc.id = race_calendar_new.id
            )
        """)
    except sqlite3.OperationalError:
        pass  # garmin_time column didn't exist in old table

    conn.execute("DROP TABLE race_calendar")
    conn.execute("ALTER TABLE race_calendar_new RENAME TO race_calendar")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_race_calendar_date ON race_calendar(date)")
    logger.info("Rebuilt race_calendar table with activity_id FK and garmin_time")

    # ── 3. Add srpe to activities ──
    try:
        conn.execute("ALTER TABLE activities ADD COLUMN srpe REAL")
        logger.info("Added srpe column to activities")
    except sqlite3.OperationalError:
        logger.debug("srpe column already exists")

    # ── 4. Add columns to weekly_agg ──
    for col in ("monotony REAL", "strain REAL", "cycling_km REAL", "cycling_min REAL"):
        try:
            conn.execute(f"ALTER TABLE weekly_agg ADD COLUMN {col}")
        except sqlite3.OperationalError:
            logger.debug("Column %s already exists", col.split()[0])
    logger.info("Added monotony, strain, cycling_km, cycling_min to weekly_agg")

    # ── 5. Link existing active goals to Berlin Marathon (task 2.2) ──
    conn.execute("""
        UPDATE goals SET race_id = (
            SELECT id FROM race_calendar
            WHERE name LIKE '%Berlin%' AND date >= '2026-01-01'
            LIMIT 1
        )
        WHERE active = 1 AND race_id IS NULL
    """)
    linked = conn.execute("SELECT changes()").fetchone()[0]
    if linked:
        logger.info("Linked %d active goals to Berlin Marathon race", linked)
