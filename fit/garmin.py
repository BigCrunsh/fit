"""Garmin Connect API client for syncing health metrics and activities."""

import logging
import time
from datetime import date, timedelta
from pathlib import Path

import garth
from garminconnect import Garmin

logger = logging.getLogger(__name__)


def _request_with_retry(func, max_retries=3, description="API call"):
    """Execute a Garmin API call with retry/backoff for transient errors.

    Handles: 429 (rate limit, wait 60s), 401 (auth expired), 5xx (exponential backoff).
    """
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as e:
            err_str = str(e)
            if "429" in err_str:
                wait = 60
                logger.warning("%s rate limited (429). Waiting %ds...", description, wait)
                time.sleep(wait)
                continue
            elif "401" in err_str:
                raise RuntimeError(
                    "Garmin auth expired. Re-authenticate with:\n"
                    "  python -c \"import garth; garth.login(input('Email: '), input('Password: ')); "
                    "garth.save('~/.fit/garmin-tokens/')\""
                ) from e
            elif any(code in err_str for code in ("500", "502", "503", "504")):
                wait = 2 ** attempt
                logger.warning("%s server error (attempt %d/%d). Retrying in %ds...",
                               description, attempt + 1, max_retries, wait)
                time.sleep(wait)
                continue
            else:
                if attempt < max_retries - 1:
                    logger.debug("%s failed: %s (attempt %d/%d)", description, e, attempt + 1, max_retries)
                    continue
                raise
    return None


def connect(token_dir: str) -> Garmin:
    """Connect to Garmin using saved garth tokens.

    Args:
        token_dir: Path to directory containing garth tokens.

    Returns:
        Authenticated Garmin API client.

    Raises:
        RuntimeError: If auth tokens are missing or expired, with re-auth instructions.
    """
    token_path = Path(token_dir).expanduser()
    try:
        garth.resume(str(token_path))
    except Exception as e:
        raise RuntimeError(
            f"Garmin auth failed: {e}\n"
            f"Token dir: {token_path}\n"
            f"Re-authenticate with:\n"
            f"  python -c \"import garth; garth.login(input('Email: '), input('Password: ')); "
            f"garth.save('{token_path}')\""
        ) from e
    api = Garmin()
    api.garth = garth.client

    # Load profile for display_name (needed by some API calls)
    try:
        profile = api.garth.connectapi("/userprofile-service/userprofile/social-profile")
        if isinstance(profile, dict):
            api.display_name = profile.get("displayName")
            api.full_name = profile.get("fullName")
    except Exception:
        try:
            profile = api.garth.profile
            if isinstance(profile, dict):
                api.display_name = profile.get("displayName")
                api.full_name = profile.get("fullName")
        except Exception:
            pass

    name = getattr(api, "display_name", None) or getattr(api, "full_name", None) or "unknown"
    logger.info("Authenticated as %s", name)
    return api


def fetch_health(api: Garmin, start: date, end: date) -> list[dict]:
    """Fetch daily health metrics for a date range.

    Returns list of dicts keyed by date, each containing all available health fields.
    """
    results = []
    current = start
    while current <= end:
        d = current.isoformat()
        metrics = _fetch_day_health(api, d)
        if metrics:
            metrics["date"] = d
            results.append(metrics)
        current += timedelta(days=1)

    logger.info("Fetched health metrics for %d days", len(results))
    return results


