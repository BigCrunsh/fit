"""Sync pipeline: Garmin → normalize → weather → store."""

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from fit import garmin, weather

logger = logging.getLogger(__name__)


def run_sync(conn: sqlite3.Connection, config: dict, days: int = 7, full: bool = False) -> dict:
    """Run the full sync pipeline.

    Returns dict with counts per data type.
    """
    token_dir = config["sync"]["garmin_token_dir"]
    api = garmin.connect(token_dir)

    if full:
        start = date(2024, 1, 1)  # reasonable far-back date
    else:
        start = date.today() - timedelta(days=days)
    end = date.today()

    counts = {"health": 0, "activities": 0, "spo2": 0, "weather": 0}

    # 1. Health metrics
    health_rows = garmin.fetch_health(api, start, end)
    for h in health_rows:
        _upsert_health(conn, h)
    counts["health"] = len(health_rows)

    # 2. Activities
    activities = garmin.fetch_activities(api, start, end)
    for a in activities:
        _upsert_activity(conn, a)
    counts["activities"] = len(activities)

    # 3. SpO2
    spo2_data = garmin.fetch_spo2(api, start, end)
    for d_str, avg_spo2 in spo2_data.items():
        if avg_spo2 is not None:
            conn.execute(
                "UPDATE daily_health SET avg_spo2 = ? WHERE date = ?",
                (avg_spo2, d_str),
            )
            counts["spo2"] += 1

    # 4. Weather for activity dates
    lat = config.get("profile", {}).get("location", {}).get("lat")
    lon = config.get("profile", {}).get("location", {}).get("lon")
    if lat and lon:
        activity_dates = {a["date"] for a in activities if a.get("date")}
        for d_str in activity_dates:
            existing = conn.execute("SELECT 1 FROM weather WHERE date = ?", (d_str,)).fetchone()
            if existing and not full:
                continue
            d = date.fromisoformat(d_str)
            w = weather.fetch_daily_weather(d, float(lat), float(lon))
            if w:
                _upsert_weather(conn, w)
                counts["weather"] += 1

    conn.commit()
    logger.info("Sync complete: %s", counts)
    return counts


def _upsert_health(conn: sqlite3.Connection, h: dict) -> None:
    """Upsert a daily health row using INSERT ON CONFLICT."""
    conn.execute("""
        INSERT INTO daily_health (
            date, total_steps, total_distance_m, total_calories, active_calories,
            resting_heart_rate, max_heart_rate, min_heart_rate,
            avg_stress_level, max_stress_level, body_battery_high, body_battery_low,
            sleep_duration_hours, deep_sleep_hours, light_sleep_hours,
            rem_sleep_hours, awake_hours, deep_sleep_pct,
            training_readiness, readiness_level,
            hrv_weekly_avg, hrv_last_night, hrv_status,
            avg_respiration, avg_spo2
        ) VALUES (
            :date, :total_steps, :total_distance_m, :total_calories, :active_calories,
            :resting_heart_rate, :max_heart_rate, :min_heart_rate,
            :avg_stress_level, :max_stress_level, :body_battery_high, :body_battery_low,
            :sleep_duration_hours, :deep_sleep_hours, :light_sleep_hours,
            :rem_sleep_hours, :awake_hours, :deep_sleep_pct,
            :training_readiness, :readiness_level,
            :hrv_weekly_avg, :hrv_last_night, :hrv_status,
            :avg_respiration, :avg_spo2
        )
        ON CONFLICT(date) DO UPDATE SET
            total_steps = excluded.total_steps,
            total_distance_m = excluded.total_distance_m,
            total_calories = excluded.total_calories,
            active_calories = excluded.active_calories,
            resting_heart_rate = excluded.resting_heart_rate,
            max_heart_rate = excluded.max_heart_rate,
            min_heart_rate = excluded.min_heart_rate,
            avg_stress_level = excluded.avg_stress_level,
            max_stress_level = excluded.max_stress_level,
            body_battery_high = excluded.body_battery_high,
            body_battery_low = excluded.body_battery_low,
            sleep_duration_hours = excluded.sleep_duration_hours,
            deep_sleep_hours = excluded.deep_sleep_hours,
            light_sleep_hours = excluded.light_sleep_hours,
            rem_sleep_hours = excluded.rem_sleep_hours,
            awake_hours = excluded.awake_hours,
            deep_sleep_pct = excluded.deep_sleep_pct,
            training_readiness = excluded.training_readiness,
            readiness_level = excluded.readiness_level,
            hrv_weekly_avg = excluded.hrv_weekly_avg,
            hrv_last_night = excluded.hrv_last_night,
            hrv_status = excluded.hrv_status,
            avg_respiration = excluded.avg_respiration,
            avg_spo2 = COALESCE(excluded.avg_spo2, daily_health.avg_spo2)
    """, {
        "date": h.get("date"),
        "total_steps": h.get("total_steps"),
        "total_distance_m": h.get("total_distance_m"),
        "total_calories": h.get("total_calories"),
        "active_calories": h.get("active_calories"),
        "resting_heart_rate": h.get("resting_heart_rate"),
        "max_heart_rate": h.get("max_heart_rate"),
        "min_heart_rate": h.get("min_heart_rate"),
        "avg_stress_level": h.get("avg_stress_level"),
        "max_stress_level": h.get("max_stress_level"),
        "body_battery_high": h.get("body_battery_high"),
        "body_battery_low": h.get("body_battery_low"),
        "sleep_duration_hours": h.get("sleep_duration_hours"),
        "deep_sleep_hours": h.get("deep_sleep_hours"),
        "light_sleep_hours": h.get("light_sleep_hours"),
        "rem_sleep_hours": h.get("rem_sleep_hours"),
        "awake_hours": h.get("awake_hours"),
        "deep_sleep_pct": h.get("deep_sleep_pct"),
        "training_readiness": h.get("training_readiness"),
        "readiness_level": h.get("readiness_level"),
        "hrv_weekly_avg": h.get("hrv_weekly_avg"),
        "hrv_last_night": h.get("hrv_last_night"),
        "hrv_status": h.get("hrv_status"),
        "avg_respiration": h.get("avg_respiration"),
        "avg_spo2": h.get("avg_spo2"),
    })


