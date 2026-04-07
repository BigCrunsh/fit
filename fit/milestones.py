"""Milestone and personal best detection."""

import logging
import sqlite3
from datetime import date

logger = logging.getLogger(__name__)


def detect_milestones(conn: sqlite3.Connection) -> list[dict]:
    """Detect recent milestones and personal bests.

    Checks:
    - New longest run (all time)
    - New best speed_per_bpm (aerobic efficiency peak)
    - Streak milestones (4, 8, 12 weeks of 3+ runs)
    - VO2max peak (all time)

    Returns list of milestone dicts with: type, message, date, previous_value, new_value.
    """
    milestones = []

    # ── Longest run ──
    longest = conn.execute("""
        SELECT date, distance_km FROM activities
        WHERE type IN ('running', 'track_running', 'trail_running') AND distance_km IS NOT NULL
        ORDER BY distance_km DESC LIMIT 2
    """).fetchall()
    if len(longest) >= 2:
        current_best = longest[0]
        previous_best = longest[1]
        # Check if the best is from the last 14 days (recent milestone)
        days_ago = (date.today() - date.fromisoformat(current_best["date"])).days
        if days_ago <= 14 and current_best["distance_km"] > previous_best["distance_km"]:
            milestones.append({
                "type": "longest_run",
                "message": f"New longest run: {current_best['distance_km']:.1f} km!",
                "date": current_best["date"],
                "previous_value": round(previous_best["distance_km"], 1),
                "new_value": round(current_best["distance_km"], 1),
            })

    # ── Best speed_per_bpm (aerobic efficiency) ──
    best_eff = conn.execute("""
        SELECT date, speed_per_bpm FROM activities
        WHERE type IN ('running', 'track_running', 'trail_running') AND speed_per_bpm IS NOT NULL
        ORDER BY speed_per_bpm DESC LIMIT 2
    """).fetchall()
    if len(best_eff) >= 2:
        current_best = best_eff[0]
        previous_best = best_eff[1]
        days_ago = (date.today() - date.fromisoformat(current_best["date"])).days
        if days_ago <= 14 and current_best["speed_per_bpm"] > previous_best["speed_per_bpm"]:
            milestones.append({
                "type": "best_efficiency",
                "message": f"New efficiency PB: {current_best['speed_per_bpm']:.2f} m/min/bpm!",
                "date": current_best["date"],
                "previous_value": round(previous_best["speed_per_bpm"], 2),
                "new_value": round(current_best["speed_per_bpm"], 2),
            })

    # ── VO2max peak ──
    best_vo2 = conn.execute("""
        SELECT date, vo2max FROM activities
        WHERE vo2max IS NOT NULL
        ORDER BY vo2max DESC LIMIT 2
    """).fetchall()
    if len(best_vo2) >= 2:
        current_best = best_vo2[0]
        previous_best = best_vo2[1]
        days_ago = (date.today() - date.fromisoformat(current_best["date"])).days
        if days_ago <= 14 and current_best["vo2max"] > previous_best["vo2max"]:
            milestones.append({
                "type": "vo2max_peak",
                "message": f"VO2max peak: {current_best['vo2max']:.0f} ml/kg/min!",
                "date": current_best["date"],
                "previous_value": round(previous_best["vo2max"], 1),
                "new_value": round(current_best["vo2max"], 1),
            })

    # ── Streak milestones (4, 8, 12 weeks) ──
    streak_row = conn.execute(
        "SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1"
    ).fetchone()
    if streak_row and streak_row[0]:
        streak = streak_row[0]
        for threshold in (4, 8, 12):
            if streak == threshold:
                milestones.append({
                    "type": "streak_milestone",
                    "message": f"Consistency streak: {threshold} weeks of 3+ runs!",
                    "date": date.today().isoformat(),
                    "previous_value": threshold - 1,
                    "new_value": threshold,
                })
                break  # Only report the exact milestone, not lower ones

    return milestones
