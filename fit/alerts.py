"""Real-time coaching alerts — threshold rules that fire after each sync."""

import json
import logging
import sqlite3
from datetime import date

from fit.analysis import detect_training_gap

logger = logging.getLogger(__name__)


def run_alerts(conn: sqlite3.Connection, config: dict) -> list[dict]:
    """Run all alert rules against current data. Store and return fired alerts."""
    today = date.today().isoformat()
    fired = []

    # Rule: All runs too hard — Z2 compliance < 50% over 2 weeks
    z12 = conn.execute("""
        SELECT AVG(z12_pct) as avg_z12 FROM (
            SELECT z12_pct FROM weekly_agg ORDER BY week DESC LIMIT 2
        )
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

    # Rule: Readiness gate — adaptive threshold (task 4.13)
    # Default threshold: 40, raised to 50 during return-to-run
    base_threshold = config.get("coaching", {}).get("readiness_gate_threshold", 40)
    gap = detect_training_gap(conn)
    readiness_threshold = 50 if gap else base_threshold

    readiness = conn.execute("SELECT training_readiness FROM daily_health ORDER BY date DESC LIMIT 1").fetchone()
    if readiness and readiness["training_readiness"] and readiness["training_readiness"] < readiness_threshold:
        context = "return-to-run" if gap else "normal"
        fired.append(_fire(conn, today, "readiness_gate",
                           f"Readiness is {readiness['training_readiness']} (threshold: {readiness_threshold}, "
                           f"context: {context}). Rest or very easy activity only.",
                           {"readiness": readiness["training_readiness"],
                            "threshold": readiness_threshold, "context": context}))

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

    # Rule: SpO2 alert — avg_spo2 < threshold for 2+ consecutive days
    spo2_threshold = config.get("coaching", {}).get("spo2_alert_threshold", 95)
    spo2_rows = conn.execute("""
        SELECT date, avg_spo2 FROM daily_health
        WHERE avg_spo2 IS NOT NULL
        ORDER BY date DESC LIMIT 7
    """).fetchall()
    if len(spo2_rows) >= 2:
        consecutive_low = 0
        for row in spo2_rows:
            if row["avg_spo2"] < spo2_threshold:
                consecutive_low += 1
            else:
                break
        if consecutive_low >= 2:
            avg_spo2 = sum(r["avg_spo2"] for r in spo2_rows[:consecutive_low]) / consecutive_low
            fired.append(_fire(conn, today, "spo2_low",
                               f"SpO2 averaging {avg_spo2:.1f}% over {consecutive_low} consecutive days "
                               f"(threshold: {spo2_threshold}%). Possible illness — consider rest.",
                               {"avg_spo2": avg_spo2, "consecutive_days": consecutive_low,
                                "threshold": spo2_threshold}))

    # Rule: Deload overdue — no deload week in 4+ consecutive build weeks (task 4.9)
    deload_alert = _check_deload_overdue(conn, today)
    if deload_alert:
        fired.append(deload_alert)

    logger.info("Alerts: %d fired", len(fired))
    return fired


def _check_deload_overdue(conn: sqlite3.Connection, today: str) -> dict | None:
    """Alert if no deload week in 4+ consecutive build weeks.

    A deload = volume drops >=30% from prior week.
    """
    weeks = conn.execute(
        "SELECT week, run_km FROM weekly_agg ORDER BY week DESC LIMIT 6"
    ).fetchall()

    if len(weeks) < 3:
        return None

    # Count consecutive build weeks (no deload) from most recent
    consecutive_build = 0
    for i in range(len(weeks) - 1):
        current_km = weeks[i]["run_km"] or 0
        prev_km = weeks[i + 1]["run_km"] or 0
        if prev_km > 0 and current_km < prev_km * 0.7:
            # This was a deload week — volume dropped >=30%
            break
        consecutive_build += 1

    if consecutive_build >= 4:
        return _fire(conn, today, "deload_overdue",
                     f"{consecutive_build} consecutive build weeks without a deload. "
                     f"Consider reducing volume 30-40% this week for recovery.",
                     {"consecutive_build_weeks": consecutive_build})
    return None


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