def _upsert_activity(conn: sqlite3.Connection, a: dict) -> None:
    """Upsert an activity. Only raw Garmin fields updated on conflict — derived metrics preserved."""
    conn.execute("""
        INSERT INTO activities (
            id, date, type, subtype, name,
            distance_km, duration_min, pace_sec_per_km,
            avg_hr, max_hr, avg_cadence, elevation_gain_m,
            calories, vo2max, aerobic_te, training_load,
            avg_stride_m, avg_speed, start_lat, start_lon
        ) VALUES (
            :id, :date, :type, :subtype, :name,
            :distance_km, :duration_min, :pace_sec_per_km,
            :avg_hr, :max_hr, :avg_cadence, :elevation_gain_m,
            :calories, :vo2max, :aerobic_te, :training_load,
            :avg_stride_m, :avg_speed, :start_lat, :start_lon
        )
        ON CONFLICT(id) DO UPDATE SET
            date = excluded.date,
            type = excluded.type,
            name = excluded.name,
            distance_km = excluded.distance_km,
            duration_min = excluded.duration_min,
            pace_sec_per_km = excluded.pace_sec_per_km,
            avg_hr = excluded.avg_hr,
            max_hr = excluded.max_hr,
            avg_cadence = excluded.avg_cadence,
            elevation_gain_m = excluded.elevation_gain_m,
            calories = excluded.calories,
            vo2max = excluded.vo2max,
            aerobic_te = excluded.aerobic_te,
            training_load = excluded.training_load,
            avg_stride_m = excluded.avg_stride_m,
            avg_speed = excluded.avg_speed,
            start_lat = excluded.start_lat,
            start_lon = excluded.start_lon
    """, a)


def _upsert_weather(conn: sqlite3.Connection, w: dict) -> None:
    """Upsert a daily weather row."""
    conn.execute("""
        INSERT INTO weather (date, temp_c, temp_max_c, temp_min_c, humidity_pct,
                             wind_speed_kmh, precipitation_mm, conditions)
        VALUES (:date, :temp_c, :temp_max_c, :temp_min_c, :humidity_pct,
                :wind_speed_kmh, :precipitation_mm, :conditions)
        ON CONFLICT(date) DO UPDATE SET
            temp_c = excluded.temp_c,
            temp_max_c = excluded.temp_max_c,
            temp_min_c = excluded.temp_min_c,
            humidity_pct = excluded.humidity_pct,
            wind_speed_kmh = excluded.wind_speed_kmh,
            precipitation_mm = excluded.precipitation_mm,
            conditions = excluded.conditions
    """, w)
