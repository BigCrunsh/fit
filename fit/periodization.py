"""Run Story narrative synthesis + periodization feedback loop + heat acclimatization + race-day pacing."""

import json
import logging
import sqlite3
from datetime import date

from fit.analysis import RUNNING_TYPES_SQL

logger = logging.getLogger(__name__)


# ── Run Story ──


def generate_run_story(conn: sqlite3.Connection, config: dict) -> dict | None:
    """Synthesize a narrative for the most recent long run.

    Combines: splits (if available), correlations, checkin, weather.
    Degrades gracefully without .fit data (uses per-run averages).
    """
    # Find most recent long run
    long_run = conn.execute(f"""
        SELECT a.id, a.date, a.name, a.distance_km, a.duration_min,
               a.avg_hr, a.pace_sec_per_km, a.speed_per_bpm, a.run_type,
               a.temp_at_start_c, a.humidity_at_start_pct, a.splits_status,
               a.training_load, a.hr_zone
        FROM activities a
        WHERE a.type IN {RUNNING_TYPES_SQL} AND a.run_type = 'long'
        ORDER BY a.date DESC LIMIT 1
    """).fetchone()

    if not long_run:
        return None

    story = {
        "date": long_run["date"],
        "name": long_run["name"],
        "distance_km": long_run["distance_km"],
        "duration_min": long_run["duration_min"],
        "avg_hr": long_run["avg_hr"],
        "avg_pace": _format_pace(long_run["pace_sec_per_km"]),
        "efficiency": long_run["speed_per_bpm"],
    }

    # Get preceding checkin
    checkin = conn.execute("""
        SELECT alcohol, sleep_quality, rpe, legs, energy, hydration
        FROM checkins WHERE date = date(?, '-1 day')
    """, (long_run["date"],)).fetchone()

    if checkin:
        story["checkin"] = {
            "alcohol": checkin["alcohol"],
            "sleep_quality": checkin["sleep_quality"],
            "legs": checkin["legs"],
            "energy": checkin["energy"],
        }

    # Get weather
    weather = conn.execute(
        "SELECT temp_c, humidity_pct, conditions FROM weather WHERE date = ?",
        (long_run["date"],),
    ).fetchone()
    if weather:
        story["weather"] = dict(weather)

    # Try splits data
    splits = conn.execute("""
        SELECT * FROM activity_splits WHERE activity_id = ? ORDER BY split_num
    """, (long_run["id"],)).fetchall()

    if splits:
        story["has_splits"] = True
        story["splits_summary"] = _summarize_splits(splits, long_run)
    else:
        story["has_splits"] = False

    # Build narrative text
    story["narrative"] = _compose_run_story_text(story, config)

    return story


