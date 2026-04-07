"""Rule-based trend narratives and story connectors for the dashboard."""

import logging
import sqlite3
from datetime import date

logger = logging.getLogger(__name__)


# ── 3.1: Trend Badges ──


def generate_trend_badges(conn: sqlite3.Connection) -> list[dict]:
    """Generate 'This Month' trend badges as pill-style indicators.

    Returns list of badge dicts: {metric, direction, value, color, detail}.
    Minimum data threshold: 4+ weeks for trends. Below: returns fallback.
    """
    weeks = conn.execute(
        "SELECT * FROM weekly_agg ORDER BY week DESC LIMIT 8"
    ).fetchall()

    if len(weeks) < 4:
        weeks_needed = 4 - len(weeks)
        return [{
            "metric": "insufficient_data",
            "direction": "none",
            "value": f"Keep logging — {weeks_needed} more week{'s' if weeks_needed != 1 else ''} until trends emerge.",
            "color": "gray",
            "detail": None,
        }]

    badges = []

    # Efficiency: compare last 4 weeks avg vs prior 4 weeks
    eff_recent = conn.execute("""
        SELECT AVG(speed_per_bpm_z2) as avg_eff FROM activities
        WHERE type='running' AND speed_per_bpm_z2 IS NOT NULL
        AND date >= date('now', '-28 days')
    """).fetchone()
    eff_prior = conn.execute("""
        SELECT AVG(speed_per_bpm_z2) as avg_eff FROM activities
        WHERE type='running' AND speed_per_bpm_z2 IS NOT NULL
        AND date >= date('now', '-56 days') AND date < date('now', '-28 days')
    """).fetchone()

    if eff_recent and eff_prior and eff_recent["avg_eff"] and eff_prior["avg_eff"]:
        recent_val = eff_recent["avg_eff"]
        prior_val = eff_prior["avg_eff"]
        if prior_val > 0:
            pct_change = ((recent_val - prior_val) / prior_val) * 100
            if pct_change > 2:
                color = "green"
                direction = "up"
            elif pct_change < -2:
                color = "red"
                direction = "down"
            else:
                color = "gray"
                direction = "flat"
            badges.append({
                "metric": "Efficiency",
                "direction": direction,
                "value": f"{pct_change:+.0f}%",
                "color": color,
                "detail": f"Z2 speed/bpm: {recent_val:.3f} vs {prior_val:.3f} (4wk avg)",
            })

    # VO2max: latest vs 4-week-ago
    vo2_latest = conn.execute(
        "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    vo2_4wk = conn.execute(
        "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL AND date <= date('now', '-28 days') ORDER BY date DESC LIMIT 1"
    ).fetchone()

    if vo2_latest and vo2_4wk and vo2_latest["vo2max"] and vo2_4wk["vo2max"]:
        diff = vo2_latest["vo2max"] - vo2_4wk["vo2max"]
        if vo2_4wk["vo2max"] > 0:
            pct = (diff / vo2_4wk["vo2max"]) * 100
            if pct > 2:
                color = "green"
                direction = "up"
            elif pct < -2:
                color = "red"
                direction = "down"
            else:
                color = "gray"
                direction = "flat"
            badges.append({
                "metric": "VO2max",
                "direction": direction,
                "value": f"{diff:+.0f}" if abs(diff) >= 1 else "flat",
                "color": color,
                "detail": f"{vo2_latest['vo2max']:.0f} vs {vo2_4wk['vo2max']:.0f} (4wk ago)",
            })

    # Z2 compliance: latest week z12_pct
    if weeks and weeks[0]["z12_pct"] is not None:
        z12 = weeks[0]["z12_pct"]
        if z12 >= 80:
            color = "green"
        elif z12 >= 50:
            color = "yellow"
        else:
            color = "red"
        badges.append({
            "metric": "Z2 compliance",
            "direction": "up" if z12 >= 80 else "down" if z12 < 50 else "flat",
            "value": f"{z12:.0f}%",
            "color": color,
            "detail": f"Z1+Z2 time this week: {z12:.0f}% (target: >=80%)",
        })

    # Volume: latest week run_km (informational, always blue)
    if weeks and weeks[0]["run_km"] is not None:
        km = weeks[0]["run_km"]
        badges.append({
            "metric": "Volume",
            "direction": "info",
            "value": f"{km:.0f}km/wk",
            "color": "blue",
            "detail": f"This week: {km:.1f}km across {weeks[0]['run_count'] or 0} runs",
        })

    return badges


