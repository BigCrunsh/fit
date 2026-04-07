"""Download, parse, and analyze .fit files for per-km splits."""

import logging
import math
from pathlib import Path

logger = logging.getLogger(__name__)


def download_fit_file(api, activity_id, cache_dir):
    """Download .fit file from Garmin. Returns path or None.

    Uses the Garmin API download_activity method with retry.
    Files are cached locally so repeat calls are free.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{activity_id}.fit"
    if target.exists():
        return target
    try:
        from fit.garmin import _request_with_retry
        data = _request_with_retry(
            lambda: api.download_activity(
                activity_id,
                dl_fmt=api.ActivityDownloadFormat.ORIGINAL,
            ),
            description=f"Download .fit {activity_id}",
        )
        if data:
            target.write_bytes(data)
            return target
    except Exception as e:
        logger.warning("Failed to download .fit for %s: %s", activity_id, e)
    return None


def parse_fit_to_splits(fit_path, z2_ceiling_hr=134):
    """Parse .fit file into per-km splits. Returns list of split dicts.

    Each split dict contains:
        split_num, distance_km, time_sec, pace_sec_per_km, avg_hr,
        avg_cadence, elevation_gain_m, avg_speed_m_s,
        time_above_z2_ceiling_sec, start_distance_m, end_distance_m.

    Args:
        fit_path: Path to a .fit file.
        z2_ceiling_hr: HR ceiling for Z2 (used for time_above_z2_ceiling computation).

    Returns:
        List of split dicts, one per completed km.
    """
    try:
        from fitparse import FitFile
    except ImportError:
        logger.error("fitparse not installed. Install with: pip install 'fit[analysis]'")
        return []

    fit_path = Path(fit_path)
    if not fit_path.exists():
        logger.warning(".fit file not found: %s", fit_path)
        return []

    # Garmin downloads are often ZIP files containing the .fit file — extract if needed
    import zipfile
    if zipfile.is_zipfile(fit_path):
        try:
            with zipfile.ZipFile(fit_path) as zf:
                fit_names = [n for n in zf.namelist() if n.endswith(".fit")]
                if not fit_names:
                    logger.warning("ZIP contains no .fit file: %s", fit_path)
                    return []
                extracted = fit_path.parent / fit_names[0]
                if not extracted.exists():
                    zf.extract(fit_names[0], fit_path.parent)
                fit_path = extracted
        except zipfile.BadZipFile:
            logger.warning("Corrupt ZIP file: %s", fit_path)
            return []

    try:
        fitfile = FitFile(str(fit_path))
        records = list(fitfile.get_messages("record"))
    except Exception as e:
        logger.warning("Failed to parse .fit file %s: %s", fit_path, e)
        return []

    if not records:
        return []

    # Extract data points from records
    points = []
    for record in records:
        data = {field.name: field.value for field in record.fields}
        distance = data.get("distance")  # meters (cumulative)
        hr = data.get("heart_rate")
        cadence = data.get("cadence")
        altitude = data.get("enhanced_altitude") or data.get("altitude")
        timestamp = data.get("timestamp")
        speed = data.get("enhanced_speed") or data.get("speed")

        if distance is not None and timestamp is not None:
            points.append({
                "distance_m": float(distance),
                "hr": int(hr) if hr is not None else None,
                "cadence": int(cadence) if cadence is not None else None,
                "altitude_m": float(altitude) if altitude is not None else None,
                "timestamp": timestamp,
                "speed_m_s": float(speed) if speed is not None else None,
            })

    if len(points) < 2:
        return []

    # Sort by distance (should already be sorted, but safety)
    points.sort(key=lambda p: p["distance_m"])

    # Bin by km boundaries
    splits = []
    km_boundary = 1000.0  # next km mark in meters
    split_num = 1
    bin_start_idx = 0

    for i, pt in enumerate(points):
        if pt["distance_m"] >= km_boundary:
            # Collect all points in this km bin
            bin_points = points[bin_start_idx:i + 1]
            split = _compute_split(
                split_num, bin_points, z2_ceiling_hr,
                start_distance_m=km_boundary - 1000.0,
                end_distance_m=km_boundary,
            )
            if split:
                splits.append(split)
            split_num += 1
            km_boundary += 1000.0
            bin_start_idx = i

    return splits


def _compute_split(split_num, points, z2_ceiling_hr, start_distance_m, end_distance_m):
    """Compute metrics for a single km split from data points.

    Args:
        split_num: 1-based split number.
        points: List of data point dicts within this km.
        z2_ceiling_hr: HR ceiling for Z2.
        start_distance_m: Start distance of this split in meters.
        end_distance_m: End distance of this split in meters.

    Returns:
        Split dict or None if insufficient data.
    """
    if len(points) < 2:
        return None

    # Time
    first_ts = points[0]["timestamp"]
    last_ts = points[-1]["timestamp"]
    time_sec = (last_ts - first_ts).total_seconds()
    if time_sec <= 0:
        return None

    # Distance actually covered
    actual_dist_m = points[-1]["distance_m"] - points[0]["distance_m"]
    distance_km = actual_dist_m / 1000.0 if actual_dist_m > 0 else 1.0

    # Pace
    pace_sec_per_km = time_sec / distance_km if distance_km > 0 else None

    # Average HR
    hr_vals = [p["hr"] for p in points if p["hr"] is not None]
    avg_hr = sum(hr_vals) / len(hr_vals) if hr_vals else None

    # Average cadence (fitparse gives single-leg cadence for running, double it)
    cadence_vals = [p["cadence"] for p in points if p["cadence"] is not None]
    avg_cadence = sum(cadence_vals) / len(cadence_vals) if cadence_vals else None
    # Running cadence from FIT is single-leg; multiply by 2 for steps per minute
    if avg_cadence is not None:
        avg_cadence = avg_cadence * 2

    # Elevation gain
    altitudes = [p["altitude_m"] for p in points if p["altitude_m"] is not None]
    elevation_gain = 0.0
    if len(altitudes) >= 2:
        for j in range(1, len(altitudes)):
            diff = altitudes[j] - altitudes[j - 1]
            if diff > 0:
                elevation_gain += diff

    # Average speed
    speed_vals = [p["speed_m_s"] for p in points if p["speed_m_s"] is not None]
    avg_speed = sum(speed_vals) / len(speed_vals) if speed_vals else None

    # Time above Z2 ceiling: estimate seconds per data point interval
    time_above_z2 = 0.0
    if len(hr_vals) >= 2 and z2_ceiling_hr is not None:
        # Approximate: each point represents an interval of ~(total_time / n_points)
        interval_sec = time_sec / len(points)
        for p in points:
            if p["hr"] is not None and p["hr"] > z2_ceiling_hr:
                time_above_z2 += interval_sec

    return {
        "split_num": split_num,
        "distance_km": round(distance_km, 3),
        "time_sec": round(time_sec, 1),
        "pace_sec_per_km": round(pace_sec_per_km, 1) if pace_sec_per_km else None,
        "avg_hr": round(avg_hr, 1) if avg_hr is not None else None,
        "avg_cadence": round(avg_cadence, 1) if avg_cadence is not None else None,
        "elevation_gain_m": round(elevation_gain, 1),
        "avg_speed_m_s": round(avg_speed, 3) if avg_speed is not None else None,
        "time_above_z2_ceiling_sec": round(time_above_z2, 1),
        "start_distance_m": round(start_distance_m, 1),
        "end_distance_m": round(end_distance_m, 1),
    }


def compute_cardiac_drift(splits):
    """Compute rolling 1km cardiac drift. Returns drift info dict.

    Cardiac drift = increase in HR:pace ratio over the course of a run,
    indicating aerobic decoupling. Detected by comparing the first-half
    average ratio against a sliding 1km window.

    Returns dict with:
        drift_pct: overall drift percentage (first half vs second half)
        drift_onset_km: km where HR:pace ratio first exceeds 5% of baseline
        status: 'detected', 'none', or 'inconclusive_variable_pace'
        pace_cv_pct: coefficient of variation of pace across splits
    """
    if not splits or len(splits) < 4:
        return {"drift_pct": None, "drift_onset_km": None,
                "status": "insufficient_data", "pace_cv_pct": None}

    # Filter splits with valid HR and pace
    valid = [s for s in splits
             if s.get("avg_hr") and s.get("pace_sec_per_km") and s["pace_sec_per_km"] > 0]
    if len(valid) < 4:
        return {"drift_pct": None, "drift_onset_km": None,
                "status": "insufficient_data", "pace_cv_pct": None}

    # Check pace variability — if CV > 15%, flag as inconclusive
    pace_cv = compute_pace_variability(valid)
    if pace_cv is not None and pace_cv > 15.0:
        return {"drift_pct": None, "drift_onset_km": None,
                "status": "inconclusive_variable_pace", "pace_cv_pct": round(pace_cv, 1)}

    # Compute HR:pace ratio for each split (higher ratio = more cardiac cost per km)
    ratios = []
    for s in valid:
        ratio = s["avg_hr"] / s["pace_sec_per_km"]
        ratios.append(ratio)

    # First half baseline
    half = len(ratios) // 2
    first_half_avg = sum(ratios[:half]) / half

    if first_half_avg <= 0:
        return {"drift_pct": None, "drift_onset_km": None,
                "status": "insufficient_data", "pace_cv_pct": pace_cv}

    # Find drift onset: slide through splits looking for >5% deviation
    drift_onset_km = None
    for i in range(half, len(ratios)):
        deviation_pct = (ratios[i] - first_half_avg) / first_half_avg * 100
        if deviation_pct > 5.0:
            drift_onset_km = valid[i]["split_num"]
            break

    # Overall drift: first half vs second half
    second_half_avg = sum(ratios[half:]) / len(ratios[half:])
    drift_pct = (second_half_avg - first_half_avg) / first_half_avg * 100

    status = "detected" if drift_pct > 5.0 else "none"

    return {
        "drift_pct": round(drift_pct, 1),
        "drift_onset_km": drift_onset_km,
        "status": status,
        "pace_cv_pct": round(pace_cv, 1) if pace_cv is not None else None,
    }


def compute_pace_variability(splits):
    """Compute pace coefficient of variation (CV) across splits.

    CV = (std_dev / mean) * 100, expressed as a percentage.
    Lower CV means more even pacing.

    Args:
        splits: List of split dicts with pace_sec_per_km.

    Returns:
        CV as a percentage, or None if insufficient data.
    """
    paces = [s["pace_sec_per_km"] for s in splits if s.get("pace_sec_per_km")]
    if len(paces) < 2:
        return None
    mean_pace = sum(paces) / len(paces)
    if mean_pace <= 0:
        return None
    variance = sum((p - mean_pace) ** 2 for p in paces) / len(paces)
    return math.sqrt(variance) / mean_pace * 100


def compute_cadence_drift(splits):
    """Compute cadence drift over splits.

    Compares the average cadence of the first 3km to the last 3km.
    Negative drift = cadence dropping (fatigue signal).

    Args:
        splits: List of split dicts with avg_cadence.

    Returns:
        Dict with first_3km_avg, last_3km_avg, drift_pct, and status.
        Returns None if insufficient data.
    """
    valid = [s for s in splits if s.get("avg_cadence") is not None]
    if len(valid) < 6:
        # Need at least 6 splits (3 for each end)
        return None

    first_3 = valid[:3]
    last_3 = valid[-3:]

    first_avg = sum(s["avg_cadence"] for s in first_3) / 3
    last_avg = sum(s["avg_cadence"] for s in last_3) / 3

    if first_avg <= 0:
        return None

    drift_pct = (last_avg - first_avg) / first_avg * 100

    status = "stable"
    if drift_pct < -3.0:
        status = "declining"
    elif drift_pct > 3.0:
        status = "increasing"

    return {
        "first_3km_avg": round(first_avg, 1),
        "last_3km_avg": round(last_avg, 1),
        "drift_pct": round(drift_pct, 1),
        "status": status,
    }


def compute_split_zone_time(splits, z2_ceiling_hr=134):
    """Compute time_above_z2_ceiling_sec for each split.

    Args:
        splits: List of split dicts with avg_hr and time_sec.
        z2_ceiling_hr: Z2 ceiling HR (default 134).

    Returns:
        List of split dicts with time_above_z2_ceiling_sec added.
    """
    result = []
    for s in splits:
        s_copy = dict(s) if not isinstance(s, dict) else s.copy()
        avg_hr = s_copy.get("avg_hr")
        time_sec = s_copy.get("time_sec", 0) or 0
        if avg_hr is not None and avg_hr > z2_ceiling_hr:
            s_copy["time_above_z2_ceiling_sec"] = time_sec
        else:
            s_copy["time_above_z2_ceiling_sec"] = 0
        result.append(s_copy)
    return result


def flag_heat_affected(activity):
    """Flag if a run was heat-affected: >25C or >70% humidity.

    These conditions significantly affect cardiac output and HR response,
    making zone-based analysis less reliable.

    Args:
        activity: Dict with temp_at_start_c and humidity_at_start_pct.

    Returns:
        True if heat-affected, False otherwise.
    """
    temp = activity.get("temp_at_start_c")
    humidity = activity.get("humidity_at_start_pct")
    return (
        (temp is not None and temp > 25)
        or (humidity is not None and humidity > 70)
    )


def process_splits_for_activity(conn, api, activity_id, config, cache_dir=None):
    """Full pipeline: download .fit, parse splits, store in DB.

    Args:
        conn: SQLite connection.
        api: Garmin API client.
        activity_id: Activity ID string.
        config: Config dict (for z2 ceiling).
        cache_dir: Optional override for .fit file cache directory.

    Returns:
        Number of splits stored, or 0 on failure.
    """
    if cache_dir is None:
        from pathlib import Path
        cache_dir = Path(config["sync"]["db_path"]).expanduser().parent / "fit_files"

    # Check if already processed
    existing = conn.execute(
        "SELECT splits_status FROM activities WHERE id = ?", (activity_id,)
    ).fetchone()
    if existing and existing["splits_status"] == "done":
        return 0

    # Download
    fit_path = download_fit_file(api, activity_id, cache_dir)
    if not fit_path:
        conn.execute(
            "UPDATE activities SET splits_status = 'download_failed' WHERE id = ?",
            (activity_id,),
        )
        return 0

    # Parse
    z2_ceiling = config.get("analysis", {}).get("easy_hr_ceiling", 134)
    splits = parse_fit_to_splits(fit_path, z2_ceiling_hr=z2_ceiling)
    if not splits:
        conn.execute(
            "UPDATE activities SET splits_status = 'parse_failed', fit_file_path = ? WHERE id = ?",
            (str(fit_path), activity_id),
        )
        return 0

    # Store splits
    for s in splits:
        conn.execute("""
            INSERT INTO activity_splits (
                activity_id, split_num, distance_km, time_sec, pace_sec_per_km,
                avg_hr, avg_cadence, elevation_gain_m, avg_speed_m_s,
                time_above_z2_ceiling_sec, start_distance_m, end_distance_m
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(activity_id, split_num) DO UPDATE SET
                distance_km = excluded.distance_km,
                time_sec = excluded.time_sec,
                pace_sec_per_km = excluded.pace_sec_per_km,
                avg_hr = excluded.avg_hr,
                avg_cadence = excluded.avg_cadence,
                elevation_gain_m = excluded.elevation_gain_m,
                avg_speed_m_s = excluded.avg_speed_m_s,
                time_above_z2_ceiling_sec = excluded.time_above_z2_ceiling_sec,
                start_distance_m = excluded.start_distance_m,
                end_distance_m = excluded.end_distance_m
        """, (
            activity_id, s["split_num"], s["distance_km"], s["time_sec"],
            s["pace_sec_per_km"], s["avg_hr"], s["avg_cadence"],
            s["elevation_gain_m"], s["avg_speed_m_s"],
            s["time_above_z2_ceiling_sec"], s["start_distance_m"],
            s["end_distance_m"],
        ))

    conn.execute(
        "UPDATE activities SET splits_status = 'done', fit_file_path = ? WHERE id = ?",
        (str(fit_path), activity_id),
    )
    conn.commit()
    logger.info("Stored %d splits for activity %s", len(splits), activity_id)
    return len(splits)
