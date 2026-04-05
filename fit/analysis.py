"""Fitness analysis: HR zones, efficiency, run types, weekly aggregation."""

import logging
import sqlite3
from datetime import date, timedelta

logger = logging.getLogger(__name__)


# ── HR Zone Computation (parallel models) ──


def compute_hr_zones(avg_hr: int | None, config: dict, lthr: int | None = None) -> dict:
    """Compute zones from BOTH max HR and LTHR models in parallel.

    Returns dict with hr_zone_maxhr, hr_zone_lthr (None if no LTHR),
    hr_zone (alias for preferred model), and effort_class.
    """
    if avg_hr is None:
        return {"hr_zone_maxhr": None, "hr_zone_lthr": None, "hr_zone": None, "effort_class": None}

    # Max HR model (always computed)
    zones_maxhr = config["profile"].get("zones_max_hr", {})
    zone_maxhr = _classify_zone(avg_hr, zones_maxhr)

    # LTHR model (computed only if LTHR calibration exists)
    zone_lthr = None
    if lthr:
        zones_lthr_pct = config["profile"].get("zones_lthr", {})
        zone_lthr = _classify_zone_lthr(avg_hr, lthr, zones_lthr_pct)

    # Primary zone = preferred model
    preferred = config["profile"].get("zone_model", "max_hr")
    primary = zone_lthr if (preferred == "lthr" and zone_lthr) else zone_maxhr

    return {
        "hr_zone_maxhr": zone_maxhr,
        "hr_zone_lthr": zone_lthr,
        "hr_zone": primary,
        "effort_class": compute_effort_class(primary),
    }


def _classify_zone(avg_hr: int, zones: dict) -> str:
    """Classify HR into zone using absolute boundaries."""
    for zone_name in ("z5", "z4", "z3", "z2", "z1"):
        bounds = zones.get(zone_name)
        if bounds and avg_hr >= bounds[0]:
            return zone_name.upper()
    return "Z1"


def _classify_zone_lthr(avg_hr: int, lthr: int, zones_pct: dict) -> str:
    """Classify HR into zone using LTHR percentage model."""
    pct = (avg_hr / lthr) * 100
    for zone_name in ("z5_pct", "z4_pct", "z3_pct", "z2_pct", "z1_pct"):
        bounds = zones_pct.get(zone_name)
        if bounds and pct >= bounds[0]:
            return zone_name.replace("_pct", "").upper()
    return "Z1"


def compute_effort_class(zone: str | None) -> str | None:
    """Map zone to 5-level effort class."""
    if zone is None:
        return None
    return {
        "Z1": "Recovery",
        "Z2": "Easy",
        "Z3": "Moderate",
        "Z4": "Hard",
        "Z5": "Very Hard",
    }.get(zone, "Easy")


# ── Speed Per BPM (aerobic efficiency) ──


def compute_speed_per_bpm(distance_km: float | None, duration_min: float | None,
                          avg_hr: int | None) -> float | None:
    """Compute speed per heartbeat: (m/min) / avg_hr. Higher = more efficient."""
    if not all((distance_km, duration_min, avg_hr)) or duration_min <= 0 or avg_hr <= 0:
        return None
    meters_per_min = (distance_km * 1000) / duration_min
    return round(meters_per_min / avg_hr, 4)


def compute_speed_per_bpm_z2(distance_km: float | None, duration_min: float | None,
                              avg_hr: int | None, z2_range: list[int] | None = None) -> float | None:
    """Compute speed per BPM only for Z2 HR range (pure aerobic trending)."""
    if z2_range is None:
        z2_range = [115, 134]
    if avg_hr is None or avg_hr < z2_range[0] or avg_hr > z2_range[1]:
        return None
    return compute_speed_per_bpm(distance_km, duration_min, avg_hr)


# ── Run Type Classification ──


