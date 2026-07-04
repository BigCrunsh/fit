"""Real-time coaching alerts — threshold rules that fire after each sync."""

import json
import logging
import sqlite3
from datetime import date

from fit.analysis import detect_training_gap

logger = logging.getLogger(__name__)

# Severity tiers from most-urgent to least-urgent. The order here is also
# the render order — dashboard and MCP iterate critical → warning → info.
_SEVERITY_TIERS = ("critical", "warning", "info")
_SEVERITY_ORDER = {sev: i for i, sev in enumerate(_SEVERITY_TIERS)}

# Severity mapping per alert rule. Anything not listed defaults to 'info'.
ALERT_SEVERITY: dict[str, str] = {
    # Critical — immediate physiological / injury-risk signal
    "acwr_spike_danger": "critical",
    "readiness_gate": "critical",
    "volume_ramp": "critical",
    "recovery_cliff": "critical",
    # Warning — meaningful but not urgent
    "all_runs_too_hard": "warning",
    "high_monotony": "warning",
    "undertraining": "warning",
    "deload_overdue": "warning",
    "spo2_low": "warning",
    "respiration_elevated": "warning",
    "rhr_elevated": "warning",
    # info — context signal (anything not listed)
}


def severity_of(alert_type: str) -> str:
    """Return the severity tier for an alert type. Defaults to 'info'."""
    return ALERT_SEVERITY.get(alert_type, "info")


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

    # Rule: Monotony >2.0 — overtraining risk (Foster's guideline).
    # Rolling-7d "now" read (window policy §4.1), matching CLI status and coaching;
    # weekly_agg.monotony stays the ISO-week trend. Config-free so this fire and the
    # auto-dismiss in _condition_still_holds compute the identical value (no
    # weighted/unweighted split → no fire-then-instant-dismiss), as compute_rolling_acwr.
    from fit.analysis import compute_rolling_week
    monotony = compute_rolling_week(conn).get("monotony")
    if monotony and monotony > 2.0:
        fired.append(_fire(conn, today, "high_monotony",
                           f"Training monotony is {monotony:.1f} (threshold: 2.0). "
                           f"Vary your sessions — mix easy, tempo, and long runs to reduce overtraining risk.",
                           {"monotony": monotony}))

    # Rule: ACWR <0.6 — undertraining / detraining risk
    # Uses rolling 7-day window — no partial-week suppression needed
    from fit.analysis import compute_rolling_acwr
    rolling_acwr = compute_rolling_acwr(conn)
    if rolling_acwr is not None and rolling_acwr < 0.6:
        fired.append(_fire(conn, today, "undertraining",
                           f"ACWR is {rolling_acwr:.2f} — significantly below optimal (0.8-1.3). "
                           f"You may be losing fitness. Gradually increase training load.",
                           {"acwr": rolling_acwr}))

    # Rule: Deload overdue — no deload week in 4+ consecutive build weeks (task 4.9)
    deload_alert = _check_deload_overdue(conn, today)
    if deload_alert:
        fired.append(deload_alert)

    # Wellness baseline-deviation rules — fire and auto-dismiss both read
    # wellness_snapshot (SSOT), so they can never disagree.
    fired.extend(_wellness_alerts(conn, config, today))

    logger.info("Alerts: %d fired", len(fired))
    return fired


