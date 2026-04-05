"""Data source health checking — what's active, stale, or missing."""

import logging
import sqlite3
from datetime import date

logger = logging.getLogger(__name__)

GARMIN_INSTRUCTIONS = {
    "spo2": "Enable Pulse Ox → Garmin Settings → Health & Wellness → Pulse Oximeter → During Sleep",
    "lthr_detection": "Enable LTHR → Garmin Settings → Physiological Metrics → Lactate Threshold",
    "hrv_status": "Enable HRV → Garmin Settings → Health & Wellness → HRV Status (needs 3 weeks for baseline)",
    "training_readiness": "Enable Training Readiness (usually on by default on newer watches)",
    "move_iq": "Enable Move IQ → Garmin Settings → Activity Tracking → Move IQ",
}


def check_data_sources(conn: sqlite3.Connection) -> list[dict]:
    """Check freshness and availability of all data sources.

    Returns list of dicts with: source, status (active/stale/missing),
    last_date, instruction (if missing).
    """
    results = []
    today = date.today()

    # Garmin health metrics
    last_health = conn.execute("SELECT MAX(date) FROM daily_health").fetchone()[0]
    results.append(_check("garmin_health", last_health, today, stale_days=3))

    # Garmin activities
    last_activity = conn.execute("SELECT MAX(date) FROM activities").fetchone()[0]
    results.append(_check("garmin_activities", last_activity, today, stale_days=7))

    # SpO2
    spo2_count = conn.execute("""
        SELECT COUNT(*) FROM daily_health
        WHERE avg_spo2 IS NOT NULL AND date >= date('now', '-14 days')
    """).fetchone()[0]
    if spo2_count == 0:
        results.append({
            "source": "spo2", "status": "missing", "last_date": None,
            "instruction": GARMIN_INSTRUCTIONS["spo2"],
        })
    else:
        results.append({"source": "spo2", "status": "active", "last_date": None, "instruction": None})

    # HRV Status
    hrv_count = conn.execute("""
        SELECT COUNT(*) FROM daily_health
        WHERE hrv_status IS NOT NULL AND date >= date('now', '-14 days')
    """).fetchone()[0]
    if hrv_count == 0:
        results.append({
            "source": "hrv_status", "status": "missing", "last_date": None,
            "instruction": GARMIN_INSTRUCTIONS["hrv_status"],
        })
    else:
        results.append({"source": "hrv_status", "status": "active", "last_date": None, "instruction": None})

    # Training Readiness
    readiness_count = conn.execute("""
        SELECT COUNT(*) FROM daily_health
        WHERE training_readiness IS NOT NULL AND date >= date('now', '-14 days')
    """).fetchone()[0]
    if readiness_count == 0:
        results.append({
            "source": "training_readiness", "status": "missing", "last_date": None,
            "instruction": GARMIN_INSTRUCTIONS["training_readiness"],
        })
    else:
        results.append({"source": "training_readiness", "status": "active", "last_date": None, "instruction": None})

    # Move IQ
    moveiq_count = conn.execute(
        "SELECT COUNT(*) FROM activities WHERE subtype = 'auto_detected'"
    ).fetchone()[0]
    if moveiq_count == 0:
        results.append({
            "source": "move_iq", "status": "missing", "last_date": None,
            "instruction": GARMIN_INSTRUCTIONS["move_iq"],
        })
    else:
        results.append({"source": "move_iq", "status": "active", "last_date": None, "instruction": None})

    # Weight
    last_weight = conn.execute("SELECT MAX(date) FROM body_comp").fetchone()[0]
    results.append(_check("weight", last_weight, today, stale_days=7))

    # Check-ins
    last_checkin = conn.execute("SELECT MAX(date) FROM checkins").fetchone()[0]
    results.append(_check("checkins", last_checkin, today, stale_days=2))

    return results


def _check(source: str, last_date_str: str | None, today: date, stale_days: int) -> dict:
    """Classify a data source as active, stale, or missing."""
    if not last_date_str:
        return {"source": source, "status": "missing", "last_date": None, "instruction": None}

    last = date.fromisoformat(last_date_str)
    age = (today - last).days

    if age <= stale_days:
        status = "active"
    else:
        status = "stale"

    return {
        "source": source, "status": status, "last_date": last_date_str,
        "instruction": None, "days_ago": age,
    }
