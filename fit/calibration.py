"""Calibration tracking for physiological metrics."""

import logging
import sqlite3
from datetime import date, timedelta

logger = logging.getLogger(__name__)

STALENESS_THRESHOLDS = {
    "max_hr": timedelta(days=365),
    "lthr": timedelta(days=56),  # 8 weeks
    "weight": timedelta(days=7),
    "vo2max": timedelta(days=90),
}

RETEST_PROMPTS = {
    "max_hr": "Verify during your next hard race or interval session.",
    "lthr": "Schedule a 30-min time trial, or we can auto-extract from your next 10k+ race.",
    "weight": "Step on the scale or enter weight in `fit checkin`.",
    "vo2max": "Run outdoors with GPS for Garmin to update estimate.",
}


def get_active_calibration(conn: sqlite3.Connection, metric: str) -> dict | None:
    """Get the most recent active calibration for a metric."""
    row = conn.execute("""
        SELECT * FROM calibration
        WHERE metric = ? AND active = 1
        ORDER BY date DESC LIMIT 1
    """, (metric,)).fetchone()
    return dict(row) if row else None


def add_calibration(conn: sqlite3.Connection, metric: str, value: float,
                    method: str, confidence: str, cal_date: date,
                    source_activity_id: str | None = None,
                    notes: str | None = None) -> None:
    """Add a new calibration, deactivating previous ones for the same metric."""
    conn.execute("UPDATE calibration SET active = 0 WHERE metric = ? AND active = 1", (metric,))
    conn.execute("""
        INSERT INTO calibration (metric, value, method, confidence, date, source_activity_id, notes, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """, (metric, value, method, confidence, cal_date.isoformat(), source_activity_id, notes))
    conn.commit()
    logger.info("Calibration added: %s = %s (%s, %s confidence)", metric, value, method, confidence)


def is_stale(conn: sqlite3.Connection, metric: str) -> bool:
    """Check if a calibration is older than its staleness threshold."""
    cal = get_active_calibration(conn, metric)
    if cal is None:
        return True
    threshold = STALENESS_THRESHOLDS.get(metric, timedelta(days=365))
    cal_date = date.fromisoformat(cal["date"])
    return (date.today() - cal_date) > threshold


def get_calibration_status(conn: sqlite3.Connection) -> list[dict]:
    """Get status of all tracked metrics with staleness and retest prompts."""
    results = []
    for metric in ("max_hr", "lthr", "weight", "vo2max"):
        cal = get_active_calibration(conn, metric)
        stale = is_stale(conn, metric)
        threshold = STALENESS_THRESHOLDS[metric]

        entry = {
            "metric": metric,
            "value": cal["value"] if cal else None,
            "method": cal["method"] if cal else None,
            "date": cal["date"] if cal else None,
            "confidence": cal["confidence"] if cal else None,
            "stale": stale,
            "missing": cal is None,
            "threshold_days": threshold.days,
            "retest_prompt": RETEST_PROMPTS[metric] if stale else None,
        }

        if cal and not stale:
            cal_date = date.fromisoformat(cal["date"])
            entry["days_ago"] = (date.today() - cal_date).days
            entry["days_until_stale"] = (cal_date + threshold - date.today()).days

        results.append(entry)

    return results


def extract_max_hr_from_activity(activity: dict, current_max_hr: float | None) -> float | None:
    """Return the activity's max_hr if it raises the calibrated max above current.

    The watch records peak HR per activity. When that peak exceeds the stored
    max_hr calibration by >1 bpm and falls within a physiologically plausible
    range, treat it as evidence that the calibration is out of date — the body
    just demonstrated a higher max than we had on file.

    Plausible range: 140–215 bpm for adults. Above 215 is almost always a strap
    glitch; below 140 is too low to be a max for a trained runner. Returns
    None when the activity gives us no new information.

    Accepts any running-class activity (running, track_running, trail_running),
    matching the broader RUNNING_TYPES convention used elsewhere.
    """
    from fit.analysis import RUNNING_TYPES
    if activity.get("type") not in RUNNING_TYPES:
        return None
    observed = activity.get("max_hr")
    if not observed or observed < 140 or observed > 215:
        return None
    if current_max_hr is not None and observed <= current_max_hr + 1:
        return None
    return float(observed)


def extract_lthr_from_race(activity: dict) -> float | None:
    """Estimate LTHR from a race activity >= 10km.

    Uses avg HR of the second half of the race as an approximation.
    Since we don't have split data, we use the overall avg HR as a proxy
    (for races, avg HR of the whole effort is close to LTHR).
    """
    distance = activity.get("distance_km") or 0
    avg_hr = activity.get("avg_hr")
    run_type = activity.get("run_type")

    activity_type = activity.get("type", "")
    if activity_type != "running" or run_type != "race" or distance < 10 or not avg_hr:
        return None

    # For races >= 10km, overall avg HR approximates LTHR
    # For HM/marathon, it's slightly below LTHR; for 10k, slightly above
    # Apply a small correction factor based on distance
    if distance >= 40:  # marathon
        correction = 1.02  # avg HR is ~2% below LTHR
    elif distance >= 20:  # half marathon
        correction = 1.01
    else:  # 10k-ish
        correction = 0.99  # avg HR is ~1% above LTHR

    estimated_lthr = round(avg_hr * correction)
    logger.info("LTHR estimate from %s (%.1fkm): avg_hr=%d → estimated LTHR=%d",
                activity.get("name"), distance, avg_hr, estimated_lthr)
    return estimated_lthr