# ── 3.3: Why Connectors ──


def generate_why_connectors(conn: sqlite3.Connection) -> list[dict]:
    """Find patterns linking worst runs to preceding day's checkin data.

    Returns list of connector dicts with pattern descriptions and run dates.
    """
    # Check data sufficiency
    run_count = conn.execute("""
        SELECT COUNT(*) as n FROM activities a
        JOIN checkins c ON a.date = c.date OR c.date = date(a.date, '-1 day')
        WHERE a.type = 'running' AND a.speed_per_bpm IS NOT NULL
    """).fetchone()

    if not run_count or run_count["n"] < 10:
        return [{
            "pattern": "insufficient_data",
            "message": "Need 10+ runs with checkin data to detect patterns.",
            "runs": [],
        }]

    # Get 5 worst efficiency runs (lowest speed_per_bpm)
    worst_runs = conn.execute("""
        SELECT a.id, a.date, a.speed_per_bpm, a.name,
               c.sleep_quality, c.alcohol, c.alcohol_detail
        FROM activities a
        LEFT JOIN checkins c ON c.date = date(a.date, '-1 day')
        WHERE a.type = 'running' AND a.speed_per_bpm IS NOT NULL
        ORDER BY a.speed_per_bpm ASC LIMIT 5
    """).fetchall()

    if not worst_runs:
        return []

    connectors = []

    # Check preceding day checkin patterns
    sleep_poor_count = 0
    alcohol_count = 0
    poor_sleep_runs = []
    alcohol_runs = []

    for run in worst_runs:
        # Check preceding day's health data for sleep hours
        prev_health = conn.execute("""
            SELECT sleep_duration_hours FROM daily_health
            WHERE date = date(?, '-1 day')
        """, (run["date"],)).fetchone()

        if prev_health and prev_health["sleep_duration_hours"] is not None:
            if prev_health["sleep_duration_hours"] < 6:
                sleep_poor_count += 1
                poor_sleep_runs.append(run["date"])

        if run["sleep_quality"] == "Poor":
            sleep_poor_count += 1
            if run["date"] not in poor_sleep_runs:
                poor_sleep_runs.append(run["date"])

        if run["alcohol"] is not None and run["alcohol"] > 1:
            alcohol_count += 1
            alcohol_runs.append(run["date"])

    # Check cycling preceding worst runs
    cycling_runs = []
    for run in worst_runs:
        cycling = conn.execute("""
            SELECT SUM(distance_km) as km FROM activities
            WHERE type = 'cycling' AND date = date(?, '-1 day')
        """, (run["date"],)).fetchone()
        if cycling and cycling["km"] and cycling["km"] > 30:
            cycling_runs.append(run["date"])

    if sleep_poor_count >= 2:
        connectors.append({
            "pattern": "sleep_impact",
            "message": f"{sleep_poor_count} of your 5 worst runs followed <6h sleep",
            "runs": poor_sleep_runs,
        })

    if alcohol_count >= 2:
        connectors.append({
            "pattern": "alcohol_impact",
            "message": f"{alcohol_count} of your 5 worst runs followed >1 drink",
            "runs": alcohol_runs,
        })

    if len(cycling_runs) >= 2:
        connectors.append({
            "pattern": "cycling_fatigue",
            "message": f"{len(cycling_runs)} of your 5 worst runs followed >30km cycling",
            "runs": cycling_runs,
        })

    return connectors