def classify_run_type(activity: dict, config: dict = None, recent_long_run_avg: float = None) -> str | None:
    """Auto-classify a running activity into a run type.

    Types: easy, long, tempo, intervals, recovery, race, progression.
    Returns None for non-running activities.
    """
    if activity.get("type") != "running":
        return None

    name = (activity.get("name") or "").lower()
    distance = activity.get("distance_km") or 0
    zone = activity.get("hr_zone")

    # Race detection (highest priority)
    race_keywords = ("race", "marathon", "hm ", "half marathon", "10k", "5k", "parkrun")
    if any(kw in name for kw in race_keywords):
        return "race"

    # Progression detection
    if "prog" in name or "negative split" in name:
        return "progression"

    # Intervals/fartlek detection
    if any(kw in name for kw in ("interval", "fartlek", "speed", "repeat")):
        return "intervals"

    # Tempo detection
    if "tempo" in name or (zone in ("Z3", "Z4") and distance >= 6):
        return "tempo"

    # Long run detection
    long_threshold = max(15, (recent_long_run_avg or 15) * 0.75)
    if distance >= long_threshold:
        return "long"

    # Recovery detection (very easy, short)
    if zone == "Z1" and distance < 6:
        return "recovery"

    # Default: easy
    return "easy"


# ── Activity Enrichment ──


def enrich_activity(activity: dict, config: dict, lthr: int | None = None,
                    recent_long_run_avg: float = None) -> dict:
    """Apply all derived metrics to an activity dict.

    Adds: hr_zone_maxhr, hr_zone_lthr, hr_zone, effort_class,
    speed_per_bpm, speed_per_bpm_z2, run_type, max_hr_used, lthr_used.
    """
    zones = compute_hr_zones(activity.get("avg_hr"), config, lthr=lthr)
    activity.update(zones)

    z2_range = config.get("analysis", {}).get("speed_per_bpm_hr_range", [115, 134])
    activity["speed_per_bpm"] = compute_speed_per_bpm(
        activity.get("distance_km"), activity.get("duration_min"), activity.get("avg_hr")
    )
    activity["speed_per_bpm_z2"] = compute_speed_per_bpm_z2(
        activity.get("distance_km"), activity.get("duration_min"), activity.get("avg_hr"), z2_range
    )
    activity["run_type"] = classify_run_type(activity, config, recent_long_run_avg)
    activity["max_hr_used"] = config["profile"]["max_hr"]
    activity["lthr_used"] = lthr

    return activity


# ── Weekly Aggregation ──


