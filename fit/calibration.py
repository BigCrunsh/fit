"""Calibration tracking for physiological metrics."""

import json
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

# Plausibility envelopes for the flag taxonomy. Outside the envelope, a
# reading is recorded with `implausible_value` flag and `confidence=low`
# rather than being silently dropped — keeps an audit trail of strap
# glitches and lets the history chart show the anomaly as a red ring.
_PLAUSIBLE = {
    "max_hr": (140, 215),
    "lthr":   (130, 200),
    "vo2max": (25, 80),
    "weight": (35, 200),  # kg
}

# Direction-anomaly thresholds (drop vs prior active) within 12 weeks.
# Slow drift downward is real (age, detraining); sudden drops usually
# mean under-recovery or measurement noise.
_DIRECTION_DROP = {
    "max_hr": 2,    # bpm
    "lthr": 5,      # bpm
    "vo2max": 3,    # ml/kg/min
}

# Tolerance for "agrees with prior" — within ±tolerance of the active row.
_AGREE_TOLERANCE = {
    "max_hr": 2,
    "lthr": 2,
    "aet": 3,
    "vo2max": 1,
    "weight": 0.5,
}


def derive_flags(metric: str, value: float, method: str,
                 prior: dict | None) -> list[str]:
    """Compute the flag list for a new calibration reading.

    Inputs:
        metric: 'max_hr' | 'lthr' | 'aet' | 'vo2max' | 'weight'
        value: the new reading
        method: 'manual' | 'race_extract' | 'activity_max' | 'drift_test' | ...
        prior: the currently-active calibration dict (or None)

    Returns:
        Sorted list of flag strings. Empty list = clean reading.
    """
    flags: list[str] = []

    # implausible — physiologically out of envelope
    env = _PLAUSIBLE.get(metric)
    if env and (value < env[0] or value > env[1]):
        flags.append("implausible_value")

    if prior is not None:
        prior_val = prior.get("value")
        if prior_val is not None:
            tol = _AGREE_TOLERANCE.get(metric, 2)
            if abs(value - prior_val) <= tol:
                flags.append("agrees_with_prior")
            else:
                # Unexpected directional drop within 12 weeks
                drop_threshold = _DIRECTION_DROP.get(metric)
                if drop_threshold is not None and prior_val - value > drop_threshold:
                    if prior.get("date"):
                        prior_date = date.fromisoformat(prior["date"])
                        if (date.today() - prior_date).days < 84:  # 12 weeks
                            flags.append("unexpected_direction")
                # Upward revision of max_hr (or vo2max) in a hard-effort
                # context is the strongest evidence the prior was a low
                # guess — the body literally demonstrated a higher value.
                # Mark it as `new_peak` so derive_confidence promotes to
                # high rather than letting an older manual reading win.
                if (
                    metric in ("max_hr", "vo2max")
                    and method != "activity_max"
                    and value > prior_val + tol
                ):
                    flags.append("new_peak")

    # Weak context — extracted from a non-race / non-hard-effort activity.
    # `activity_max` flag is used by max_hr extraction outside races.
    if method == "activity_max":
        flags.append("weak_context")

    return sorted(set(flags))


def derive_confidence(method: str, flags: list[str], has_prior_agreement: bool = False) -> str:
    """Map (method, flags, prior_agreement) → confidence tier.

    Uniform rubric across all metrics:
        high   — manual write OR two corroborating readings within tolerance
        medium — single recent reading from a hard-effort context, no flags
        low    — any blocking flag (implausible_value / spike /
                 unexpected_direction / weak_context)

    Note: stale → low is a query-time concern, not encoded in the stored
    `confidence` field. The row's stored confidence reflects write-time
    quality; `get_calibration_status()` reports `low` when the active row
    has crossed its STALENESS_THRESHOLDS boundary.
    """
    # Blocking flags always demote to low — manual override can't rescue
    # an implausible reading (the user should re-enter or rely on the
    # next valid reading).
    blockers = {"implausible_value", "spike", "unexpected_direction", "weak_context"}
    if any(f in blockers for f in flags):
        return "low"
    if method == "manual":
        return "high"
    if has_prior_agreement or "agrees_with_prior" in flags:
        return "high"
    # Upward revision in a hard-effort context — physiology said so, trust it.
    if "new_peak" in flags:
        return "high"
    return "medium"


