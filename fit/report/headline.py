"""Rule-based headline engine for the Today tab."""

import sqlite3
from datetime import date


def generate_headline(readiness: int | None, acwr: float | None, phase: dict | None,
                      last_checkin_date: str | None, today: str = None,
                      sleep_quality: str | None = None,
                      conn: sqlite3.Connection | None = None,
                      config: dict | None = None) -> str:
    """Generate a daily headline sentence based on current state.

    If conn is provided, produces a race-anchored headline:
    "Berlin Marathon: 174 days -- Phase 1 of 4 -- prediction: 3:52"

    Falls back to the original rule-based headline when no race data is available.
    """
    # Try race-anchored headline first
    if conn is not None:
        race_headline = _race_anchored_headline(conn, phase)
        if race_headline:
            # Append safety/recovery signal if needed
            safety = _safety_signal(readiness, acwr, sleep_quality)
            if safety:
                return f"{race_headline} | {safety}"
            return race_headline

    # Fallback: original rule-based headline
    return _classic_headline(readiness, acwr, phase, last_checkin_date, today, sleep_quality)


def _race_anchored_headline(conn: sqlite3.Connection, phase: dict | None) -> str | None:
    """Build race-anchored headline: 'Race: N days -- Phase X of Y -- prediction: T'."""
    from fit.goals import get_target_race

    race = get_target_race(conn)
    if not race:
        return None

    days_left = (date.fromisoformat(race["date"]) - date.today()).days
    parts = [f"{race['name']}: {days_left} days"]

    # Phase position
    if phase:
        total_phases = conn.execute(
            "SELECT COUNT(*) FROM training_phases WHERE goal_id = ?",
            (phase["goal_id"],)
        ).fetchone()[0]
        phase_num = phase.get("phase", "Phase 1")
        # Extract number from "Phase 1" etc.
        num = ""
        for ch in str(phase_num):
            if ch.isdigit():
                num += ch
        if num and total_phases:
            parts.append(f"Phase {num} of {total_phases}")
        elif phase.get("name"):
            parts.append(phase["name"])

    # Latest race prediction
    try:
        from fit.analysis import predict_race_time
        races = conn.execute("""
            SELECT distance_km, result_time FROM race_calendar
            WHERE status = 'completed' AND result_time IS NOT NULL
            ORDER BY date DESC LIMIT 5
        """).fetchall()
        vo2_row = conn.execute(
            "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()

        def _parse_time(t):
            parts = t.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            return 0

        race_data = [
            {"distance_km": r["distance_km"], "time_seconds": _parse_time(r["result_time"])}
            for r in races if r["distance_km"] and r["result_time"]
        ]
        preds = predict_race_time(race_data, vo2max=vo2_row["vo2max"] if vo2_row else None)

        # Pick best prediction
        best_secs = None
        if preds.get("riegel"):
            best_secs = min(p["predicted_seconds"] for p in preds["riegel"])
        if preds.get("vdot"):
            vdot_secs = preds["vdot"]["predicted_seconds"]
            if best_secs is None or vdot_secs < best_secs:
                best_secs = vdot_secs

        if best_secs:
            hours = best_secs // 3600
            mins = (best_secs % 3600) // 60
            parts.append(f"prediction: {hours}:{mins:02d}")
    except Exception:
        pass  # Prediction is optional

    return " \u2014 ".join(parts)


def _safety_signal(readiness: int | None, acwr: float | None,
                   sleep_quality: str | None, heat_affected: bool = False) -> str | None:
    """Return a safety/recovery signal string, or None."""
    if sleep_quality == "Poor":
        return "Recovery day recommended"
    if readiness is not None and readiness < 50:
        return f"Recovery day (readiness {readiness})"
    if acwr is not None and acwr > 1.5:
        return f"Training spike ACWR {acwr:.2f}"
    if acwr is not None and acwr > 1.3:
        return f"ACWR {acwr:.2f} approaching limit"
    if heat_affected:
        return "Heat advisory: expect elevated HR, adjust zone targets"
    return None


def _classic_headline(readiness, acwr, phase, last_checkin_date, today, sleep_quality):
    """Original rule-based headline (fallback when no race data)."""
    parts = []

    # Recovery signal
    if sleep_quality == "Poor":
        parts.append("Recovery day recommended (sleep quality Poor).")
    elif readiness is not None:
        if readiness < 50:
            parts.append(f"Recovery day recommended (readiness {readiness}).")
        elif readiness >= 75:
            parts.append("Ready for training.")
        else:
            parts.append(f"Moderate readiness ({readiness}).")

    # ACWR safety
    if acwr is not None:
        if acwr > 1.5:
            parts.append(f"Training spike detected \u2014 ACWR {acwr:.2f}. Reduce load.")
        elif acwr > 1.3:
            parts.append(f"ACWR {acwr:.2f} approaching limit. Keep it easy.")
        elif acwr < 0.6:
            parts.append(f"ACWR {acwr:.2f} \u2014 detraining risk. Increase volume gradually.")

    # Phase-aware session suggestion
    if phase and readiness and readiness >= 50:
        phase_name = phase.get("name", "")
        quality_target = 0
        if phase.get("targets"):
            import json
            targets = json.loads(phase["targets"]) if isinstance(phase["targets"], str) else phase["targets"]
            qt = targets.get("quality_sessions_per_week", 0)
            quality_target = qt[0] if isinstance(qt, list) else qt

        if quality_target == 0:
            parts.append(f"{phase_name}: easy Z2 runs only, no hard efforts.")
        elif readiness >= 75:
            parts.append(f"{phase_name}: a quality session (tempo or intervals) is appropriate today.")
        else:
            parts.append(f"{phase_name}: easy run today, save quality for a high-readiness day.")

    # Stale checkin
    if last_checkin_date and today:
        if last_checkin_date < today:
            parts.append("No check-in today \u2014 run `fit checkin` before training.")

    if not parts:
        parts.append("Sync data to see your training headline.")

    return " ".join(parts)
