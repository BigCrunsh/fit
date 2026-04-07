"""Sync pipeline: Garmin → normalize → weather → store."""

import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn

from fit import garmin, weather
from fit.analysis import enrich_activity, compute_weekly_agg
from fit.calibration import get_active_calibration, extract_lthr_from_race

logger = logging.getLogger(__name__)

# Suppress console logging during progress bars (file logging continues)
_console_suppressed = False


def run_sync(conn: sqlite3.Connection, config: dict, days: int = 7, full: bool = False,
             download_splits: bool = False) -> dict:
    """Run the full sync pipeline.

    Args:
        download_splits: If True (or config sync.download_fit_files), download .fit files
            and compute per-km splits for running activities.

    Returns dict with counts per data type.
    """
    token_dir = config["sync"]["garmin_token_dir"]
    api = garmin.connect(token_dir)

    if full:
        start = date(2024, 1, 1)  # reasonable far-back date
    else:
        start = date.today() - timedelta(days=days)
    end = date.today()

    counts = {"health": 0, "activities": 0, "spo2": 0, "weather": 0, "enriched": 0, "weekly_agg": 0}
    warnings = []

    # Get LTHR calibration for zone computation
    lthr_cal = get_active_calibration(conn, "lthr")
    lthr = int(lthr_cal["value"]) if lthr_cal else None

    total_days = (end - start).days + 1

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        transient=True,
    ) as progress:

        # 1. Health metrics
        task_h = progress.add_task("Health", total=total_days)
        health_rows = garmin.fetch_health(api, start, end)
        for h in health_rows:
            _upsert_health(conn, h)
            progress.advance(task_h)
        progress.update(task_h, completed=total_days)
        counts["health"] = len(health_rows)

        # 2. Activities
        task_a = progress.add_task("Activities", total=None)
        activities = garmin.fetch_activities(api, start, end)
        progress.update(task_a, total=len(activities), completed=0)

        # 3. Enrich new activities
        for i, a in enumerate(activities):
            existing = conn.execute("SELECT hr_zone FROM activities WHERE id = ?", (a["id"],)).fetchone()
            if existing and existing["hr_zone"] is not None:
                _upsert_activity(conn, a)
            else:
                enriched = enrich_activity(a, config, lthr=lthr)
                _upsert_enriched_activity(conn, enriched)
                counts["enriched"] += 1

                if enriched.get("run_type") == "race":
                    candidate_lthr = extract_lthr_from_race(enriched)
                    if candidate_lthr:
                        from fit.calibration import add_calibration
                        add_calibration(
                            conn, "lthr", candidate_lthr, "race_extract", "medium",
                            date.fromisoformat(enriched["date"]),
                            source_activity_id=enriched["id"],
                            notes=f"Auto-extracted from {enriched.get('name')} ({enriched.get('distance_km', '?')}km)",
                        )
                        logger.info("LTHR auto-saved from race %s: %d bpm", enriched.get("name"), candidate_lthr)
            progress.advance(task_a)
        counts["activities"] = len(activities)

        # 4. SpO2
        task_s = progress.add_task("SpO2", total=total_days)
        spo2_data = garmin.fetch_spo2(api, start, end)
        for d_str, avg_spo2 in spo2_data.items():
            if avg_spo2 is not None:
                conn.execute("UPDATE daily_health SET avg_spo2 = ? WHERE date = ?", (avg_spo2, d_str))
                counts["spo2"] += 1
            progress.advance(task_s)

        # 5. Weather
        lat = config.get("profile", {}).get("location", {}).get("lat")
        lon = config.get("profile", {}).get("location", {}).get("lon")
        if lat and lon:
            activity_dates = {a["date"] for a in activities if a.get("date")}
            task_w = progress.add_task("Weather", total=len(activity_dates) + len(activities))
            for d_str in activity_dates:
                existing = conn.execute("SELECT 1 FROM weather WHERE date = ?", (d_str,)).fetchone()
                if not existing or full:
                    d = date.fromisoformat(d_str)
                    w = weather.fetch_daily_weather(d, float(lat), float(lon))
                    if w:
                        _upsert_weather(conn, w)
                        counts["weather"] += 1
                progress.advance(task_w)

            for a in activities:
                if a.get("start_lat") and a.get("start_lon") and a.get("date"):
                    existing_hw = conn.execute(
                        "SELECT temp_at_start_c FROM activities WHERE id = ? AND temp_at_start_c IS NOT NULL",
                        (a["id"],)
                    ).fetchone()
                    if not existing_hw or full:
                        try:
                            d = date.fromisoformat(a["date"])
                            hour = a.get("start_hour") or 8
                            hw = weather.fetch_hourly_weather(d, hour, float(a["start_lat"]), float(a["start_lon"]))
                            if hw:
                                conn.execute(
                                    "UPDATE activities SET temp_at_start_c = ?, humidity_at_start_pct = ? WHERE id = ?",
                                    (hw["temp_at_start_c"], hw["humidity_at_start_pct"], a["id"]),
                                )
                        except Exception as e:
                            logger.debug("Hourly weather failed for %s: %s", a["id"], e)
                progress.advance(task_w)

        # 6. Weekly aggregation
        affected_weeks = _get_affected_weeks(activities, start, end)
        task_wk = progress.add_task("Weekly Agg", total=len(affected_weeks))
        for week_str in affected_weeks:
            agg = compute_weekly_agg(conn, week_str)
            _upsert_weekly_agg(conn, agg)
            counts["weekly_agg"] += 1
            progress.advance(task_wk)

    conn.commit()

    # 7. Match activities to race calendar
    _match_race_calendar(conn)

    # 8. Auto-import weight/body comp CSV
    weight_csv = config.get("sync", {}).get("weight_csv_path", "")
    if weight_csv:
        csv_path = Path(weight_csv).expanduser()
        if not csv_path.exists():
            warnings.append(
                f"FitDays CSV not found at {csv_path}. "
                f"Download from FitDays app → Export → CSV, save to {csv_path}"
            )
        else:
            # Check staleness (warn if file >14 days old)
            import os
            mtime = date.fromtimestamp(os.path.getmtime(csv_path))
            days_old = (date.today() - mtime).days
            if days_old > 14:
                warnings.append(
                    f"FitDays CSV is {days_old} days old. "
                    f"Re-export from FitDays app to get latest body comp data."
                )
            try:
                _auto_import_weight(conn, csv_path)
            except Exception as e:
                logger.debug("Weight auto-import failed: %s", e)
    else:
        warnings.append(
            "No weight CSV configured. To auto-import FitDays body comp data, "
            "add sync.weight_csv_path to config.local.yaml (e.g., ~/.fit/fitdays.csv)"
        )

    # 8a. Compute sRPE (retroactively join checkin RPE to same-day activities)
    try:
        from fit.analysis import compute_srpe
        srpe_count = compute_srpe(conn)
        if srpe_count:
            counts["srpe"] = srpe_count
    except Exception as e:
        logger.debug("sRPE computation skipped: %s", e)

    # 8b. Sync planned workouts from Garmin Calendar (Runna)
    try:
        from fit.plan import sync_planned_workouts
        plan_count = sync_planned_workouts(api, conn)
        if plan_count:
            counts["planned_workouts"] = plan_count
    except Exception as e:
        logger.debug("Plan sync skipped: %s", e)

    # 8c. Auto-compute correlations + run alerts
    try:
        from fit.correlations import compute_all_correlations
        compute_all_correlations(conn)
    except Exception as e:
        logger.debug("Correlations skipped: %s", e)

    try:
        from fit.alerts import run_alerts
        alerts = run_alerts(conn, config)
        if alerts:
            counts["alerts"] = len(alerts)
    except Exception as e:
        logger.debug("Alerts skipped: %s", e)

    # 9. Download .fit files and compute splits (if enabled)
    should_download_splits = download_splits or config.get("sync", {}).get("download_fit_files", False)
    if should_download_splits:
        try:
            import time as _time
            from fit.fit_file import process_splits_for_activity

            max_downloads = config.get("sync", {}).get("max_fit_downloads", 20)
            running_ids = [a["id"] for a in activities if a.get("type") == "running"]
            # Only process activities without splits yet
            to_process = []
            for aid in running_ids:
                row = conn.execute(
                    "SELECT splits_status FROM activities WHERE id = ?", (aid,)
                ).fetchone()
                if not row or row["splits_status"] != "done":
                    to_process.append(aid)
            to_process = to_process[:max_downloads]

            splits_count = 0
            for i, aid in enumerate(to_process):
                n = process_splits_for_activity(conn, api, aid, config)
                splits_count += (1 if n > 0 else 0)
                if i < len(to_process) - 1:
                    _time.sleep(2)  # Rate control
            counts["splits"] = splits_count
        except Exception as e:
            logger.debug("Splits processing skipped: %s", e)

    if warnings:
        counts["warnings"] = warnings
    logger.info("Sync complete: %s", counts)
    return counts