_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2}


def get_active_calibration(conn: sqlite3.Connection, metric: str) -> dict | None:
    """Get the active calibration row for a metric, preferring higher confidence.

    Selection rule (subsumes the old date-only behavior):
      1. Prefer non-stale rows over stale rows.
      2. Within that pool, prefer higher confidence (high → medium → low).
      3. Within tied confidence, prefer the most recent date.

    This keeps a single spurious low-confidence row (e.g., a strap-glitch
    220 bpm max_hr) from displacing a clean medium-confidence row written
    earlier. Falls back to pure date if no rows are within the staleness
    window.
    """
    rows = conn.execute("""
        SELECT * FROM calibration
        WHERE metric = ?
        ORDER BY date DESC
    """, (metric,)).fetchall()
    if not rows:
        return None

    threshold = STALENESS_THRESHOLDS.get(metric, timedelta(days=365))
    today = date.today()

    def _is_stale(r):
        try:
            return (today - date.fromisoformat(r["date"])) > threshold
        except (ValueError, TypeError):
            return True

    def _sort_key(r):
        # Confidence rank ascending (lower = better), then date desc.
        # Using negative-day offset so SORT ASC keeps newer first.
        try:
            day_offset = -date.fromisoformat(r["date"]).toordinal()
        except (ValueError, TypeError):
            day_offset = 0
        return (_CONFIDENCE_RANK.get(r["confidence"] or "low", 2), day_offset)

    non_stale = [r for r in rows if not _is_stale(r)]
    pool = non_stale if non_stale else rows
    chosen = min(pool, key=_sort_key)
    return dict(chosen)


def add_calibration(conn: sqlite3.Connection, metric: str, value: float,
                    method: str, confidence: str, cal_date: date,
                    source_activity_id: str | None = None,
                    notes: str | None = None,
                    flags: list[str] | None = None) -> None:
    """Add a new calibration row.

    The new row is marked active=1; all prior rows for the metric get
    active=0. Note: this is just a bookkeeping flag — `get_active_calibration`
    re-evaluates active using the confidence-aware rule on every read, so
    the column's value reflects "last inserted", not "currently used".

    `flags` is a list of taxonomy tags ({implausible_value, spike,
    unexpected_direction, agrees_with_prior, weak_context}) — stored as a
    JSON array string. Empty list / None becomes '[]'.
    """
    conn.execute("UPDATE calibration SET active = 0 WHERE metric = ? AND active = 1", (metric,))
    flags_json = json.dumps(sorted(set(flags))) if flags else "[]"
    conn.execute("""
        INSERT INTO calibration (metric, value, method, confidence, date,
                                 source_activity_id, notes, active, flags)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (metric, value, method, confidence, cal_date.isoformat(),
          source_activity_id, notes, flags_json))
    conn.commit()
    logger.info("Calibration added: %s = %s (%s, %s confidence%s)",
                metric, value, method, confidence,
                f", flags={flags}" if flags else "")


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


def get_calibration_history(conn: sqlite3.Connection, metric: str) -> list[dict]:
    """Return every calibration row for a metric, oldest first.

    Used by the dashboard's per-metric history chart and by the CLI
    `fit calibrate history <metric>` command. Each dict includes value,
    date, method, confidence, source_activity_id, notes, and the parsed
    flags list.
    """
    rows = conn.execute("""
        SELECT id, metric, value, method, confidence, date,
               source_activity_id, notes, flags
        FROM calibration
        WHERE metric = ?
        ORDER BY date ASC
    """, (metric,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["flags"] = json.loads(d["flags"] or "[]")
        except (ValueError, TypeError):
            d["flags"] = []
        out.append(d)
    return out


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