def _fetch_day_health(api: Garmin, d: str) -> dict | None:
    """Fetch all health data for a single day, combining multiple API calls."""
    m = {}
    errors = []

    # Daily stats (steps, calories, resting HR, stress, body battery)
    try:
        stats = api.get_stats(d)
        if stats:
            m.update({
                "total_steps": stats.get("totalSteps"),
                "total_distance_m": stats.get("totalDistanceMeters"),
                "total_calories": stats.get("totalKilocalories"),
                "active_calories": stats.get("activeKilocalories"),
                "resting_heart_rate": stats.get("restingHeartRate"),
                "max_heart_rate": stats.get("maxHeartRate"),
                "min_heart_rate": stats.get("minHeartRate"),
                "avg_stress_level": stats.get("averageStressLevel"),
                "max_stress_level": stats.get("maxStressLevel"),
                "body_battery_high": stats.get("bodyBatteryChargedValue"),
                "body_battery_low": stats.get("bodyBatteryDrainedValue"),
            })
    except Exception as e:
        errors.append(f"stats: {e}")

    # Sleep
    try:
        sleep = api.get_sleep_data(d)
        if sleep and sleep.get("dailySleepDTO"):
            s = sleep["dailySleepDTO"]
            deep = (s.get("deepSleepSeconds") or 0) / 3600
            light = (s.get("lightSleepSeconds") or 0) / 3600
            rem = (s.get("remSleepSeconds") or 0) / 3600
            awake = (s.get("awakeSleepSeconds") or 0) / 3600
            total = deep + light + rem
            if total > 0:
                m.update({
                    "sleep_duration_hours": round(total, 2),
                    "deep_sleep_hours": round(deep, 2),
                    "light_sleep_hours": round(light, 2),
                    "rem_sleep_hours": round(rem, 2),
                    "awake_hours": round(awake, 2),
                    "deep_sleep_pct": round(deep / total * 100, 1),
                })
    except Exception as e:
        errors.append(f"sleep: {e}")

    # HRV
    try:
        hrv = api.get_hrv_data(d)
        if hrv:
            summary = hrv.get("hrvSummary") or hrv
            if isinstance(summary, dict):
                m.update({
                    "hrv_weekly_avg": summary.get("weeklyAvg"),
                    "hrv_last_night": summary.get("lastNightAvg"),
                    "hrv_status": summary.get("status"),
                })
    except Exception as e:
        errors.append(f"hrv: {e}")

    # Training readiness
    try:
        tr = api.get_training_readiness(d)
        if tr:
            if isinstance(tr, list) and len(tr) > 0:
                tr = tr[0]
            if isinstance(tr, dict):
                m.update({
                    "training_readiness": tr.get("score"),
                    "readiness_level": tr.get("level"),
                })
    except Exception as e:
        errors.append(f"readiness: {e}")

    # Respiration
    try:
        resp = api.get_respiration_data(d)
        if resp:
            m["avg_respiration"] = resp.get("avgWakingRespirationValue")
    except Exception as e:
        errors.append(f"respiration: {e}")

    if errors:
        logger.debug("Health fetch warnings for %s: %s", d, errors)

    valid = {k: v for k, v in m.items() if v is not None}
    return valid if valid else None


def fetch_activities(api: Garmin, start: date, end: date) -> list[dict]:
    """Fetch all activities (running, cycling, etc.) for a date range.

    Returns normalized activity dicts ready for DB insertion.
    """
    s, e = start.isoformat(), end.isoformat()
    all_activities = []

    # Fetch all common activity types. Garmin API returns 400 for unsupported types,
    # which is caught by the try/except below.
    for activity_type in ("running", "cycling", "swimming", "hiking", "walking",
                          "fitness_equipment", "other"):
        try:
            acts = api.get_activities_by_date(s, e, activity_type)
            all_activities.extend(acts)
        except Exception as ex:
            logger.debug("No %s activities or error: %s", activity_type, ex)

    results = []
    seen_ids = set()
    for a in all_activities:
        aid = str(a.get("activityId", ""))
        if not aid or aid in seen_ids:
            continue
        seen_ids.add(aid)

        dist = (a.get("distance", 0) or 0) / 1000
        dur = (a.get("duration", 0) or 0) / 60
        pace = (dur / dist * 60) if dist > 0 else None

        atype_raw = a.get("activityType", {})
        atype = atype_raw.get("typeKey", "") if isinstance(atype_raw, dict) else str(atype_raw)

        # Determine subtype (manual vs auto-detected / Move IQ)
        subtype = "manual"
        if a.get("autoCalcCalories") is False or "move iq" in (a.get("activityName") or "").lower():
            subtype = "auto_detected"

        results.append({
            "id": aid,
            "date": (a.get("startTimeLocal") or "")[:10],
            "start_hour": int((a.get("startTimeLocal") or "00:00:00")[11:13]) if len(a.get("startTimeLocal") or "") > 13 else None,
            "type": atype or "other",
            "subtype": subtype,
            "name": a.get("activityName"),
            "distance_km": round(dist, 2) if dist else None,
            "duration_min": round(dur, 1) if dur else None,
            "pace_sec_per_km": round(pace) if pace else None,
            "avg_hr": a.get("averageHR"),
            "max_hr": a.get("maxHR"),
            "avg_cadence": a.get("averageRunningCadenceInStepsPerMinute"),
            "elevation_gain_m": a.get("elevationGain"),
            "calories": a.get("calories"),
            "vo2max": a.get("vO2MaxValue"),
            "aerobic_te": a.get("aerobicTrainingEffect"),
            "training_load": a.get("activityTrainingLoad"),
            "avg_stride_m": ((a.get("avgStrideLength") or 0) / 100) if a.get("avgStrideLength") else None,
            "avg_speed": a.get("averageSpeed"),
            "start_lat": a.get("startLatitude"),
            "start_lon": a.get("startLongitude"),
        })

    logger.info("Fetched %d activities", len(results))
    return results