# ── 3.4: Week-over-Week with Phase Context ──


def generate_wow_context(conn: sqlite3.Connection) -> dict | None:
    """Compare latest 2 weeks with phase target context.

    Returns dict with volume_change, phase_warning, and summary text.
    """
    weeks = conn.execute(
        "SELECT * FROM weekly_agg ORDER BY week DESC LIMIT 2"
    ).fetchall()
    if len(weeks) < 2:
        return None

    this_wk, last_wk = weeks[0], weeks[1]
    this_km = this_wk["run_km"] or 0
    last_km = last_wk["run_km"] or 0

    result = {
        "this_week": this_wk["week"],
        "last_week": last_wk["week"],
        "volume_km": this_km,
        "volume_change_km": this_km - last_km,
        "volume_change_pct": ((this_km - last_km) / last_km * 100) if last_km > 0 else 0,
        "phase_warning": None,
        "summary": "",
    }

    # Check active phase targets
    phase = conn.execute(
        "SELECT * FROM training_phases WHERE status = 'active' LIMIT 1"
    ).fetchone()

    warnings = []
    if phase:
        import json
        targets = json.loads(phase["targets"]) if phase["targets"] else {}

        # Volume ramp check
        max_ramp = targets.get("max_volume_increase_pct", 10)
        if last_km > 0 and result["volume_change_pct"] > max_ramp:
            warnings.append(
                f"Volume up {result['volume_change_pct']:.0f}% — "
                f"{phase['phase']} target is <={max_ramp}%"
            )

        # Volume range check
        if phase["weekly_km_min"] and phase["weekly_km_max"]:
            if this_km < phase["weekly_km_min"]:
                warnings.append(
                    f"Volume {this_km:.0f}km below {phase['phase']} min "
                    f"({phase['weekly_km_min']:.0f}km)"
                )
            elif this_km > phase["weekly_km_max"]:
                warnings.append(
                    f"Volume {this_km:.0f}km above {phase['phase']} max "
                    f"({phase['weekly_km_max']:.0f}km)"
                )

        # Z2 compliance check
        if phase["z12_pct_target"] and this_wk["z12_pct"] is not None:
            if this_wk["z12_pct"] < phase["z12_pct_target"] * 0.9:
                warnings.append(
                    f"Z1+Z2 at {this_wk['z12_pct']:.0f}% — "
                    f"target is {phase['z12_pct_target']:.0f}%"
                )

    result["phase_warning"] = "; ".join(warnings) if warnings else None

    # Build summary
    sign = "+" if result["volume_change_km"] >= 0 else ""
    parts = [f"{this_km:.0f}km ({sign}{result['volume_change_km']:.0f}km)"]
    if result["phase_warning"]:
        parts.append(result["phase_warning"])
    result["summary"] = " — ".join(parts)

    return result


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


# ── 3.7: Walk-Break Detection ──


