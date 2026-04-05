"""Backfill historical check-ins collected via Claude Chat sessions."""

import logging
import sqlite3

logger = logging.getLogger(__name__)

CHECKINS = [
    {
        "date": "2026-03-22", "hydration": "Good", "alcohol": 1,
        "alcohol_detail": "1x 0.5L beer post-run", "legs": "Heavy",
        "eating": "OK", "water_liters": 1.5,
        "notes": "HM day, faded km 18",
    },
    {
        "date": "2026-03-25", "hydration": "OK", "alcohol": 0,
        "alcohol_detail": "1 alcohol-free beer", "legs": "Heavy",
        "eating": "Poor", "water_liters": 1.0,
        "notes": "Skipped breakfast, ran fasted",
    },
    {
        "date": "2026-03-27", "hydration": "OK", "alcohol": 2,
        "alcohol_detail": "2 beers", "legs": "Heavy",
        "eating": "Poor", "water_liters": 1.0, "energy": "Low",
        "notes": "3+ coffees, glute soreness fading",
    },
    {
        "date": "2026-03-30", "hydration": "OK", "alcohol": 0,
        "legs": "OK", "eating": "OK", "water_liters": 1.0,
        "energy": "Normal", "notes": "Rest day",
    },
    {
        "date": "2026-04-04", "hydration": "OK", "alcohol": 0,
        "legs": "Fresh", "notes": "No alcohol last days, recovered",
    },
]


def run(conn: sqlite3.Connection) -> None:
    count = 0
    for c in CHECKINS:
        conn.execute("""
            INSERT OR IGNORE INTO checkins (
                date, hydration, alcohol, alcohol_detail, legs,
                eating, water_liters, energy, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            c["date"], c.get("hydration"), c.get("alcohol", 0),
            c.get("alcohol_detail"), c.get("legs"),
            c.get("eating"), c.get("water_liters"),
            c.get("energy"), c.get("notes"),
        ))
        count += 1
    logger.info("Backfilled %d historical check-ins", count)