def fetch_activity_splits(api: Garmin, activity_id: str) -> list[dict]:
    """Fetch per-km splits for an activity from the Garmin API.

    Returns list of split dicts with fields matching activity_splits schema:
        split_num, distance_km, time_sec, pace_sec_per_km, avg_hr, max_hr,
        avg_cadence, elevation_gain_m, elevation_loss_m, avg_speed_m_s,
        intensity_type, wkt_step_index.

    Includes all laps (km splits + interval segments). Only skips tiny
    trailing fragments (<50m) that Garmin sometimes appends.
    """
    data = _request_with_retry(
        lambda: api.get_activity_splits(str(activity_id)),
        description=f"Splits for {activity_id}",
    )
    if not data or "lapDTOs" not in data:
        return []

    splits = []
    km = 0
    for lap in data["lapDTOs"]:
        dist = lap.get("distance", 0) or 0
        dur = lap.get("duration", 0) or 0
        if dist < 50 or dur <= 0:
            continue
        km += 1
        speed = lap.get("averageSpeed", 0) or 0
        pace = round(1000 / speed) if speed > 0 else None
        splits.append({
            "split_num": km,
            "distance_km": round(dist / 1000, 2),
            "time_sec": round(dur),
            "pace_sec_per_km": pace,
            "avg_hr": round(lap["averageHR"]) if lap.get("averageHR") else None,
            "max_hr": round(lap["maxHR"]) if lap.get("maxHR") else None,
            "avg_cadence": round(lap["averageRunCadence"]) if lap.get("averageRunCadence") else None,
            "elevation_gain_m": lap.get("elevationGain"),
            "elevation_loss_m": lap.get("elevationLoss"),
            "avg_speed_m_s": round(speed, 3) if speed else None,
            "intensity_type": lap.get("intensityType"),
            "wkt_step_index": lap.get("wktStepIndex"),
        })

    logger.info("Fetched %d splits for activity %s", len(splits), activity_id)
    return splits


def fetch_spo2(api: Garmin, start: date, end: date) -> dict[str, float | None]:
    """Fetch SpO2 data for a date range.

    Returns dict mapping date string to avg SpO2 value (or None if unavailable).
    """
    results = {}
    current = start
    while current <= end:
        d = current.isoformat()
        try:
            data = api.get_spo2_data(d)
            if data and isinstance(data, dict):
                avg = data.get("averageSpO2")
                results[d] = avg
            else:
                results[d] = None
        except Exception:
            results[d] = None
        current += timedelta(days=1)

    non_null = sum(1 for v in results.values() if v is not None)
    logger.info("Fetched SpO2 for %d days (%d with data)", len(results), non_null)
    return results
