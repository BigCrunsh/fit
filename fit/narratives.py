"""Rule-based trend narratives and story connectors for the dashboard."""

import logging
import sqlite3
from datetime import date


logger = logging.getLogger(__name__)


# ── 3.6: Race Countdown Narrative ──


def generate_race_countdown(conn: sqlite3.Connection) -> dict | None:
    """Generate race countdown with phase position and objective progress.

    Returns dict with days_remaining, phase info, objectives, taper rules.
    """
    from fit.goals import get_target_race

    race = get_target_race(conn)
    if not race:
        return None

    today = date.today()
    try:
        race_date = date.fromisoformat(race["date"])
    except (ValueError, TypeError):
        return None

    days_remaining = (race_date - today).days
    if days_remaining < 0:
        return None

    result = {
        "race_name": race["name"],
        "race_date": race["date"],
        "distance": race.get("distance", ""),
        "days_remaining": days_remaining,
        "phase": None,
        "phase_position": None,
        "objectives_on_track": 0,
        "objectives_total": 0,
        "taper_rules": None,
    }

    # Phase position
    phases = conn.execute("""
        SELECT * FROM training_phases WHERE status != 'revised'
        ORDER BY start_date
    """).fetchall()
    if phases:
        active = [p for p in phases if p["status"] == "active"]
        if active:
            active_phase = active[0]
            phase_num = next(
                (i + 1 for i, p in enumerate(phases) if p["id"] == active_phase["id"]),
                1
            )
            result["phase"] = active_phase["name"]
            result["phase_position"] = f"Phase {phase_num} of {len(phases)}"

    # Objective progress from goals
    goals = conn.execute(
        "SELECT * FROM goals WHERE active = 1"
    ).fetchall()
    on_track = 0
    total = 0
    for g in goals:
        total += 1
        if g["type"] == "metric" and g["target_value"]:
            # Check current value vs target
            if "vo2" in (g["name"] or "").lower():
                v = conn.execute(
                    "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
                ).fetchone()
                if v and v["vo2max"] >= g["target_value"]:
                    on_track += 1
            elif "weight" in (g["name"] or "").lower():
                v = conn.execute(
                    "SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1"
                ).fetchone()
                if v and v["weight_kg"] <= g["target_value"]:
                    on_track += 1
    result["objectives_on_track"] = on_track
    result["objectives_total"] = total

    # Taper rules for final 2-3 weeks
    if days_remaining <= 21:
        if days_remaining <= 7:
            result["taper_rules"] = (
                "Final week: volume drop 60%, no quality sessions. "
                "Short shakeout runs only. Focus on sleep and nutrition."
            )
        elif days_remaining <= 14:
            result["taper_rules"] = (
                "Taper week 2: volume drop 50%, last quality session ~10 days out. "
                "Maintain frequency, reduce duration."
            )
        else:
            result["taper_rules"] = (
                "Taper begins: volume drop 40%, reduce long run to 60% of peak. "
                "Keep 1-2 short quality sessions for sharpness."
            )

    return result


# ── Data Storytelling Generators ──


def generate_body_summary(conn: sqlite3.Connection) -> str | None:
    """One-line narrative for the Body tab: connect recovery signals.

    E.g. "Recovery improving: readiness 6→67 in 3 days. RHR stable. HRV low but trending up."
    """
    recent = conn.execute("""
        SELECT date, training_readiness, resting_heart_rate, hrv_last_night
        FROM daily_health WHERE date >= date('now', '-7 days')
        ORDER BY date DESC
    """).fetchall()
    if len(recent) < 2:
        return None

    parts = []

    # Readiness trend
    r_now = recent[0]["training_readiness"]
    r_min = min((r["training_readiness"] for r in recent if r["training_readiness"]), default=None)
    r_max = max((r["training_readiness"] for r in recent if r["training_readiness"]), default=None)
    if r_now and r_min and r_max and r_max - r_min > 20:
        if r_now > r_min + 15:
            parts.append(f"Recovery improving: readiness {r_min}→{r_now}")
        elif r_now < r_max - 15:
            parts.append(f"Recovery declining: readiness {r_max}→{r_now}")
    elif r_now:
        if r_now >= 75:
            parts.append(f"Readiness {r_now} — ready for quality")
        elif r_now >= 50:
            parts.append(f"Readiness {r_now} — easy day")
        else:
            parts.append(f"Readiness {r_now} — rest recommended")

    # RHR trend
    rhr_vals = [r["resting_heart_rate"] for r in recent if r["resting_heart_rate"]]
    if len(rhr_vals) >= 3:
        rhr_trend = rhr_vals[0] - rhr_vals[-1]
        if abs(rhr_trend) <= 2:
            parts.append("RHR stable")
        elif rhr_trend < 0:
            parts.append("RHR dropping (good)")
        else:
            parts.append(f"RHR rising (+{rhr_trend})")

    # HRV
    hrv_vals = [r["hrv_last_night"] for r in recent if r["hrv_last_night"]]
    if hrv_vals:
        hrv_avg = sum(hrv_vals) / len(hrv_vals)
        if hrv_avg < 30:
            parts.append("HRV low")
        elif hrv_vals[0] > hrv_avg * 1.1:
            parts.append("HRV trending up")
        else:
            parts.append(f"HRV {hrv_avg:.0f}ms avg")

    # Weight vs target
    weight = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
    target = conn.execute(
        "SELECT target_value FROM goals WHERE type='metric' AND name LIKE '%eight%' AND active=1 LIMIT 1"
    ).fetchone()
    if weight and target and target["target_value"]:
        diff = weight["weight_kg"] - target["target_value"]
        if diff > 0:
            parts.append(f"Weight: {diff:.1f}kg above target")
        else:
            parts.append("Weight: at target")

    return ". ".join(parts) + "." if parts else None