def _summarize_splits(splits: list, run: dict) -> dict:
    """Summarize split data for the Run Story."""
    split_dicts = [dict(s) for s in splits]
    n = len(split_dicts)
    if n == 0:
        return {}

    # Find drift onset (if any)
    drift_onset = None
    if n >= 4:
        first_half_hr = [s["avg_hr"] for s in split_dicts[:n // 2] if s.get("avg_hr")]
        if first_half_hr:
            baseline_hr = sum(first_half_hr) / len(first_half_hr)
            for s in split_dicts[n // 2:]:
                if s.get("avg_hr") and s["avg_hr"] > baseline_hr * 1.05:
                    drift_onset = s["split_num"]
                    break

    # Pace consistency
    paces = [s["pace_sec_per_km"] for s in split_dicts if s.get("pace_sec_per_km")]
    first_half_pace = paces[:n // 2] if paces else []
    second_half_pace = paces[n // 2:] if paces else []

    return {
        "n_splits": n,
        "drift_onset_km": drift_onset,
        "avg_pace_first_half": _format_pace(sum(first_half_pace) / len(first_half_pace)) if first_half_pace else None,
        "avg_pace_second_half": _format_pace(sum(second_half_pace) / len(second_half_pace)) if second_half_pace else None,
    }


def _compose_run_story_text(story: dict, config: dict) -> str:
    """Compose human-readable Run Story paragraph."""
    parts = []
    dist = story.get("distance_km", 0)
    day_name = _day_of_week(story.get("date", ""))

    parts.append(f"{day_name}'s {dist:.0f}km")

    if story.get("has_splits") and story.get("splits_summary"):
        ss = story["splits_summary"]
        if ss.get("avg_pace_first_half"):
            parts.append(f"held {ss['avg_pace_first_half']} through km {ss['n_splits'] // 2}")
            if ss.get("avg_pace_second_half") and ss.get("drift_onset_km"):
                parts.append(f"then faded to {ss['avg_pace_second_half']}")
    else:
        parts.append(f"avg {story.get('avg_pace', '?')}/km at HR {story.get('avg_hr', '?')}")
        if story.get("efficiency"):
            parts.append(f"(efficiency {story['efficiency']:.3f})")

    # Checkin context
    if story.get("checkin"):
        ci = story["checkin"]
        factors = []
        if ci.get("alcohol") and ci["alcohol"] >= 1:
            factors.append(f"{ci['alcohol']:.0f} drink{'s' if ci['alcohol'] > 1 else ''} the night before")
        if ci.get("sleep_quality") == "Poor":
            factors.append("poor sleep")
        if ci.get("legs") == "Heavy":
            factors.append("heavy legs")
        if factors:
            parts.append(". ".join(factors))

    # Weather
    if story.get("weather") and story["weather"].get("temp_c"):
        w = story["weather"]
        parts.append(f"{w['temp_c']:.0f}°C, {w.get('conditions', '')}")

    return ". ".join(p for p in parts if p) + "."


# ── Periodization Feedback Loop ──


def evaluate_phase_readiness(conn: sqlite3.Connection) -> dict | None:
    """Detect if current phase should advance, extend, or deload.

    Returns recommendation dict or None if no active phase.
    """
    phase = conn.execute(
        "SELECT * FROM training_phases WHERE status = 'active' LIMIT 1"
    ).fetchone()
    if not phase:
        return None

    targets = json.loads(phase["targets"]) if phase["targets"] else {}

    # Get recent weekly_agg (last 3 weeks within phase)
    recent_weeks = conn.execute("""
        SELECT * FROM weekly_agg
        WHERE week >= ? ORDER BY week DESC LIMIT 4
    """, (phase["start_date"] or "2000-01-01",)).fetchall()

    if len(recent_weeks) < 2:
        return {"action": "insufficient_data", "message": "Need 2+ weeks in phase to evaluate"}

    result = {"phase": dict(phase), "weeks_in_phase": len(recent_weeks)}

    # Check if objectives met for 2+ consecutive weeks
    objectives_met = _check_objectives_met(recent_weeks, phase, targets)
    if objectives_met >= 2:
        result["action"] = "advance"
        result["message"] = (
            f"Phase {phase['phase']} objectives met for {objectives_met} consecutive weeks "
            f"— ready to advance to next phase"
        )
        return result

    # Check if struggling (below target for 3+ weeks)
    below_target_weeks = _count_below_target(recent_weeks, phase)
    if below_target_weeks >= 3:
        result["action"] = "extend"
        result["message"] = (
            f"Below volume target for {below_target_weeks} weeks "
            f"— consider extending {phase['name']}"
        )
        return result

    # Check deload need
    build_weeks = _count_consecutive_build_weeks(recent_weeks)
    if build_weeks >= 4:
        result["action"] = "deload"
        result["message"] = (
            f"No recovery week in {build_weeks} weeks "
            f"— schedule a deload (30-40% volume reduction)"
        )
        return result

    # Check taper (if race within 3 weeks)
    target_race = conn.execute("""
        SELECT * FROM race_calendar
        WHERE date >= date('now') AND status IN ('registered', 'planned')
        ORDER BY date ASC LIMIT 1
    """).fetchone()
    if target_race:
        race_date = date.fromisoformat(target_race["date"])
        days_to_race = (race_date - date.today()).days
        if days_to_race <= 21:
            result["action"] = "taper"
            result["message"] = (
                f"{days_to_race} days to {target_race['name']} "
                f"— begin taper: volume drops 40-60%, maintain intensity, "
                f"last quality session ~10 days out"
            )
            return result

    result["action"] = "continue"
    result["message"] = f"Phase {phase['phase']} on track — continue current plan"
    return result


def _check_objectives_met(weeks: list, phase, targets: dict) -> int:
    """Count consecutive weeks where phase objectives are met."""
    met_streak = 0
    for w in weeks:
        met = True
        # Z2 compliance
        if phase["z12_pct_target"] and w["z12_pct"] is not None:
            if w["z12_pct"] < phase["z12_pct_target"] * 0.9:
                met = False
        # Volume range
        if phase["weekly_km_min"] and w["run_km"] is not None:
            if w["run_km"] < phase["weekly_km_min"]:
                met = False
        if met:
            met_streak += 1
        else:
            break
    return met_streak


def _count_below_target(weeks: list, phase) -> int:
    """Count consecutive weeks below volume target."""
    below = 0
    for w in weeks:
        if phase["weekly_km_min"] and w["run_km"] is not None:
            if w["run_km"] < phase["weekly_km_min"] * 0.8:
                below += 1
            else:
                break
        else:
            break
    return below


def _count_consecutive_build_weeks(weeks: list) -> int:
    """Count consecutive build weeks (no deload = volume drop ≥30%)."""
    if len(weeks) < 2:
        return len(weeks)
    build = 1
    for i in range(1, len(weeks)):
        prev_km = weeks[i]["run_km"] or 0
        curr_km = weeks[i - 1]["run_km"] or 0
        if prev_km > 0 and curr_km >= prev_km * 0.7:
            build += 1
        else:
            break
    return build


# ── Heat Acclimatization Tracker ──


def compute_heat_acclimatization(conn: sqlite3.Connection) -> dict | None:
    """Track temperature-adjusted efficiency over time.

    Returns heat acclimatization trend and race-day projection.
    """
    # Get runs with temperature data in the last 8 weeks
    hot_runs = conn.execute(f"""
        SELECT date, speed_per_bpm, temp_at_start_c, humidity_at_start_pct
        FROM activities
        WHERE type IN {RUNNING_TYPES_SQL} AND temp_at_start_c IS NOT NULL
            AND temp_at_start_c > 20
            AND date >= date('now', '-56 days')
        ORDER BY date
    """).fetchall()

    if len(hot_runs) < 3:
        return None

    # Compute trend: is efficiency in heat improving?
    efficiencies = [(r["date"], r["speed_per_bpm"], r["temp_at_start_c"]) for r in hot_runs if r["speed_per_bpm"]]
    if len(efficiencies) < 3:
        return None

    first_half = efficiencies[:len(efficiencies) // 2]
    second_half = efficiencies[len(efficiencies) // 2:]

    avg_first = sum(e[1] for e in first_half) / len(first_half)
    avg_second = sum(e[1] for e in second_half) / len(second_half)
    trend_pct = ((avg_second - avg_first) / avg_first * 100) if avg_first > 0 else 0

    # Race-day projection (Berlin late September: ~15°C)
    race_temp = 15
    cool_runs = conn.execute(f"""
        SELECT AVG(speed_per_bpm) as avg_eff FROM activities
        WHERE type IN {RUNNING_TYPES_SQL} AND temp_at_start_c IS NOT NULL
            AND temp_at_start_c BETWEEN 10 AND 20
            AND date >= date('now', '-56 days')
    """).fetchone()

    return {
        "hot_runs_count": len(hot_runs),
        "trend_pct": round(trend_pct, 1),
        "improving": trend_pct > 2,
        "avg_hot_efficiency": round(avg_second, 4),
        "avg_cool_efficiency": round(cool_runs["avg_eff"], 4) if cool_runs and cool_runs["avg_eff"] else None,
        "race_temp_projection": race_temp,
        "message": (
            f"Heat efficiency {'improving' if trend_pct > 2 else 'stable'} "
            f"({trend_pct:+.1f}% over {len(hot_runs)} hot runs). "
            f"Race day forecast ~{race_temp}°C — conditions will be favorable."
        ),
    }


# ── Race-Day Pacing Strategy ──


def generate_pacing_strategy(
    prediction_seconds: int, config: dict, target_km: float = 42.195
) -> dict:
    """Translate a race prediction into a race-day pacing plan.

    Adapts segment count, HR ceilings, and fueling to the target distance:
    - Marathon (>30km): 8×5km + remainder, 5 gels
    - Half marathon (15-30km): 4×5km + remainder, 2 gels
    - 10K and under (≤15km): 2×5km + remainder, 0-1 gel

    Returns: target splits per segment, HR ceiling per phase, fueling timing.
    """
    target_pace = prediction_seconds / target_km  # sec/km
    half_km = target_km / 2

    # Build segments: 5km chunks + final remainder
    segments = []
    km = 0.0
    while km < target_km:
        start_km = km
        end_km = min(km + 5, target_km)
        segment_km = end_km - start_km

        # Even-split with slight negative split
        if start_km < half_km:
            pace_adj = target_pace + 2  # conservative first half
        elif start_km < target_km * 0.83:
            pace_adj = target_pace  # on pace
        else:
            pace_adj = target_pace - 1  # slight push final segment(s)

        segment_time = pace_adj * segment_km
        segments.append({
            "start_km": start_km,
            "end_km": round(end_km, 1),
            "pace_sec_km": round(pace_adj),
            "pace_display": _format_pace(pace_adj),
            "segment_time_sec": round(segment_time),
            "cumulative_km": round(end_km, 1),
        })
        km = end_km

    # HR ceilings adapt to distance
    max_hr = config.get("profile", {}).get("max_hr", 192)
    if target_km > 30:  # marathon
        hr_ceilings = {
            f"0-{int(target_km * 0.36)}km": int(max_hr * 0.78),
            f"{int(target_km * 0.36)}-{int(target_km * 0.71)}km": int(max_hr * 0.82),
            f"{int(target_km * 0.71)}-{int(target_km)}km": int(max_hr * 0.87),
        }
    elif target_km > 15:  # half marathon
        hr_ceilings = {
            f"0-{int(half_km)}km": int(max_hr * 0.80),
            f"{int(half_km)}-{int(target_km)}km": int(max_hr * 0.85),
        }
    else:  # 10K and under
        hr_ceilings = {
            f"0-{int(half_km)}km": int(max_hr * 0.83),
            f"{int(half_km)}-{int(target_km)}km": int(max_hr * 0.88),
        }

    # Fueling plan scales with duration
    est_time_min = prediction_seconds / 60
    fueling = []
    if est_time_min > 60:  # only fuel for races > 1 hour
        t = 45
        while t < est_time_min - 10:
            item = "gel + water" if len(fueling) % 2 == 0 else "gel"
            fueling.append({"time_min": t, "item": item})
            t += 30

    total_time = sum(s["segment_time_sec"] for s in segments)
    return {
        "target_time_sec": prediction_seconds,
        "target_km": target_km,
        "target_pace_display": _format_pace(target_pace),
        "segments": segments,
        "hr_ceilings": hr_ceilings,
        "fueling": fueling,
        "total_estimated_sec": round(total_time),
        "total_estimated_display": _format_time(round(total_time)),
    }


# ── Helpers ──


def _format_pace(sec_per_km: float | None) -> str:
    """Format pace as M:SS/km."""
    if sec_per_km is None or sec_per_km <= 0:
        return "—"
    minutes = int(sec_per_km // 60)
    seconds = int(sec_per_km % 60)
    return f"{minutes}:{seconds:02d}"


def _format_time(total_seconds: int) -> str:
    """Format total seconds as H:MM:SS."""
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours}:{minutes:02d}:{seconds:02d}"


def _day_of_week(date_str: str) -> str:
    """Get day name from date string."""
    try:
        d = date.fromisoformat(date_str)
        return d.strftime("%A")
    except (ValueError, TypeError):
        return "Recent"