def detect_walk_break_need(conn: sqlite3.Connection) -> dict | None:
    """Check recent Z2 runs for cardiac drift or pace fade.

    Returns suggestion dict or None if not applicable.
    Without split-level data, uses per-run pace variability as proxy.
    """
    # Get recent Z2 runs
    z2_runs = conn.execute("""
        SELECT id, date, distance_km, duration_min, pace_sec_per_km,
               avg_hr, speed_per_bpm
        FROM activities
        WHERE type = 'running' AND hr_zone IN ('Z1', 'Z2')
        AND date >= date('now', '-42 days')
        ORDER BY date DESC LIMIT 10
    """).fetchall()

    if len(z2_runs) < 3:
        return None

    # Without split data, we use a proxy: check if efficiency degrades
    # significantly on longer runs (suggesting drift)
    short_runs = [r for r in z2_runs if r["distance_km"] and r["distance_km"] < 5]
    long_runs = [r for r in z2_runs if r["distance_km"] and r["distance_km"] >= 5]

    if not short_runs or not long_runs:
        return None

    short_eff = sum(r["speed_per_bpm"] for r in short_runs if r["speed_per_bpm"]) / max(
        len([r for r in short_runs if r["speed_per_bpm"]]), 1
    )
    long_eff = sum(r["speed_per_bpm"] for r in long_runs if r["speed_per_bpm"]) / max(
        len([r for r in long_runs if r["speed_per_bpm"]]), 1
    )

    if short_eff == 0:
        return None

    drift_pct = ((short_eff - long_eff) / short_eff) * 100

    if drift_pct < 5:
        # Check exit criteria: 3 consecutive Z2 runs with sustained efficiency
        recent_3 = z2_runs[:3]
        if all(
            r["distance_km"] and r["distance_km"] >= 8 and r["speed_per_bpm"]
            for r in recent_3
        ):
            efficiencies = [r["speed_per_bpm"] for r in recent_3]
            avg_eff = sum(efficiencies) / len(efficiencies)
            if all(abs(e - avg_eff) / avg_eff < 0.05 for e in efficiencies):
                return {
                    "status": "graduated",
                    "message": "3 consecutive Z2 runs with <5% drift through 8+km. "
                               "Run-walk no longer needed.",
                    "drift_pct": drift_pct,
                }
        return None

    # Drift detected
    result = {
        "status": "suggested",
        "drift_pct": round(drift_pct, 1),
        "message": f"Z2 runs show {drift_pct:.0f}% efficiency drop on runs >5km. "
                   "Consider structured run-walk intervals (e.g., 4:1 run:walk).",
        "exit_criteria": "Graduate when 3 consecutive Z2 runs sustain <5% drift through km 8.",
    }

    return result


# ── 3.10: Z2 Compliance Remediation ──


def generate_z2_remediation(conn: sqlite3.Connection, config: dict) -> dict | None:
    """Generate Z2 compliance remediation when compliance is low for 3+ weeks.

    Returns remediation dict with specific pace/HR targets, or None.
    """
    recent_weeks = conn.execute(
        "SELECT week, z12_pct FROM weekly_agg ORDER BY week DESC LIMIT 4"
    ).fetchall()

    if len(recent_weeks) < 3:
        return None

    # Check for 3+ consecutive weeks below 50%
    low_weeks = 0
    for w in recent_weeks[:3]:
        if w["z12_pct"] is not None and w["z12_pct"] < 50:
            low_weeks += 1
        else:
            break

    if low_weeks < 3:
        return None

    # Get zone boundaries from config
    zones = config.get("profile", {}).get("zones_max_hr", {})
    z2_bounds = zones.get("z2", [115, 134])

    avg_z12 = sum(
        w["z12_pct"] for w in recent_weeks[:3] if w["z12_pct"] is not None
    ) / max(low_weeks, 1)

    # Calculate target pace from recent Z2 runs
    z2_pace = conn.execute("""
        SELECT AVG(pace_sec_per_km) as avg_pace FROM activities
        WHERE type='running' AND hr_zone IN ('Z1', 'Z2')
        AND date >= date('now', '-21 days')
    """).fetchone()

    pace_suggestion = ""
    if z2_pace and z2_pace["avg_pace"]:
        pace_min = int(z2_pace["avg_pace"] // 60)
        pace_sec = int(z2_pace["avg_pace"] % 60)
        pace_suggestion = f"Your Z2 pace: ~{pace_min}:{pace_sec:02d}/km. "

    return {
        "status": "remediation",
        "low_weeks": low_weeks,
        "avg_z12_pct": round(avg_z12, 1),
        "hr_ceiling": z2_bounds[1],
        "hr_floor": z2_bounds[0],
        "message": (
            f"Z2 compliance below 50% for {low_weeks} consecutive weeks "
            f"(avg {avg_z12:.0f}%). "
            f"{pace_suggestion}"
            f"Keep HR between {z2_bounds[0]}-{z2_bounds[1]} bpm. "
            f"Slow down — if you can't hold a conversation, you're too fast."
        ),
    }