def compute_weekly_agg(conn: sqlite3.Connection, week_str: str) -> dict:
    """Compute weekly aggregation for a given ISO week (e.g., '2026-W14').

    Returns dict with all weekly_agg fields.
    """
    # Parse week to get date range
    year = int(week_str[:4])
    week_num = int(week_str.split("W")[1])
    monday = date.fromisocalendar(year, week_num, 1)
    sunday = monday + timedelta(days=6)

    runs = conn.execute("""
        SELECT distance_km, duration_min, pace_sec_per_km, avg_hr, avg_cadence,
               training_load, hr_zone, run_type
        FROM activities
        WHERE type = 'running' AND date BETWEEN ? AND ?
    """, (monday.isoformat(), sunday.isoformat())).fetchall()

    cross = conn.execute("""
        SELECT duration_min, training_load
        FROM activities
        WHERE type != 'running' AND date BETWEEN ? AND ?
    """, (monday.isoformat(), sunday.isoformat())).fetchall()

    health = conn.execute("""
        SELECT training_readiness, sleep_duration_hours, resting_heart_rate, hrv_last_night
        FROM daily_health
        WHERE date BETWEEN ? AND ?
    """, (monday.isoformat(), sunday.isoformat())).fetchall()

    weight = conn.execute("""
        SELECT AVG(weight_kg) as avg_weight FROM body_comp
        WHERE date BETWEEN ? AND ?
    """, (monday.isoformat(), sunday.isoformat())).fetchone()

    # Running metrics
    run_km = sum(r["distance_km"] or 0 for r in runs)
    run_count = len(runs)
    longest = max((r["distance_km"] or 0 for r in runs), default=0)
    cadences = [r["avg_cadence"] for r in runs if r["avg_cadence"]]
    paces = [r["pace_sec_per_km"] for r in runs if r["pace_sec_per_km"]]
    hrs = [r["avg_hr"] for r in runs if r["avg_hr"]]
    easy_count = sum(1 for r in runs if r["run_type"] in ("easy", "recovery"))
    quality_count = sum(1 for r in runs if r["run_type"] in ("tempo", "intervals", "race"))

    # Zone time distribution (using duration_min per activity, assigned to its zone)
    zone_mins = {"Z1": 0, "Z2": 0, "Z3": 0, "Z4": 0, "Z5": 0}
    for r in runs:
        z = r["hr_zone"]
        dur = r["duration_min"] or 0
        if z in zone_mins:
            zone_mins[z] += dur
    total_zone_time = sum(zone_mins.values())
    z12_pct = ((zone_mins["Z1"] + zone_mins["Z2"]) / total_zone_time * 100) if total_zone_time > 0 else None
    z45_pct = ((zone_mins["Z4"] + zone_mins["Z5"]) / total_zone_time * 100) if total_zone_time > 0 else None

    # Cross-training
    cross_count = len(cross)
    cross_min = sum(c["duration_min"] or 0 for c in cross)

    # Combined load
    all_loads = [r["training_load"] or 0 for r in runs] + [c["training_load"] or 0 for c in cross]
    total_load = sum(all_loads)

    # ACWR (this week / avg of previous 4 weeks)
    acwr = _compute_acwr(conn, week_str, total_load)

    # Training days
    activity_dates = conn.execute("""
        SELECT DISTINCT date FROM activities WHERE date BETWEEN ? AND ?
    """, (monday.isoformat(), sunday.isoformat())).fetchall()
    training_days = len(activity_dates)

    # Consistency streak
    streak = _compute_streak(conn, week_str, run_count)

    # Recovery
    readiness_vals = [h["training_readiness"] for h in health if h["training_readiness"]]
    sleep_vals = [h["sleep_duration_hours"] for h in health if h["sleep_duration_hours"]]
    rhr_vals = [h["resting_heart_rate"] for h in health if h["resting_heart_rate"]]
    hrv_vals = [h["hrv_last_night"] for h in health if h["hrv_last_night"]]

    return {
        "week": week_str,
        "run_count": run_count,
        "run_km": round(run_km, 1),
        "run_avg_pace": round(sum(paces) / len(paces)) if paces else None,
        "run_avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
        "longest_run_km": round(longest, 1) if longest > 0 else None,
        "run_avg_cadence": round(sum(cadences) / len(cadences), 1) if cadences else None,
        "easy_run_count": easy_count,
        "quality_session_count": quality_count,
        "cross_train_count": cross_count,
        "cross_train_min": round(cross_min, 1),
        "total_load": round(total_load, 1),
        "total_activities": run_count + cross_count,
        "acwr": acwr,
        "avg_readiness": round(sum(readiness_vals) / len(readiness_vals), 1) if readiness_vals else None,
        "avg_sleep": round(sum(sleep_vals) / len(sleep_vals), 1) if sleep_vals else None,
        "avg_rhr": round(sum(rhr_vals) / len(rhr_vals), 1) if rhr_vals else None,
        "avg_hrv": round(sum(hrv_vals) / len(hrv_vals), 1) if hrv_vals else None,
        "weight_avg": round(weight["avg_weight"], 1) if weight and weight["avg_weight"] else None,
        "z1_min": round(zone_mins["Z1"], 1),
        "z2_min": round(zone_mins["Z2"], 1),
        "z3_min": round(zone_mins["Z3"], 1),
        "z4_min": round(zone_mins["Z4"], 1),
        "z5_min": round(zone_mins["Z5"], 1),
        "z12_pct": round(z12_pct, 1) if z12_pct is not None else None,
        "z45_pct": round(z45_pct, 1) if z45_pct is not None else None,
        "training_days": training_days,
        "consecutive_weeks_3plus": streak,
    }


