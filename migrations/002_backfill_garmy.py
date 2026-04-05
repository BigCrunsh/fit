"""Backfill from legacy ~/.garmy/health.db into fitness.db."""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

GARMY_DB_PATH = Path.home() / ".garmy" / "health.db"


def run(conn: sqlite3.Connection) -> None:
    if not GARMY_DB_PATH.exists():
        logger.warning("Legacy garmy DB not found at %s — skipping backfill", GARMY_DB_PATH)
        return

    garmy = sqlite3.connect(str(GARMY_DB_PATH))
    garmy.row_factory = sqlite3.Row

    _backfill_health(conn, garmy)
    _backfill_activities(conn, garmy)

    garmy.close()


def _backfill_health(conn: sqlite3.Connection, garmy: sqlite3.Connection) -> None:
    rows = garmy.execute("SELECT * FROM daily_health_metrics").fetchall()
    count = 0
    for r in rows:
        conn.execute("""
            INSERT OR IGNORE INTO daily_health (
                date, total_steps, total_distance_m, total_calories, active_calories,
                resting_heart_rate, max_heart_rate, min_heart_rate,
                avg_stress_level, max_stress_level,
                body_battery_high, body_battery_low,
                sleep_duration_hours, deep_sleep_hours, light_sleep_hours,
                rem_sleep_hours, awake_hours, deep_sleep_pct,
                training_readiness, readiness_level,
                hrv_weekly_avg, hrv_last_night, hrv_status,
                avg_respiration, avg_spo2
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["metric_date"], r["total_steps"], r["total_distance_meters"],
            r["total_calories"], r["active_calories"],
            r["resting_heart_rate"], r["max_heart_rate"], r["min_heart_rate"],
            r["avg_stress_level"], r["max_stress_level"],
            r["body_battery_high"], r["body_battery_low"],
            r["sleep_duration_hours"], r["deep_sleep_hours"], r["light_sleep_hours"],
            r["rem_sleep_hours"], r["awake_hours"], r["deep_sleep_percentage"],
            r["training_readiness_score"], r["training_readiness_level"],
            r["hrv_weekly_avg"], r["hrv_last_night_avg"], r["hrv_status"],
            r["average_respiration"], r["average_spo2"],
        ))
        count += 1
    logger.info("Backfilled %d daily_health rows from garmy", count)


def _backfill_activities(conn: sqlite3.Connection, garmy: sqlite3.Connection) -> None:
    rows = garmy.execute("SELECT * FROM run_activities").fetchall()
    count = 0
    for r in rows:
        activity_type = r["activity_type"] if r["activity_type"] else "running"
        conn.execute("""
            INSERT OR IGNORE INTO activities (
                id, date, type, subtype, name,
                distance_km, duration_min, pace_sec_per_km,
                avg_hr, max_hr, avg_cadence, elevation_gain_m,
                calories, vo2max, aerobic_te, training_load,
                avg_stride_m, avg_speed, start_lat, start_lon
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            r["activity_id"], r["activity_date"], activity_type, "imported", r["activity_name"],
            r["distance_km"], r["duration_min"], r["pace_sec_per_km"],
            r["avg_hr"], r["max_hr"], r["avg_cadence"], r["elevation_gain_m"],
            r["calories"], r["vo2max"], r["aerobic_te"], r["training_load"],
            r["avg_stride_m"], r["avg_speed"], r["start_latitude"], r["start_longitude"],
        ))
        count += 1
    logger.info("Backfilled %d activities from garmy", count)
