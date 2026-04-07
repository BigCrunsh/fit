"""Fitness profile: 4-dimension model with VDOT tracking, trends, and achievability."""

import logging
import math
import sqlite3
from datetime import date

logger = logging.getLogger(__name__)

# ── Daniels VDOT Formula ──
# From Daniels' Running Formula: VDOT computed from oxygen cost and VO2max fraction.
# No lookup table needed — the formula is the source of truth.


def get_fitness_profile(conn: sqlite3.Connection) -> dict:
    """Compute the 4-dimension fitness profile from current data.

    Returns dict with:
        aerobic: {current_value, trend, rate_per_month, source, data_points}
        threshold: {current_value, trend, rate_per_month, source, data_points}
        economy: {current_value, trend, rate_per_month, source, data_points}
        resilience: {current_value, trend, rate_per_month, source, data_points}
        effective_vdot: float (blended from races + Garmin)
        garmin_vo2max: float (latest from Garmin)
        race_vdot: float (latest from race results)
        race_vdot_date: str
    """
    profile = {
        "aerobic": _compute_aerobic(conn),
        "threshold": _compute_threshold(conn),
        "economy": _compute_economy(conn),
        "resilience": _compute_resilience(conn),
    }

    # VDOT computation
    garmin_vo2 = _get_garmin_vo2max(conn)
    race_vdot, race_vdot_date = _get_race_vdot(conn)
    effective = _compute_effective_vdot(garmin_vo2, race_vdot, race_vdot_date)

    profile["garmin_vo2max"] = garmin_vo2
    profile["race_vdot"] = race_vdot
    profile["race_vdot_date"] = race_vdot_date
    profile["effective_vdot"] = effective

    return profile


# ── Dimension Computations ──


def _compute_aerobic(conn: sqlite3.Connection) -> dict:
    """Aerobic capacity: VO2max trend + VDOT from races."""
    rows = conn.execute("""
        SELECT date, vo2max FROM activities
        WHERE vo2max IS NOT NULL AND date >= date('now', '-56 days')
        ORDER BY date
    """).fetchall()

    if not rows:
        return _empty_dimension("No VO2max data in last 8 weeks")

    values = [(r["date"], r["vo2max"]) for r in rows]
    current = values[-1][1]
    trend, rate = _compute_trend(values)

    return {
        "current_value": current,
        "trend": trend,
        "rate_per_month": rate,
        "unit": "ml/kg/min",
        "source": "Garmin VO2max",
        "data_points": len(values),
    }


def _compute_threshold(conn: sqlite3.Connection) -> dict:
    """Threshold: Z2 pace at HR ceiling (speed at controlled effort)."""
    rows = conn.execute("""
        SELECT date, speed_per_bpm_z2 FROM activities
        WHERE type IN ('running','track_running','trail_running')
        AND speed_per_bpm_z2 IS NOT NULL
        AND date >= date('now', '-56 days')
        ORDER BY date
    """).fetchall()

    if len(rows) < 3:
        return _empty_dimension("Need 3+ Z2 runs in last 8 weeks")

    values = [(r["date"], r["speed_per_bpm_z2"]) for r in rows]
    current = values[-1][1]
    trend, rate = _compute_trend(values)

    return {
        "current_value": round(current, 4),
        "trend": trend,
        "rate_per_month": round(rate, 4) if rate else None,
        "unit": "m/min/bpm (Z2)",
        "source": "Z2 speed per BPM",
        "data_points": len(values),
    }


def _compute_economy(conn: sqlite3.Connection) -> dict:
    """Economy: overall speed per BPM (running efficiency)."""
    rows = conn.execute("""
        SELECT date, speed_per_bpm FROM activities
        WHERE type IN ('running','track_running','trail_running')
        AND speed_per_bpm IS NOT NULL
        AND date >= date('now', '-56 days')
        ORDER BY date
    """).fetchall()

    if len(rows) < 3:
        return _empty_dimension("Need 3+ runs with HR data in last 8 weeks")

    values = [(r["date"], r["speed_per_bpm"]) for r in rows]
    current = values[-1][1]
    trend, rate = _compute_trend(values)

    return {
        "current_value": round(current, 4),
        "trend": trend,
        "rate_per_month": round(rate, 4) if rate else None,
        "unit": "m/min/bpm",
        "source": "Speed per BPM (all runs)",
        "data_points": len(values),
    }


