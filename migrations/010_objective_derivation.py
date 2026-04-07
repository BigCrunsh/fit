"""Add objective derivation columns to goals table.

- derivation_source: 'auto_daniels', 'auto_distance', 'auto_timeline', 'manual'
- auto_value: system-derived target (always computed, even if overridden)
- is_override: true when user manually set target_value different from auto_value
"""

import logging

logger = logging.getLogger(__name__)


def run(conn):
    # Add columns to goals
    for col in (
        "derivation_source TEXT DEFAULT 'manual'",
        "auto_value REAL",
        "is_override BOOLEAN DEFAULT 0",
    ):
        try:
            conn.execute(f"ALTER TABLE goals ADD COLUMN {col}")
        except Exception:
            logger.debug("Column %s already exists", col.split()[0])

    # Backfill: mark all existing goals as manually created
    conn.execute("UPDATE goals SET derivation_source = 'manual' WHERE derivation_source IS NULL")

    logger.info("Migration 010: added derivation columns to goals, backfilled as 'manual'")