def _match_race_calendar(conn: sqlite3.Connection) -> None:
    """Match race_calendar entries to activities by date. Tag matched activities as run_type='race'."""
    unmatched = conn.execute("""
        SELECT rc.id, rc.date, rc.distance_km FROM race_calendar rc
        WHERE rc.status = 'completed' AND rc.activity_id IS NULL
    """).fetchall()
    for rc in unmatched:
        activity = conn.execute("""
            SELECT id, distance_km, duration_min FROM activities
            WHERE date = ? AND type = 'running' ORDER BY distance_km DESC LIMIT 1
        """, (rc["date"],)).fetchone()
        if activity:
            dur = activity["duration_min"] or 0
            garmin_time = f"{int(dur // 60)}:{int(dur % 60):02d}:{int((dur * 60) % 60):02d}"
            pace = (dur * 60) / activity["distance_km"] if activity["distance_km"] else None
            conn.execute("""UPDATE race_calendar SET activity_id = ?, garmin_time = ?, result_pace = ?
                            WHERE id = ?""",
                         (activity["id"], garmin_time, pace, rc["id"]))
            conn.execute("UPDATE activities SET run_type = 'race' WHERE id = ?", (activity["id"],))
            logger.info("Race matched: %s → activity %s", rc["date"], activity["id"])
    conn.commit()