def _compute_resilience(conn: sqlite3.Connection) -> dict:
    """Resilience: drift onset km from split analysis (how far before HR decouples)."""
    # Check if split data exists
    splits_runs = conn.execute("""
        SELECT a.id, a.date, a.distance_km FROM activities a
        WHERE a.type IN ('running','track_running','trail_running')
        AND a.splits_status = 'done'
        AND a.distance_km >= 8
        AND a.date >= date('now', '-56 days')
        ORDER BY a.date
    """).fetchall()

    if not splits_runs:
        return _empty_dimension(
            "Enable .fit file download: fit sync --splits. "
            "Need long runs (8km+) with split data for resilience tracking."
        )

    # Compute drift onset for each run
    drift_points = []
    for run in splits_runs:
        splits = conn.execute("""
            SELECT split_num, avg_hr, pace_sec_per_km FROM activity_splits
            WHERE activity_id = ? ORDER BY split_num
        """, (run["id"],)).fetchall()

        if len(splits) < 4:
            continue

        from fit.fit_file import compute_cardiac_drift
        drift = compute_cardiac_drift([dict(s) for s in splits])
        if drift and drift.get("status") == "detected" and drift.get("drift_onset_km"):
            drift_points.append((run["date"], float(drift["drift_onset_km"])))
        elif drift and drift.get("status") == "none":
            # No drift = resilience is at least the full distance
            drift_points.append((run["date"], float(run["distance_km"])))

    if not drift_points:
        return _empty_dimension("No drift data from recent long runs")

    current = drift_points[-1][1]
    trend, rate = _compute_trend(drift_points) if len(drift_points) >= 2 else ("insufficient_data", None)

    return {
        "current_value": round(current, 1),
        "trend": trend,
        "rate_per_month": round(rate, 1) if rate else None,
        "unit": "km (drift onset)",
        "source": "Cardiac drift analysis",
        "data_points": len(drift_points),
    }


# ── VDOT Computation ──


def _oxygen_cost(velocity_m_per_min: float) -> float:
    """Oxygen cost of running at a given velocity (ml/kg/min).

    Daniels' formula: VO2 = -4.60 + 0.182258v + 0.000104v²
    """
    v = velocity_m_per_min
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def _vo2max_fraction(time_min: float) -> float:
    """Fraction of VO2max sustainable for a given duration.

    Daniels' formula: %VO2max = 0.8 + 0.1894393e^(-0.012778t) + 0.2989558e^(-0.1932605t)
    """
    t = time_min
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)


def compute_vdot_from_race(distance_km: float, time_seconds: int) -> float | None:
    """Compute VDOT from a race result using Daniels' oxygen cost formula.

    VDOT = oxygen_cost(velocity) / vo2max_fraction(time)
    This is the exact formula from Daniels' Running Formula, not a table lookup.
    """
    if distance_km <= 0 or time_seconds <= 0:
        return None

    time_min = time_seconds / 60.0
    distance_m = distance_km * 1000.0
    velocity = distance_m / time_min  # meters per minute

    vo2 = _oxygen_cost(velocity)
    fraction = _vo2max_fraction(time_min)

    if fraction <= 0:
        return None

    vdot = vo2 / fraction
    return round(vdot, 1)


def vdot_to_race_time(vdot: float, distance_km: float) -> int | None:
    """Predict race time in seconds for a given VDOT and distance.

    Uses binary search: find the time where compute_vdot_from_race(distance, time) = vdot.
    """
    if vdot <= 0 or distance_km <= 0:
        return None

    # Binary search for time that produces the target VDOT
    # VDOT decreases as time increases (slower = lower VDOT)
    lo = 60 * 5       # 5 minutes minimum
    hi = 60 * 60 * 7  # 7 hours maximum

    for _ in range(50):  # max iterations
        mid = (lo + hi) // 2
        computed = compute_vdot_from_race(distance_km, mid)
        if computed is None:
            return None
        if abs(computed - vdot) < 0.1:
            return mid
        if computed > vdot:
            lo = mid  # too fast (high VDOT) → need more time
        else:
            hi = mid  # too slow (low VDOT) → need less time

    return (lo + hi) // 2


