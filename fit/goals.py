"""Goal and training phase lifecycle management."""

import json
import logging
import sqlite3
from datetime import date

logger = logging.getLogger(__name__)


def create_goal(conn, name: str, goal_type: str, target_value=None, target_unit=None,
                target_time=None, target_pace=None, target_date=None) -> int:
    """Create a goal and log its creation. Returns the goal ID."""
    cursor = conn.execute("""
        INSERT INTO goals (name, type, target_value, target_unit, target_time, target_pace, target_date, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
    """, (name, goal_type, target_value, target_unit, target_time, target_pace, target_date))
    goal_id = cursor.lastrowid
    log_goal_event(conn, goal_id, None, "goal_created", f"{name} ({goal_type})")
    conn.commit()
    logger.info("Goal created: %s (id=%d)", name, goal_id)
    return goal_id


def get_active_phase(conn: sqlite3.Connection, goal_id: int = None) -> dict | None:
    """Get the current active training phase, optionally filtered by goal."""
    if goal_id:
        row = conn.execute(
            "SELECT * FROM training_phases WHERE status = 'active' AND goal_id = ? LIMIT 1",
            (goal_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM training_phases WHERE status = 'active' LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def complete_phase(conn: sqlite3.Connection, phase_id: int, actuals: dict | None = None) -> None:
    """Mark a phase as completed, optionally with computed actuals."""
    if actuals:
        conn.execute(
            "UPDATE training_phases SET status = 'completed', actuals = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(actuals), phase_id),
        )
    else:
        conn.execute(
            "UPDATE training_phases SET status = 'completed', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (phase_id,),
        )
    conn.commit()
    logger.info("Phase %d completed", phase_id)


def revise_phase(conn: sqlite3.Connection, phase_id: int, new_targets: dict, reason: str) -> int:
    """Revise a phase: mark current as 'revised', create new version, log the change.

    Returns the new phase ID.
    """
    old = conn.execute("SELECT * FROM training_phases WHERE id = ?", (phase_id,)).fetchone()
    if not old:
        raise ValueError(f"Phase {phase_id} not found")

    old_targets = json.loads(old["targets"]) if old["targets"] else {}

    # Mark old as revised
    conn.execute(
        "UPDATE training_phases SET status = 'revised', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (phase_id,),
    )

    # Create new version
    cursor = conn.execute("""
        INSERT INTO training_phases (goal_id, phase, name, start_date, end_date,
            z12_pct_target, z45_pct_target, weekly_km_min, weekly_km_max,
            targets, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """, (
        old["goal_id"], old["phase"], old["name"], old["start_date"], old["end_date"],
        new_targets.get("z12_pct_target", old["z12_pct_target"]),
        new_targets.get("z45_pct_target", old["z45_pct_target"]),
        new_targets.get("weekly_km_min", old["weekly_km_min"]),
        new_targets.get("weekly_km_max", old["weekly_km_max"]),
        json.dumps(new_targets),
    ))
    new_id = cursor.lastrowid

    # Log the revision
    log_goal_event(conn, old["goal_id"], phase_id, "phase_revised", reason,
                   previous_value=old_targets, new_value=new_targets)

    conn.commit()
    logger.info("Phase %d revised → new phase %d: %s", phase_id, new_id, reason)
    return new_id


def log_goal_event(conn: sqlite3.Connection, goal_id: int, phase_id: int | None,
                   event_type: str, description: str,
                   previous_value: dict | None = None, new_value: dict | None = None) -> None:
    """Log a goal-related event to the goal_log table."""
    conn.execute("""
        INSERT INTO goal_log (date, goal_id, phase_id, type, description, previous_value, new_value)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        date.today().isoformat(), goal_id, phase_id, event_type, description,
        json.dumps(previous_value) if previous_value else None,
        json.dumps(new_value) if new_value else None,
    ))


def get_target_race(conn: sqlite3.Connection) -> dict | None:
    """Get the target race — the organizing anchor for the dashboard.

    Priority: (1) the race that active goals reference via race_id,
    (2) the furthest registered future race (marathon > half > 10K),
    (3) the nearest registered future race as fallback.
    """
    # 1. Race linked to active goals (the explicit anchor)
    row = conn.execute("""
        SELECT rc.* FROM race_calendar rc
        INNER JOIN goals g ON g.race_id = rc.id
        WHERE g.active = 1 AND rc.date >= date('now')
        ORDER BY rc.distance_km DESC
        LIMIT 1
    """).fetchone()
    if row:
        return dict(row)

    # 2. Furthest future registered race (prefer longest distance)
    row = conn.execute("""
        SELECT * FROM race_calendar
        WHERE date >= date('now') AND status IN ('registered', 'planned')
        ORDER BY distance_km DESC, date DESC
        LIMIT 1
    """).fetchone()
    if row:
        return dict(row)

    # 3. Nearest future race as last resort
    row = conn.execute("""
        SELECT * FROM race_calendar
        WHERE date >= date('now') AND status IN ('registered', 'planned')
        ORDER BY date ASC LIMIT 1
    """).fetchone()
    return dict(row) if row else None


def get_next_race(conn: sqlite3.Connection) -> dict | None:
    """Get the nearest upcoming race (for 'next race' countdown, not the anchor)."""
    row = conn.execute("""
        SELECT * FROM race_calendar
        WHERE date >= date('now') AND status IN ('registered', 'planned')
        ORDER BY date ASC LIMIT 1
    """).fetchone()
    return dict(row) if row else None


def get_race_calendar_upcoming(conn: sqlite3.Connection) -> list[dict]:
    """Get all upcoming races as waypoints."""
    rows = conn.execute("""
        SELECT * FROM race_calendar
        WHERE date >= date('now') AND status IN ('registered', 'planned')
        ORDER BY date ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_phase_compliance(conn: sqlite3.Connection, phase_id: int) -> dict:
    """Compare current weekly_agg averages to phase targets.

    Returns dict with each target dimension: target, actual, on_track (bool).
    """
    phase = conn.execute("SELECT * FROM training_phases WHERE id = ?", (phase_id,)).fetchone()
    if not phase:
        return {}

    # Get recent weekly_agg (last 2 weeks within the phase period)
    recent = conn.execute("""
        SELECT * FROM weekly_agg
        WHERE week >= ? ORDER BY week DESC LIMIT 2
    """, (phase["start_date"] or "2000-01-01",)).fetchall()

    if not recent:
        return {"status": "no_data", "dimensions": []}

    # Average the recent weeks
    def avg(field):
        vals = [r[field] for r in recent if r[field] is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    dimensions = []

    # Zone compliance
    if phase["z12_pct_target"]:
        actual = avg("z12_pct")
        dimensions.append({
            "name": "Z1+Z2 time %", "target": phase["z12_pct_target"],
            "actual": actual, "on_track": actual >= phase["z12_pct_target"] * 0.9 if actual else False,
        })

    # Volume
    if phase["weekly_km_min"]:
        actual = avg("run_km")
        dimensions.append({
            "name": "Weekly km", "target_range": [phase["weekly_km_min"], phase["weekly_km_max"]],
            "actual": actual,
            "on_track": (phase["weekly_km_min"] <= actual <= phase["weekly_km_max"]) if actual else False,
        })

    # Parse JSON targets for additional dimensions
    targets = json.loads(phase["targets"]) if phase["targets"] else {}

    if "run_frequency" in targets:
        actual = avg("run_count")
        freq = targets["run_frequency"]
        dimensions.append({
            "name": "Runs/week", "target_range": freq,
            "actual": actual,
            "on_track": (freq[0] <= actual <= freq[1]) if actual else False,
        })

    if "acwr_range" in targets:
        actual = avg("acwr")
        acwr_range = targets["acwr_range"]
        dimensions.append({
            "name": "ACWR", "target_range": acwr_range,
            "actual": actual,
            "on_track": (acwr_range[0] <= actual <= acwr_range[1]) if actual else None,
        })

    return {"status": "active", "dimensions": dimensions}