def _wellness_alerts(conn: sqlite3.Connection, config: dict, today: str) -> list[dict]:
    """Personal-baseline deviation alerts: respiration, RHR, recovery cliff."""
    from fit.wellness import wellness_snapshot
    snap = wellness_snapshot(conn, config)
    fired = []

    resp = snap["respiration"]
    if resp["elevated"]:
        label = "sleep" if resp["series"] == "sleep" else "waking"
        fired.append(_fire(conn, today, "respiration_elevated",
                           f"Respiration ({label}) at {resp['latest']:.1f} brpm — "
                           f"{resp['consecutive_elevated']} consecutive nights ≥ baseline "
                           f"{resp['baseline']:.1f} + {resp['delta']:.0f}. "
                           f"Early sign of illness or accumulated fatigue — favor rest and sleep.",
                           {"latest": resp["latest"], "baseline": resp["baseline"],
                            "nights": resp["consecutive_elevated"], "series": resp["series"]}))

    rhr = snap["rhr"]
    if rhr["elevated"]:
        fired.append(_fire(conn, today, "rhr_elevated",
                           f"Resting HR at {rhr['latest']:.0f} — {rhr['consecutive_elevated']} "
                           f"consecutive days ≥ baseline {rhr['baseline']:.0f} + {rhr['delta']:.0f} bpm. "
                           f"Accumulated fatigue or oncoming illness — reduce load until it settles.",
                           {"latest": rhr["latest"], "baseline": rhr["baseline"],
                            "days": rhr["consecutive_elevated"]}))

    if snap["recovery_cliff"]:
        c = snap["recovery_cliff_components"]
        fired.append(_fire(conn, today, "recovery_cliff",
                           f"Recovery cliff: RHR {c['rhr']} (baseline {c['rhr_baseline']:.0f}), "
                           f"HRV {c['hrv_status'] or 'below baseline'}, readiness {c['readiness']} — "
                           f"all three recovery signals down together. Rest day strongly recommended.",
                           {k: c[k] for k in ("date", "rhr", "rhr_baseline", "hrv_status", "readiness")}))

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

    # One 30%-drop build-streak rule, shared with periodization (D13) instead of a
    # second hand-rolled loop. (`_count_consecutive_build_weeks` counts build weeks
    # newest-first, stopping at the first ≥30% volume drop.)
    from fit.periodization import _count_consecutive_build_weeks
    consecutive_build = _count_consecutive_build_weeks(weeks)

    if consecutive_build >= 4:
        return _fire(conn, today, "deload_overdue",
                     f"{consecutive_build} consecutive build weeks without a deload. "
                     f"Consider reducing volume 30-40% this week for recovery.",
                     {"consecutive_build_weeks": consecutive_build})
    return None


def _fire(conn: sqlite3.Connection, today: str, alert_type: str, message: str, data: dict) -> dict:
    """Store and return a fired alert with explicit severity."""
    # Don't duplicate same-day same-type alerts
    existing = conn.execute("SELECT 1 FROM alerts WHERE date = ? AND type = ?", (today, alert_type)).fetchone()
    if not existing:
        conn.execute("""
            INSERT INTO alerts (date, type, message, data_context)
            VALUES (?, ?, ?, ?)
        """, (today, alert_type, message, json.dumps(data)))
        conn.commit()
    return {
        "type": alert_type,
        "severity": severity_of(alert_type),
        "message": message,
        "data": data,
    }


def get_recent_alerts(conn: sqlite3.Connection, days: int = 7) -> list[dict]:
    """Get recent unacknowledged alerts, auto-dismissing stale ones.

    Each alert's underlying condition is re-evaluated. If the condition
    no longer holds, the alert is marked acknowledged (auto-dismissed)
    and excluded from the result.
    """
    rows = conn.execute("""
        SELECT rowid as id, date, type, message, data_context FROM alerts
        WHERE date >= date('now', ?) AND acknowledged = 0
        ORDER BY date DESC
    """, (f"-{days} days",)).fetchall()

    # Dedupe by type — only the most recent of each type is shown (the date
    # ORDER BY DESC above gives us that natively since we iterate top-down).
    seen_types: set[str] = set()
    result = []
    for r in rows:
        if r["type"] in seen_types:
            continue
        if _condition_still_holds(conn, r["type"]):
            seen_types.add(r["type"])
            result.append({
                "date": r["date"],
                "type": r["type"],
                "severity": severity_of(r["type"]),
                "message": r["message"],
            })
        else:
            conn.execute("UPDATE alerts SET acknowledged = 1 WHERE rowid = ?", (r["id"],))
    conn.commit()
    # Order by severity (critical → warning → info), then most-recent within
    # tier. Single tuple key — second component is negated date string, which
    # is a valid sort proxy because ISO dates compare lexicographically.
    result.sort(key=lambda a: (_SEVERITY_ORDER.get(a["severity"], 99), -date.fromisoformat(a["date"]).toordinal()))
    return result