def inverse_vdot(target_time_seconds: int, distance_km: float) -> float | None:
    """Inverse Daniels: what VDOT do you need for a target time at a given distance?

    This is simply compute_vdot_from_race — the VDOT that produces this performance.
    E.g., marathon 4:00:00 → VDOT needed to sustain that pace for that duration.
    """
    return compute_vdot_from_race(distance_km, target_time_seconds)


def _get_garmin_vo2max(conn: sqlite3.Connection) -> float | None:
    """Latest Garmin VO2max estimate."""
    row = conn.execute(
        "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return row["vo2max"] if row else None


def _get_race_vdot(conn: sqlite3.Connection) -> tuple[float | None, str | None]:
    """Best VDOT from recent race results (last 6 months).

    Uses the BEST (highest) VDOT from recent races, not the most recent.
    This avoids a single bad race (wind, illness, pacing) dragging down
    the effective VDOT. The best recent race is the most representative
    of actual fitness potential.
    """
    races = conn.execute("""
        SELECT date, distance_km, result_time FROM race_calendar
        WHERE status = 'completed' AND result_time IS NOT NULL AND distance_km IS NOT NULL
        AND date >= date('now', '-180 days')
        ORDER BY date DESC
    """).fetchall()

    if not races:
        return None, None

    def _parse_time(t):
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0

    # Compute VDOT for each recent race, pick the best
    best_vdot = None
    best_date = None
    for r in races:
        time_sec = _parse_time(r["result_time"])
        vdot = compute_vdot_from_race(r["distance_km"], time_sec)
        if vdot and (best_vdot is None or vdot > best_vdot):
            best_vdot = vdot
            best_date = r["date"]

    return best_vdot, best_date


def _compute_effective_vdot(garmin_vo2: float | None, race_vdot: float | None,
                             race_date: str | None) -> float | None:
    """Compute effective VDOT from race results and Garmin VO2max.

    Race VDOT is ALWAYS preferred over Garmin VO2max because:
    - Race VDOT comes from actual performance (you ran that time)
    - Garmin VO2max is estimated from wrist HR during short GPS runs
    - Garmin consistently overestimates by 5-10 VDOT points

    When race data exists (<6 months), use race VDOT directly.
    Fall back to Garmin only when no recent races exist, and even then
    apply a discount factor (Garmin reads high).
    """
    if race_vdot and race_date:
        days_ago = (date.today() - date.fromisoformat(race_date)).days
        if days_ago <= 180:  # 6 months
            return race_vdot

    # No recent race — use Garmin with discount (tends to read ~5 VDOT high)
    if garmin_vo2:
        return round(garmin_vo2 - 5, 1)

    return None


# ── Trend Computation ──


def _compute_trend(values: list[tuple[str, float]]) -> tuple[str, float | None]:
    """Compute trend direction and rate from time-series data.

    Args:
        values: List of (date_string, value) pairs, sorted by date.

    Returns:
        (trend, rate_per_month) where trend is 'improving'/'declining'/'flat'/'insufficient_data'
    """
    if len(values) < 3:
        return "insufficient_data", None

    # Convert dates to numeric (days from first)
    base_date = date.fromisoformat(values[0][0])
    xs = [(date.fromisoformat(d) - base_date).days for d, _ in values]
    ys = [v for _, v in values]

    # Simple linear regression
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return "flat", 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom

    # Rate per month (30 days)
    rate_per_month = slope * 30

    # Mean value for relative threshold
    mean_y = sum_y / n
    if mean_y == 0:
        return "flat", 0.0

    # Threshold: >2% change per month = trending, otherwise flat
    relative_rate = abs(rate_per_month / mean_y) * 100
    if relative_rate < 2:
        return "flat", round(rate_per_month, 4)
    elif rate_per_month > 0:
        return "improving", round(rate_per_month, 4)
    else:
        return "declining", round(rate_per_month, 4)


def _empty_dimension(message: str) -> dict:
    """Return an empty dimension with an actionable message."""
    return {
        "current_value": None,
        "trend": "insufficient_data",
        "rate_per_month": None,
        "unit": None,
        "source": None,
        "data_points": 0,
        "message": message,
    }


# ── Objective Derivation ──


def derive_objectives(conn, race_id: int) -> list[dict]:
    """Auto-derive training objectives from a target race.

    Uses Daniels VDOT for aerobic targets, distance heuristics for volume/long run,
    timeline for consistency requirements.

    Returns list of objective dicts ready for goals table upsert.
    """
    race = conn.execute("SELECT * FROM race_calendar WHERE id = ?", (race_id,)).fetchone()
    if not race:
        return []

    distance_km = race["distance_km"] or 42.195
    target_time = race["target_time"]

    # Parse target time
    target_secs = None
    if target_time:
        parts = target_time.split(":")
        if len(parts) == 3:
            target_secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            target_secs = int(parts[0]) * 60 + int(parts[1])



    objectives = []

    # 1. VO2max / VDOT target (from Daniels)
    if target_secs:
        required_vdot = compute_vdot_from_race(distance_km, target_secs)
        if required_vdot:
            # Target is the VDOT needed — no Garmin offset since we now
            # use race VDOT (not Garmin VO2max) for achievability
            objectives.append({
                "name": f"VDOT ≥{required_vdot:.0f}",
                "type": "metric",
                "target_value": round(required_vdot),
                "target_unit": "VDOT",
                "derivation_source": "auto_daniels",
                "auto_value": round(required_vdot),
            })

    # 2. Peak weekly volume (distance-based heuristic)
    if distance_km >= 40:
        volume_range = (50, 65)
    elif distance_km >= 20:
        volume_range = (40, 50)
    elif distance_km >= 10:
        volume_range = (30, 40)
    else:
        volume_range = (20, 30)

    objectives.append({
        "name": f"Peak volume {volume_range[0]}-{volume_range[1]}km/wk",
        "type": "metric",
        "target_value": volume_range[1],
        "target_unit": "km/week",
        "derivation_source": "auto_distance",
        "auto_value": volume_range[1],
    })

    # 3. Long run target (distance-based)
    if distance_km >= 40:
        long_run = 32
    elif distance_km >= 20:
        long_run = 21
    elif distance_km >= 10:
        long_run = 15
    else:
        long_run = 10

    objectives.append({
        "name": f"Long run {long_run}km",
        "type": "metric",
        "target_value": long_run,
        "target_unit": "km",
        "derivation_source": "auto_distance",
        "auto_value": long_run,
    })

    # 4. Consistency (timeline-based)
    if distance_km >= 40:
        consistency_weeks = 12
    elif distance_km >= 20:
        consistency_weeks = 8
    else:
        consistency_weeks = 6

    objectives.append({
        "name": f"Consistency {consistency_weeks}wk",
        "type": "habit",
        "target_value": consistency_weeks,
        "target_unit": "consecutive_weeks",
        "derivation_source": "auto_timeline",
        "auto_value": consistency_weeks,
    })

    # 5. Z2 compliance (always 80%+ for base)
    objectives.append({
        "name": "Z2 compliance ≥80%",
        "type": "metric",
        "target_value": 80,
        "target_unit": "%",
        "derivation_source": "auto_distance",
        "auto_value": 80,
    })

    # ── Dimension-specific targets (for fitness profile display) ──

    if target_secs and required_vdot:
        # Aerobic target: Garmin VO2max corresponding to required VDOT
        # Garmin reads ~5 higher than race VDOT
        aerobic_target = round(required_vdot + 5)
        objectives.append({
            "name": "_dim_aerobic",
            "type": "metric",
            "target_value": aerobic_target,
            "target_unit": "VO2max",
            "derivation_source": "auto_daniels",
            "auto_value": aerobic_target,
        })

        # Threshold target: Z2 speed_per_bpm_z2 at required VDOT
        # Daniels easy pace for VDOT X ≈ marathon pace * 1.25
        # speed_per_bpm at easy pace ≈ (easy_m_per_min / Z2_hr)
        marathon_pace_m_per_min = (distance_km * 1000) / (target_secs / 60)
        easy_pace_m_per_min = marathon_pace_m_per_min * 0.78  # ~78% of marathon pace
        z2_hr = 134  # Z2 ceiling from config
        threshold_target = round(easy_pace_m_per_min / z2_hr, 3)
        objectives.append({
            "name": "_dim_threshold",
            "type": "metric",
            "target_value": threshold_target,
            "target_unit": "spd/bpm_z2",
            "derivation_source": "auto_daniels",
            "auto_value": threshold_target,
        })

        # Economy target: speed_per_bpm at marathon pace and race HR
        race_hr = 165  # typical marathon race HR (~86% max HR)
        economy_target = round(marathon_pace_m_per_min / race_hr, 3)
        objectives.append({
            "name": "_dim_economy",
            "type": "metric",
            "target_value": economy_target,
            "target_unit": "spd/bpm",
            "derivation_source": "auto_daniels",
            "auto_value": economy_target,
        })

        # Resilience target: drift-free distance (as fraction of race distance)
        resilience_target = round(distance_km * 0.75)  # hold pace through 75% of distance
        objectives.append({
            "name": "_dim_resilience",
            "type": "metric",
            "target_value": resilience_target,
            "target_unit": "km",
            "derivation_source": "auto_distance",
            "auto_value": resilience_target,
        })

    return objectives


def compute_achievability(conn, objectives: list[dict], days_remaining: int) -> list[dict]:
    """Compute achievability for each objective: ✓ on track / ⚠ tight / ✗ at risk.

    Adds 'achievability', 'current_value', and 'gap' to each objective dict.
    """
    profile = get_fitness_profile(conn)
    months = max(days_remaining / 30, 0.5)

    for obj in objectives:
        target = obj.get("target_value")
        unit = obj.get("target_unit", "")
        current = None
        trend_rate = None

        if "vdot" in obj["name"].lower() or "vdot" in unit.lower():
            # Use effective_vdot (race-based), not Garmin VO2max
            current = profile["effective_vdot"]
            dim = profile["aerobic"]
            trend_rate = dim.get("rate_per_month")

        elif "volume" in obj["name"].lower() or "km/week" in unit:
            row = conn.execute("SELECT run_km FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
            current = row["run_km"] if row else 0

        elif "long run" in obj["name"].lower():
            row = conn.execute("SELECT longest_run_km FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
            current = row["longest_run_km"] if row else 0

        elif "consistency" in obj["name"].lower() or "consecutive" in unit:
            row = conn.execute("SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
            current = row["consecutive_weeks_3plus"] if row and row["consecutive_weeks_3plus"] else 0

        elif "z2" in obj["name"].lower() or "%" in unit:
            # Use 4-week rolling average (not just current week which may have only 1 run)
            row = conn.execute(
                "SELECT ROUND(AVG(z12_pct), 1) as avg FROM (SELECT z12_pct FROM weekly_agg ORDER BY week DESC LIMIT 4)"
            ).fetchone()
            current = row["avg"] if row and row["avg"] else 0

        obj["current_value"] = current
        if target and current is not None:
            gap = target - current
            obj["gap"] = round(gap, 1)

            # Project: can we close the gap in time?
            if gap <= 0:
                obj["achievability"] = "on_track"
            elif trend_rate and trend_rate > 0:
                months_needed = gap / trend_rate
                if months_needed <= months:
                    obj["achievability"] = "on_track"
                elif months_needed <= months * 1.2:
                    obj["achievability"] = "tight"
                else:
                    obj["achievability"] = "at_risk"
            elif "consistency" in obj["name"].lower():
                weeks_remaining = days_remaining / 7
                if current + weeks_remaining >= target:
                    obj["achievability"] = "on_track" if current > 0 else "tight"
                else:
                    obj["achievability"] = "at_risk"
            else:
                obj["achievability"] = "tight" if gap < target * 0.1 else "at_risk"
        else:
            obj["gap"] = None
            obj["achievability"] = "unknown"

    return objectives


# ── Checkpoint Enrichment ──


def derive_checkpoint_targets(conn) -> list[dict]:
    """Compute derived target times for upcoming checkpoint races.

    For each registered race before the target, uses Riegel back-calculation:
    "To be on track for target_time at target_distance, run this distance in X."
    """
    from fit.goals import get_target_race

    target = get_target_race(conn)
    if not target or not target.get("target_time") or not target.get("distance_km"):
        return []

    def _parse_time(t):
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0

    target_secs = _parse_time(target["target_time"])
    target_km = target["distance_km"]
    target_date = target["date"]

    # Get upcoming registered races (excluding the target itself)
    checkpoints = conn.execute("""
        SELECT * FROM race_calendar
        WHERE date >= date('now') AND date < ? AND status IN ('registered', 'planned')
        AND id != ?
        ORDER BY date
    """, (target_date, target["id"])).fetchall()

    results = []
    for cp in checkpoints:
        cp_km = cp["distance_km"]
        if not cp_km or cp_km <= 0:
            continue

        # Riegel back-calculation: what time at cp_km corresponds to target_secs at target_km?
        derived_secs = round(target_secs * (cp_km / target_km) ** 1.06)
        derived_vdot = compute_vdot_from_race(cp_km, derived_secs)

        days_to_cp = (date.fromisoformat(cp["date"]) - date.today()).days

        def _fmt_time(s):
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            if h > 0:
                return f"{h}:{m:02d}:{sec:02d}"
            return f"{m}:{sec:02d}"

        user_target = cp["target_time"]
        user_secs = _parse_time(user_target) if user_target else None

        # Readiness signal
        if user_secs and derived_secs:
            if user_secs < derived_secs:
                signal = "aiming faster than needed ✓"
            elif user_secs <= derived_secs * 1.05:
                signal = "close to on-track pace"
            else:
                signal = "slower than on-track pace ⚠"
        else:
            signal = None

        results.append({
            "race_id": cp["id"],
            "name": cp["name"],
            "date": cp["date"],
            "distance": cp["distance"],
            "distance_km": cp_km,
            "days": days_to_cp,
            "user_target": user_target,
            "user_target_secs": user_secs,
            "derived_target": _fmt_time(derived_secs),
            "derived_target_secs": derived_secs,
            "derived_vdot": derived_vdot,
            "signal": signal,
            "target_race_name": target["name"],
        })

    return results


def update_vdot_from_race_result(conn, race_id: int) -> dict | None:
    """After a race completion, compute VDOT and update fitness context.

    Returns the readiness signal dict or None.
    """
    race = conn.execute("""
        SELECT * FROM race_calendar WHERE id = ? AND status = 'completed' AND result_time IS NOT NULL
    """, (race_id,)).fetchone()

    if not race or not race["distance_km"] or not race["result_time"]:
        return None

    def _parse_time(t):
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return 0

    result_secs = _parse_time(race["result_time"])
    race_vdot = compute_vdot_from_race(race["distance_km"], result_secs)

    if not race_vdot:
        return None

    # Get target race for projection
    from fit.goals import get_target_race
    target = get_target_race(conn)
    projection = None
    if target and target.get("distance_km"):
        proj_secs = vdot_to_race_time(race_vdot, target["distance_km"])
        if proj_secs:
            h = proj_secs // 3600
            m = (proj_secs % 3600) // 60
            projection = f"{h}:{m:02d}"

    return {
        "race_name": race["name"],
        "distance_km": race["distance_km"],
        "result_time": race["result_time"],
        "race_vdot": race_vdot,
        "projection": projection,
        "target_race": target["name"] if target else None,
        "message": (
            f"{race['name']} result ({race['result_time']}) → VDOT {race_vdot}"
            + (f" → {target['name']} projection: {projection}" if projection else "")
        ),
    }
