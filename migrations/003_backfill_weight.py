"""Backfill weight data from Apple Health CSV export into body_comp."""

import csv
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CSV_PATH = Path.home() / "Downloads" / "apple_health_weight.csv"


def run(conn: sqlite3.Connection) -> None:
    csv_path = DEFAULT_CSV_PATH

    if not csv_path.exists():
        logger.warning("Weight CSV not found at %s — skipping backfill", csv_path)
        return

    count = 0
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Support common column names from Apple Health exports
            date = row.get("Date") or row.get("date") or row.get("startDate")
            weight = row.get("Weight(kg)") or row.get("weight_kg") or row.get("value")

            if not date or not weight:
                continue

            # Normalize date to YYYY-MM-DD (handle various formats)
            date_str = str(date)[:10]

            try:
                weight_kg = float(weight)
            except (ValueError, TypeError):
                continue

            conn.execute("""
                INSERT OR IGNORE INTO body_comp (date, weight_kg, source)
                VALUES (?, ?, 'fitdays')
            """, (date_str, weight_kg))
            count += 1

    logger.info("Backfilled %d weight measurements from %s", count, csv_path)
