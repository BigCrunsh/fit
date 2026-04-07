"""Migration 009: Create planned_workouts table for Runna training plan integration."""


def run(conn):
    conn.execute("""
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
        )
    """)
    conn.execute(
        "CREATE INDEX idx_planned_date ON planned_workouts(date)"
    )
    conn.execute(
        "CREATE INDEX idx_planned_version "
        "ON planned_workouts(plan_version, status)"
    )
