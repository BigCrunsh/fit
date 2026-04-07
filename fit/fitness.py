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
    """Most recent VDOT from a completed race result."""
    races = conn.execute("""
        SELECT date, distance_km, result_time FROM race_calendar
        WHERE status = 'completed' AND result_time IS NOT NULL AND distance_km IS NOT NULL
        ORDER BY date DESC LIMIT 3
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

    # Use the most recent race
    r = races[0]
    time_sec = _parse_time(r["result_time"])
    vdot = compute_vdot_from_race(r["distance_km"], time_sec)
    return vdot, r["date"]


def _compute_effective_vdot(garmin_vo2: float | None, race_vdot: float | None,
                             race_date: str | None) -> float | None:
    """Blend Garmin VO2max and race VDOT. Prefer race when <8 weeks old."""
    if race_vdot and race_date:
        days_ago = (date.today() - date.fromisoformat(race_date)).days
        if days_ago <= 56:  # 8 weeks
            # Race VDOT is recent — use it, with slight blend toward Garmin
            if garmin_vo2:
                # 70% race, 30% Garmin
                return round(race_vdot * 0.7 + garmin_vo2 * 0.3, 1)
            return race_vdot

    # Race VDOT is stale or missing — use Garmin
    return garmin_vo2


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