def _condition_still_holds(conn: sqlite3.Connection, alert_type: str) -> bool:
    """Re-evaluate whether an alert's underlying condition is still true."""
    try:
        if alert_type == "all_runs_too_hard":
            row = conn.execute("""
                SELECT AVG(z12_pct) as avg_z12 FROM (
                    SELECT z12_pct FROM weekly_agg ORDER BY week DESC LIMIT 2
                )
            """).fetchone()
            return bool(row and row["avg_z12"] is not None and row["avg_z12"] < 50)

        if alert_type == "volume_ramp":
            weeks = conn.execute(
                "SELECT run_km, consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 2"
            ).fetchall()
            if len(weeks) < 2:
                return False
            this_km = weeks[0]["run_km"] or 0
            last_km = weeks[1]["run_km"] or 0
            streak = weeks[0]["consecutive_weeks_3plus"] or 0
            return last_km > 0 and ((this_km - last_km) / last_km) > 0.1 and streak < 8

        if alert_type == "readiness_gate":
            row = conn.execute(
                "SELECT training_readiness FROM daily_health ORDER BY date DESC LIMIT 1"
            ).fetchone()
            # Match the firing threshold (gap-aware): 50 during return-to-run, else 40.
            # A hardcoded 40 here meant a gap-window alert that fired at 50 could never
            # auto-dismiss (readiness 40-49 → still held), leaving a stale alert (D12).
            threshold = 50 if detect_training_gap(conn) else 40
            return bool(row and row["training_readiness"] and row["training_readiness"] < threshold)

        if alert_type == "spo2_low":
            rows = conn.execute("""
                SELECT avg_spo2 FROM daily_health
                WHERE avg_spo2 IS NOT NULL ORDER BY date DESC LIMIT 2
            """).fetchall()
            if len(rows) < 2:
                return False
            return all(r["avg_spo2"] < 95 for r in rows)

        if alert_type == "high_monotony":
            # Same rolling-7d, config-free source as the fire rule above — so an alert
            # never fires and instantly self-dismisses on a window/weighting mismatch.
            from fit.analysis import compute_rolling_week
            monotony = compute_rolling_week(conn).get("monotony")
            return bool(monotony and monotony > 2.0)

        if alert_type == "undertraining":
            # Same rolling source as the fire rule (compute_rolling_acwr) so fire and
            # dismiss agree — was the stored weekly_agg.acwr ISO trend, a mismatch (D6).
            from fit.analysis import compute_rolling_acwr
            acwr = compute_rolling_acwr(conn)
            return bool(acwr is not None and acwr < 0.6)

        if alert_type in ("respiration_elevated", "rhr_elevated", "recovery_cliff"):
            # Same wellness_snapshot as the fire rules (config-free defaults, like the
            # other branches here) — fire and dismiss can never disagree on the math.
            from fit.wellness import wellness_snapshot
            snap = wellness_snapshot(conn, None)
            if alert_type == "respiration_elevated":
                return bool(snap["respiration"]["elevated"])
            if alert_type == "rhr_elevated":
                return bool(snap["rhr"]["elevated"])
            return bool(snap["recovery_cliff"])

        if alert_type == "deload_overdue":
            weeks = conn.execute(
                "SELECT week, run_km FROM weekly_agg ORDER BY week DESC LIMIT 6"
            ).fetchall()
            if len(weeks) < 3:
                return False
            consecutive_build = 0
            for i in range(len(weeks) - 1):
                current_km = weeks[i]["run_km"] or 0
                prev_km = weeks[i + 1]["run_km"] or 0
                if prev_km > 0 and current_km < prev_km * 0.7:
                    break
                consecutive_build += 1
            return consecutive_build >= 4

    except Exception:
        # On error, keep the alert (don't auto-dismiss)
        return True

    # Unknown alert type — keep it
    return True
