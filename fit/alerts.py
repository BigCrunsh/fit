"""Real-time coaching alerts — threshold rules that fire after each sync."""

import json
import logging
import sqlite3
from datetime import date

logger = logging.getLogger(__name__)


def run_alerts(conn: sqlite3.Connection, config: dict) -> list[dict]:
    """Run all alert rules against current data. Store and return fired alerts."""
    today = date.today().isoformat()
    fired = []

    # Rule: All runs too hard — Z2 compliance < 50% over 2 weeks
    z12 = conn.execute("""
        SELECT AVG(z12_pct) as avg_z12 FROM weekly_agg
        WHERE week >= (SELECT MAX(week) FROM weekly_agg) ORDER BY week DESC LIMIT 2
    """).fetchone()
    if z12 and z12["avg_z12"] is not None and z12["avg_z12"] < 50:
        fired.append(_fire(conn, today, "all_runs_too_hard",
                           f"Only {z12['avg_z12']:.0f}% of training time in Z1+Z2 (target: ≥80%). "
                           f"Your aerobic base cannot develop at this intensity.",
                           {"z12_pct": z12["avg_z12"]}))

    # Rule: Volume ramp guard — >10% increase AND <8 consecutive weeks
    weeks = conn.execute("SELECT run_km, consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 2").fetchall()
    if len(weeks) >= 2:
        this_km = weeks[0]["run_km"] or 0
        last_km = weeks[1]["run_km"] or 0
        streak = weeks[0]["consecutive_weeks_3plus"] or 0
        if last_km > 0 and ((this_km - last_km) / last_km) > 0.1 and streak < 8:
            fired.append(_fire(conn, today, "volume_ramp",
                               f"Volume increased {((this_km - last_km) / last_km * 100):.0f}% ({last_km:.0f}→{this_km:.0f}km) "
                               f"with only {streak} weeks of consistency. Risk of injury. Keep increase ≤10%.",
                               {"this_km": this_km, "last_km": last_km, "streak": streak}))

    # Rule: Readiness gate — low readiness + planned quality session
    readiness = conn.execute("SELECT training_readiness FROM daily_health ORDER BY date DESC LIMIT 1").fetchone()
    if readiness and readiness["training_readiness"] and readiness["training_readiness"] < 30:
        fired.append(_fire(conn, today, "readiness_gate",
                           f"Readiness is {readiness['training_readiness']}. Rest or very easy activity only.",
                           {"readiness": readiness["training_readiness"]}))

    # Rule: Alcohol + HRV drop
    last_ci = conn.execute("SELECT date, alcohol FROM checkins ORDER BY date DESC LIMIT 1").fetchone()
    today_hrv = conn.execute("SELECT hrv_last_night FROM daily_health ORDER BY date DESC LIMIT 1").fetchone()
    avg_hrv = conn.execute("SELECT AVG(hrv_last_night) as avg FROM daily_health WHERE date >= date('now', '-7 days')").fetchone()
    if last_ci and last_ci["alcohol"] and last_ci["alcohol"] >= 2 and today_hrv and avg_hrv:
        hrv_now = today_hrv["hrv_last_night"] or 0
        hrv_avg = avg_hrv["avg"] or 0
        if hrv_avg > 0 and hrv_now < hrv_avg * 0.85:
            drop_pct = (1 - hrv_now / hrv_avg) * 100
            fired.append(_fire(conn, today, "alcohol_hrv",
                               f"HRV {hrv_now:.0f}ms (↓{drop_pct:.0f}% from 7d avg {hrv_avg:.0f}ms) after "
                               f"{last_ci['alcohol']:.0f} drinks. Rest day recommended.",
                               {"hrv_now": hrv_now, "hrv_avg": hrv_avg, "drinks": last_ci["alcohol"]}))

    logger.info("Alerts: %d fired", len(fired))
    return fired


def _fire(conn: sqlite3.Connection, today: str, alert_type: str, message: str, data: dict) -> dict:
    """Store and return a fired alert."""
    # Don't duplicate same-day same-type alerts
    existing = conn.execute("SELECT 1 FROM alerts WHERE date = ? AND type = ?", (today, alert_type)).fetchone()
    if not existing:
        conn.execute("""
            INSERT INTO alerts (date, type, message, data_context)
            VALUES (?, ?, ?, ?)
        """, (today, alert_type, message, json.dumps(data)))
        conn.commit()
    return {"type": alert_type, "message": message, "data": data}


def get_recent_alerts(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Get recent unacknowledged alerts."""
    rows = conn.execute("""
        SELECT date, type, message, data_context FROM alerts
        WHERE date >= date('now', ?) AND acknowledged = 0
        ORDER BY date DESC
    """, (f"-{days} days",)).fetchall()
    return [{"date": r["date"], "type": r["type"], "message": r["message"]} for r in rows]