def _safe_float(value) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        result = float(value)
        return result if result == result else None  # NaN check
    except (ValueError, TypeError):
        return None


def _auto_import_weight(conn: sqlite3.Connection, csv_path: Path) -> None:
    """Auto-import new weight measurements from configured CSV path."""
    import csv
    import hashlib

    if not csv_path.exists():
        logger.debug("Weight CSV not found at %s", csv_path)
        return

    file_hash = hashlib.md5(csv_path.read_bytes()).hexdigest()

    # Check import_log for duplicate
    existing = conn.execute("SELECT 1 FROM import_log WHERE file_hash = ?", (file_hash,)).fetchone()
    if existing:
        logger.debug("Weight CSV already imported (hash match)")
        return

    count = 0
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        # Validate header
        headers = reader.fieldnames or []
        # Case-insensitive column name matching
        header_lower = {h.lower(): h for h in headers}
        date_col = next((header_lower[k] for k in header_lower
                         if k in ("date", "startdate")), None)
        weight_col = next((header_lower[k] for k in header_lower
                           if "weight" in k or k == "value"), None)
        # Body composition columns (task 4.8)
        body_fat_col = next((header_lower[k] for k in header_lower
                             if "body" in k and "fat" in k), None)
        muscle_col = next((header_lower[k] for k in header_lower
                           if "muscle" in k and "mass" in k), None)
        visceral_col = next((header_lower[k] for k in header_lower
                             if "visceral" in k), None)

        if not date_col or not weight_col:
            logger.warning("Weight CSV has unexpected columns: %s. Expected Date + Weight column.", headers)
            return

        for row in reader:
            d = str(row.get(date_col, ""))[:10]
            try:
                w = float(row.get(weight_col, ""))
            except (ValueError, TypeError):
                continue

            # Parse body composition fields
            body_fat = _safe_float(row.get(body_fat_col)) if body_fat_col else None
            muscle_mass = _safe_float(row.get(muscle_col)) if muscle_col else None
            visceral_fat = _safe_float(row.get(visceral_col)) if visceral_col else None

            # Only insert if date not already in body_comp
            existing_w = conn.execute("SELECT 1 FROM body_comp WHERE date = ?", (d,)).fetchone()
            if not existing_w:
                conn.execute("""
                    INSERT INTO body_comp (date, weight_kg, body_fat_pct, muscle_mass_kg,
                                           visceral_fat, source)
                    VALUES (?, ?, ?, ?, ?, 'fitdays')
                """, (d, w, body_fat, muscle_mass, visceral_fat))
                count += 1

    # Log the import
    total_rows = count  # approximation
    conn.execute("""
        INSERT INTO import_log (filename, file_hash, row_count, rows_imported, source_type)
        VALUES (?, ?, ?, ?, 'weight_csv')
    """, (str(csv_path), file_hash, total_rows, count))

    # Auto-update weight calibration
    if count > 0:
        latest = conn.execute("SELECT date, weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
        if latest:
            from fit.calibration import add_calibration
            add_calibration(conn, "weight", latest["weight_kg"], "scale", "high",
                            date.fromisoformat(latest["date"]))
            logger.info("Weight calibration auto-updated: %s kg on %s", latest["weight_kg"], latest["date"])

    conn.commit()
    logger.info("Auto-imported %d new weight measurements from %s", count, csv_path)


def enrich_existing_activities(conn: sqlite3.Connection, config: dict) -> int:
    """Enrich all activities that have NULL hr_zone (e.g., from backfill migration).

    Returns count of enriched activities.
    """
    lthr_cal = get_active_calibration(conn, "lthr")
    lthr = int(lthr_cal["value"]) if lthr_cal else None

    rows = conn.execute("""
        SELECT id, date, type, subtype, name, distance_km, duration_min,
               pace_sec_per_km, avg_hr, max_hr, avg_cadence, elevation_gain_m,
               calories, vo2max, aerobic_te, training_load, avg_stride_m,
               avg_speed, start_lat, start_lon
        FROM activities WHERE hr_zone IS NULL
    """).fetchall()

    count = 0
    for row in rows:
        a = dict(row)
        enriched = enrich_activity(a, config, lthr=lthr)
        conn.execute("""
            UPDATE activities SET
                hr_zone_maxhr = ?, hr_zone_lthr = ?, hr_zone = ?,
                effort_class = ?, speed_per_bpm = ?, speed_per_bpm_z2 = ?,
                run_type = ?, max_hr_used = ?, lthr_used = ?
            WHERE id = ?
        """, (
            enriched.get("hr_zone_maxhr"), enriched.get("hr_zone_lthr"),
            enriched.get("hr_zone"), enriched.get("effort_class"),
            enriched.get("speed_per_bpm"), enriched.get("speed_per_bpm_z2"),
            enriched.get("run_type"), enriched.get("max_hr_used"),
            enriched.get("lthr_used"), enriched["id"],
        ))
        count += 1

    conn.commit()
    logger.info("Enriched %d existing activities", count)
    return count


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


def _upsert_enriched_activity(conn: sqlite3.Connection, a: dict) -> None:
    """Insert a new enriched activity with all derived fields."""
    conn.execute("""
        INSERT INTO activities (
            id, date, type, subtype, name,
            distance_km, duration_min, pace_sec_per_km,
            avg_hr, max_hr, avg_cadence, elevation_gain_m,
            calories, vo2max, aerobic_te, training_load,
            avg_stride_m, avg_speed, start_lat, start_lon,
            hr_zone_maxhr, hr_zone_lthr, hr_zone,
            speed_per_bpm, speed_per_bpm_z2,
            effort_class, run_type, max_hr_used, lthr_used
        ) VALUES (
            :id, :date, :type, :subtype, :name,
            :distance_km, :duration_min, :pace_sec_per_km,
            :avg_hr, :max_hr, :avg_cadence, :elevation_gain_m,
            :calories, :vo2max, :aerobic_te, :training_load,
            :avg_stride_m, :avg_speed, :start_lat, :start_lon,
            :hr_zone_maxhr, :hr_zone_lthr, :hr_zone,
            :speed_per_bpm, :speed_per_bpm_z2,
            :effort_class, :run_type, :max_hr_used, :lthr_used
        )
        ON CONFLICT(id) DO UPDATE SET
            date = excluded.date, type = excluded.type, name = excluded.name,
            distance_km = excluded.distance_km, duration_min = excluded.duration_min,
            pace_sec_per_km = excluded.pace_sec_per_km,
            avg_hr = excluded.avg_hr, max_hr = excluded.max_hr,
            avg_cadence = excluded.avg_cadence, elevation_gain_m = excluded.elevation_gain_m,
            calories = excluded.calories, vo2max = excluded.vo2max,
            aerobic_te = excluded.aerobic_te, training_load = excluded.training_load,
            avg_stride_m = excluded.avg_stride_m, avg_speed = excluded.avg_speed,
            start_lat = excluded.start_lat, start_lon = excluded.start_lon
    """, a)


def _upsert_weekly_agg(conn: sqlite3.Connection, agg: dict) -> None:
    """Upsert a weekly_agg row."""
    cols = list(agg.keys())
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "week")
    conn.execute(f"""
        INSERT INTO weekly_agg ({', '.join(cols)})
        VALUES ({placeholders})
        ON CONFLICT(week) DO UPDATE SET {updates}
    """, agg)


def _get_affected_weeks(activities: list[dict], start: date, end: date) -> set[str]:
    """Get ISO week strings for all dates in the sync range."""
    weeks = set()
    current = start
    while current <= end:
        iso = current.isocalendar()
        weeks.add(f"{iso.year}-W{iso.week:02d}")
        current += timedelta(days=1)
    return weeks


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