def predict_marathon_time(races: list[dict], vo2max: float | None = None) -> dict:
    """Predict marathon time using Riegel formula and VDOT tables.

    Args:
        races: List of race dicts with keys: distance_km, time_seconds, date.
        vo2max: Current VO2max estimate from Garmin.

    Returns:
        Dict with predictions: riegel (from each race), vdot (from VO2max),
        and a recommended range.
    """
    marathon_km = 42.195
    predictions = {}

    # Riegel formula: T2 = T1 * (D2/D1)^1.06
    riegel_preds = []
    for race in races:
        d1 = race.get("distance_km", 0)
        t1 = race.get("time_seconds", 0)
        if d1 > 0 and t1 > 0 and d1 < marathon_km:
            t2 = t1 * (marathon_km / d1) ** 1.06
            riegel_preds.append({
                "from_race": race.get("name", f"{d1:.1f}km"),
                "from_date": race.get("date"),
                "predicted_seconds": round(t2),
                "predicted_pace_sec_km": round(t2 / marathon_km),
            })
    predictions["riegel"] = riegel_preds

    # VDOT approximation from VO2max
    # Simplified: marathon time ≈ (VO2max-based) using Daniels' approximation
    # At VO2max 49: ~3:55 marathon, 50: ~3:48, 51: ~3:42, 53: ~3:30
    if vo2max and vo2max > 30:
        # Rough linear approximation in the 45-55 range
        base_seconds = 16800  # ~4:40 at VO2max 40
        seconds_per_unit = -300  # each VO2max point saves ~5 min
        vdot_seconds = max(7200, base_seconds + (vo2max - 40) * seconds_per_unit)
        predictions["vdot"] = {
            "vo2max": vo2max,
            "predicted_seconds": round(vdot_seconds),
            "predicted_pace_sec_km": round(vdot_seconds / marathon_km),
        }
    else:
        predictions["vdot"] = None

    return predictions


def _compute_acwr(conn: sqlite3.Connection, week_str: str, current_load: float) -> float | None:
    """Compute Acute:Chronic Workload Ratio.

    ACWR = this week's load / average of previous 4 weeks' loads.
    """
    year = int(week_str[:4])
    week_num = int(week_str.split("W")[1])

    prev_loads = []
    for i in range(1, 5):
        prev_week = week_num - i
        prev_year = year
        if prev_week <= 0:
            prev_year -= 1
            prev_week += 52
        pw_str = f"{prev_year}-W{prev_week:02d}"
        row = conn.execute("SELECT total_load FROM weekly_agg WHERE week = ?", (pw_str,)).fetchone()
        if row and row["total_load"] is not None:
            prev_loads.append(row["total_load"])

    if len(prev_loads) < 2:
        return None

    chronic = sum(prev_loads) / len(prev_loads)
    if chronic <= 0:
        return None

    return round(current_load / chronic, 2)


def _compute_streak(conn: sqlite3.Connection, week_str: str, current_run_count: int) -> int:
    """Compute consecutive weeks with 3+ runs ending at current week."""
    if current_run_count < 3:
        return 0

    streak = 1
    year = int(week_str[:4])
    week_num = int(week_str.split("W")[1])

    for i in range(1, 52):
        prev_week = week_num - i
        prev_year = year
        if prev_week <= 0:
            prev_year -= 1
            prev_week += 52
        pw_str = f"{prev_year}-W{prev_week:02d}"
        row = conn.execute("SELECT run_count FROM weekly_agg WHERE week = ?", (pw_str,)).fetchone()
        if row and row["run_count"] and row["run_count"] >= 3:
            streak += 1
        else:
            break

    return streak
