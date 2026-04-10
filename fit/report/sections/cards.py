"""Dashboard cards, panels, and small section generators."""

import json
import logging
from datetime import date
from pathlib import Path

from fit.analysis import RUNNING_TYPES_SQL
from fit.report.headline import generate_headline
from fit.narratives import (
    generate_trend_badges,
    generate_why_connectors,
    generate_race_countdown,
    detect_walk_break_need,
    generate_z2_remediation,
    generate_wow_sentence,
    generate_body_summary,
    generate_volume_story,
    generate_checkin_progress,
)

logger = logging.getLogger(__name__)

SAFE = "#34d399"
CAUTION = "#fbbf24"
DANGER = "#f87171"
Z1 = "#93c5fd"
Z2 = "#60a5fa"
Z3 = "#fbbf24"
Z4 = "#f97316"
Z5 = "#ef4444"
ACCENT = "#818cf8"



def _headline(conn):
    latest = conn.execute("SELECT training_readiness FROM daily_health ORDER BY date DESC LIMIT 1").fetchone()
    acwr_row = conn.execute("SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
    phase = conn.execute("SELECT * FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
    last_ci = conn.execute("SELECT date, sleep_quality FROM checkins ORDER BY date DESC LIMIT 1").fetchone()
    return generate_headline(
        readiness=latest["training_readiness"] if latest else None,
        acwr=acwr_row["acwr"] if acwr_row else None,
        phase=dict(phase) if phase else None,
        last_checkin_date=last_ci["date"] if last_ci else None,
        today=date.today().isoformat(),
        sleep_quality=last_ci["sleep_quality"] if last_ci else None,
        conn=conn,
    )


def _headline_signal(conn):
    """Daily coaching signal — readiness-based, not race info (that's in the card)."""
    h = conn.execute("SELECT training_readiness, sleep_duration_hours FROM daily_health ORDER BY date DESC LIMIT 1").fetchone()
    if not h or not h["training_readiness"]:
        return None
    r = h["training_readiness"]
    if r >= 75:
        return "Ready for a quality session today."
    elif r >= 50:
        return "Moderate readiness — easy run or rest recommended."
    elif r >= 25:
        return "Low readiness — rest or very easy activity only."
    else:
        return "Very low readiness — full rest day recommended."


def _prediction_summary(conn):
    """Compact prediction with confidence for the race card header.

    Shows range from multiple sources, not just VDOT point estimate.
    """
    try:
        from fit.analysis import predict_race_time
        races = conn.execute("""
            SELECT distance_km, result_time FROM race_calendar
            WHERE status = 'completed' AND result_time IS NOT NULL
            ORDER BY date DESC LIMIT 5
        """).fetchall()
        vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()

        def _parse_time(t):
            parts = t.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            return 0

        race_data = [{"distance_km": r["distance_km"], "time_seconds": _parse_time(r["result_time"])}
                     for r in races if r["distance_km"] and r["result_time"]]
        preds = predict_race_time(races=race_data, vo2max=vo2["vo2max"] if vo2 else None)

        # Collect all predictions
        all_secs = []
        if preds.get("riegel"):
            all_secs.extend(p["predicted_seconds"] for p in preds["riegel"])
        if preds.get("vdot") and preds["vdot"].get("predicted_seconds"):
            all_secs.append(preds["vdot"]["predicted_seconds"])

        if not all_secs:
            return None

        lo = min(all_secs)
        hi = max(all_secs)

        def _fmt(s):
            return f"{s // 3600}:{(s % 3600) // 60:02d}"

        confidence = preds.get("confidence", {})
        level = confidence.get("level", "low")
        level_label = {"high": "", "moderate": " (moderate confidence)", "low": " (low confidence)"}

        if hi - lo < 300:  # within 5 min — show single value
            return f"Prediction: {_fmt((lo + hi) // 2)}{level_label.get(level, '')}"
        else:
            return f"Prediction: {_fmt(lo)}–{_fmt(hi)}{level_label.get(level, '')}"
    except Exception:
        return None



def _status_cards(conn):
    cards = []
    h = conn.execute("SELECT * FROM daily_health ORDER BY date DESC LIMIT 1").fetchone()
    h4 = conn.execute("SELECT * FROM daily_health WHERE date <= date('now', '-28 days') ORDER BY date DESC LIMIT 1").fetchone()
    if not h:
        return cards

    def delta(current, prev, invert=False):
        if current is None or prev is None:
            return ""
        d = current - prev
        if d == 0:
            return "="
        arrow = "↓" if d < 0 else "↑"
        return f"{arrow}{abs(d):.0f}"

    r = h["training_readiness"]
    cards.append({"label": "Readiness", "value": r or "—", "unit": "",
                  "color": SAFE if r and r >= 75 else CAUTION if r and r >= 50 else DANGER,
                  "sub": delta(r, h4["training_readiness"] if h4 else None) + " 4wk" if h4 else "",
                  "tooltip": "Garmin composite score (0-100). ≥75 = ready for quality sessions. 50-74 = easy day. <50 = rest. Based on sleep, HRV, stress, and recent training load."})

    rhr = h["resting_heart_rate"]
    cards.append({"label": "RHR", "value": rhr or "—", "unit": "bpm",
                  "color": SAFE if rhr and rhr <= 58 else CAUTION,
                  "sub": delta(rhr, h4["resting_heart_rate"] if h4 else None, invert=True) + " 4wk" if h4 else "",
                  "tooltip": "Resting heart rate. Lower = fitter. Rising RHR signals fatigue, illness, or overtraining. Watch for trends, not single days."})

    sleep_sub = []
    if h["deep_sleep_hours"]:
        sleep_sub.append(f"D{h['deep_sleep_hours']:.1f}")
    try:
        if h["rem_sleep_hours"]:
            sleep_sub.append(f"R{h['rem_sleep_hours']:.1f}")
    except (IndexError, KeyError):
        pass
    cards.append({"label": "Sleep", "value": f"{h['sleep_duration_hours']:.1f}" if h["sleep_duration_hours"] else "—",
                  "unit": "h", "color": SAFE, "sub": " ".join(sleep_sub),
                  "tooltip": "Total sleep last night. D=deep (physical recovery), R=REM (cognitive). Target: ≥7.5h total, ≥1h deep, ≥1.5h REM."})

    hrv = h["hrv_last_night"]
    cards.append({"label": "HRV", "value": hrv or "—", "unit": "ms", "color": ACCENT,
                  "sub": delta(hrv, h4["hrv_last_night"] if h4 else None) + " 4wk" if h4 else "",
                  "tooltip": "Heart rate variability (last night). Higher = more recovered. Drops after hard efforts, alcohol, poor sleep. Trends matter more than single values."})

    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    vo2_peak = conn.execute("SELECT MAX(vo2max) as peak FROM activities WHERE vo2max IS NOT NULL").fetchone()
    vo2_4wk = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL AND date <= date('now', '-28 days') ORDER BY date DESC LIMIT 1").fetchone()
    vo2_sub = []
    if vo2_peak and vo2_peak["peak"]:
        vo2_sub.append(f"peak {vo2_peak['peak']}")
    if vo2 and vo2_4wk:
        vo2_sub.append(delta(vo2["vo2max"], vo2_4wk["vo2max"]) + " 4wk")
    cards.append({"label": "VO2max", "value": vo2["vo2max"] if vo2 else "—", "unit": "", "color": ACCENT,
                  "sub": " · ".join(vo2_sub)})

    w = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
    w_target = conn.execute("SELECT target_value FROM goals WHERE type = 'metric' AND name LIKE '%eight%' AND active = 1 LIMIT 1").fetchone()
    w_sub = []
    if w_target and w_target["target_value"]:
        w_sub.append(f"→ {w_target['target_value']}kg")
    cards.append({"label": "Weight", "value": f"{w['weight_kg']:.1f}" if w else "—", "unit": "kg", "color": CAUTION,
                  "sub": " · ".join(w_sub)})

    acwr = conn.execute("SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
    if acwr and acwr["acwr"]:
        v = acwr["acwr"]
        cards.append({"label": "ACWR", "value": f"{v:.2f}", "unit": "",
                      "color": SAFE if 0.8 <= v <= 1.3 else CAUTION if v <= 1.5 else DANGER,
                      "sub": "safe" if 0.8 <= v <= 1.3 else "caution" if v <= 1.5 else "DANGER"})

    streak = conn.execute("SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
    if streak and streak[0]:
        cards.append({"label": "Streak", "value": streak[0], "unit": "wk", "color": SAFE if streak[0] >= 4 else CAUTION, "sub": "3+ runs"})

    return cards


# ── Check-in ──

def _checkin(conn):
    row = conn.execute("SELECT * FROM checkins ORDER BY date DESC LIMIT 1").fetchone()
    if not row:
        return None
    fields = []
    if row["hydration"]:
        fields.append(f"💧 {row['hydration']}")
    if row["alcohol"] is not None:
        detail = f" ({row['alcohol_detail']})" if row["alcohol_detail"] else ""
        fields.append(f"🍺 {row['alcohol']}{detail}")
    if row["legs"]:
        fields.append(f"🦵 {row['legs']}")
    if row["eating"]:
        fields.append(f"🍽️ {row['eating']}")
    if row["water_liters"]:
        fields.append(f"💧 {row['water_liters']}L")
    if row["energy"]:
        fields.append(f"⚡ {row['energy']}")
    if row["sleep_quality"]:
        fields.append(f"😴 {row['sleep_quality']}")
    if row["rpe"] is not None:
        fields.append(f"💪 RPE {row['rpe']}")
    if row["notes"]:
        fields.append(row["notes"])
    return {"date": row["date"], "fields": fields}


# ── Journey Timeline ──

def _journey(conn):
    goal = conn.execute("SELECT * FROM goals WHERE active = 1 AND type = 'marathon' LIMIT 1").fetchone()
    if not goal:
        return None
    phases = conn.execute("SELECT * FROM training_phases WHERE goal_id = ? AND status != 'revised' ORDER BY start_date",
                          (goal["id"],)).fetchall()
    if not phases:
        return None

    colors = {"completed": "rgba(34,197,94,0.4)", "active": "rgba(129,140,248,0.5)", "planned": "rgba(255,255,255,0.08)"}
    segments = []
    position = ""
    for p in phases:
        # Build metric subtitle for each phase
        metric = ""
        if p["status"] == "completed" and p["actuals"]:
            import json as _json
            actuals = _json.loads(p["actuals"]) if isinstance(p["actuals"], str) else (p["actuals"] or {})
            metric = f" ({actuals.get('weekly_km_avg', '?')}km/wk)" if actuals else ""
        elif p["status"] == "active":
            metric = f" ({p['weekly_km_min'] or '?'}-{p['weekly_km_max'] or '?'}km)"
            position = f"You are here — {p['phase']}: {p['name']}"
        elif p["status"] == "planned":
            metric = f" ({p['weekly_km_min'] or '?'}-{p['weekly_km_max'] or '?'}km)"
        seg = {"label": f"{p['name'][:10]}{metric}", "width": 1, "color": colors.get(p["status"], colors["planned"])}
        segments.append(seg)

    return {"goal_name": f"{goal['name']} → {goal['target_date']}", "segments": segments, "position": position or "No active phase"}


# ── Week over Week ──

def _week_over_week(conn):
    """Narrative WoW sentence instead of raw numbers."""
    try:
        return generate_wow_sentence(conn)
    except Exception:
        return None


# ── Run Timeline ──

def _run_timeline(conn):
    runs = conn.execute(f"""
        SELECT date, distance_km, hr_zone, run_type, rpe FROM activities
        WHERE type IN {RUNNING_TYPES_SQL} ORDER BY date DESC LIMIT 12
    """).fetchall()
    max_km = max((r["distance_km"] or 0 for r in runs), default=1) or 1
    result = []
    prev_date = None
    for r in runs:
        km = r["distance_km"] or 0
        zone = r["hr_zone"] or "Z2"
        color = Z2 if zone in ("Z1", "Z2") else Z3 if zone == "Z3" else Z4
        # Detect gap from previous run (list is DESC, so prev_date is more recent)
        gap_days = None
        if prev_date:
            d1 = date.fromisoformat(r["date"])
            d2 = date.fromisoformat(prev_date)
            gap = (d2 - d1).days
            if gap > 14:
                gap_days = gap
        prev_date = r["date"]
        result.append({
            "date": r["date"][5:],  # MM-DD
            "distance_km": f"{km:.1f}",
            "gap_days": gap_days,
            "width": max(10, int(km / max_km * 100)),
            "color": color,
            "zone": zone,
            "run_type": r["run_type"] or "",
            "rpe": r["rpe"],
        })
    return result



def _definitions(conn):
    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    vo2_val = vo2["vo2max"] if vo2 else "?"
    acwr_row = conn.execute("SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
    acwr_val = f"{acwr_row['acwr']:.2f}" if acwr_row else "?"
    weight_row = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
    weight_val = f"{weight_row['weight_kg']:.1f}" if weight_row else "?"
    # Get actual values for contextual definitions
    avg_sleep = conn.execute("SELECT ROUND(AVG(sleep_duration_hours), 1) as v FROM daily_health WHERE date >= date('now', '-14 days')").fetchone()
    avg_sleep_val = avg_sleep["v"] if avg_sleep and avg_sleep["v"] else "?"
    avg_deep = conn.execute("SELECT ROUND(AVG(deep_sleep_hours), 2) as v FROM daily_health WHERE date >= date('now', '-14 days')").fetchone()
    avg_deep_val = avg_deep["v"] if avg_deep and avg_deep["v"] else "?"
    avg_cadence = conn.execute(f"SELECT ROUND(AVG(avg_cadence), 0) as v FROM activities WHERE type IN {RUNNING_TYPES_SQL} AND avg_cadence IS NOT NULL AND date >= date('now', '-30 days')").fetchone()
    avg_cadence_val = avg_cadence["v"] if avg_cadence and avg_cadence["v"] else "?"
    avg_stress = conn.execute("SELECT ROUND(AVG(avg_stress_level), 0) as v FROM daily_health WHERE date >= date('now', '-7 days')").fetchone()
    avg_stress_val = avg_stress["v"] if avg_stress and avg_stress["v"] else "?"

    return {
        "speed_per_bpm": "Speed per heartbeat: (meters/min) ÷ avg HR. Higher = more efficient. The Z2-filtered line (bold) shows pure aerobic fitness at controlled effort — the most honest fitness signal.",
        "vo2max": f"Maximum oxygen uptake (ml/kg/min). Current: {vo2_val}. For sub-4:00 marathon at ~75kg, you need ≥50. Declines ~3-5% per month of inactivity, recovers ~1/month with consistent training.",
        "training_load": "Garmin's EPOC-based measure of physiological stress per session. <strong style='color:var(--z12)'>< 150 = easy</strong>, <strong style='color:var(--z3)'>150-250 = moderate</strong>, <strong style='color:var(--z45)'>250-350 = hard</strong>, <strong style='color:var(--danger)'>> 350 = overload risk</strong>. A typical well-trained week sums to 400-800 across all sessions.",
        "readiness": "Garmin's composite 0-100 score combining sleep quality, recovery time, HRV status, stress, and recent training load. <strong style='color:var(--safe)'>≥75 = ready for quality sessions</strong>, <strong style='color:var(--caution)'>50-74 = easy day</strong>, <strong style='color:var(--danger)'>< 50 = rest</strong>.",
        "sleep": f"Your 14d avg: {avg_sleep_val}h total, {avg_deep_val}h deep. For runners: ≥1h deep + ≥1.5h REM is good. Total ≥7.5h supports adaptation. Post-hard-effort, deep sleep often collapses — a key recovery signal.",
        "stress_battery": f"Your 7d avg stress: {avg_stress_val}. Body Battery: energy reserve (0-100), charged by rest, drained by activity. Stress: 0-100 from HRV. When stress rises and battery drops simultaneously, your body is under load.",
        "weight": f"Current: {weight_val} kg. Each kg lost saves ~2-3 sec/km at the same effort. Over 42.2 km, 3 kg = ~7-10 min faster. Target weight through training volume (not dieting).",
        "zones": "HR zones by training TIME (minutes per week), not run count. Compared to your active training phase targets. Blue = Z1+Z2 (easy), amber = Z3 (moderate), orange = Z4+Z5 (hard). Phase 1 targets ~90% easy.",
        "volume": "Total running km per week. The darker segment shows the longest single run. For marathon training: long run should build gradually to 30-32 km, weekly volume to 50-60 km at peak.",
        "cadence": f"Your 30d avg cadence: {avg_cadence_val} spm. Below 165 often indicates overstriding. Target: 170-180. Tends to improve with fatigue resilience and form work.",
        "cardiac_drift": "<strong>Cardiac drift</strong> = HR rising while pace stays constant, caused by glycogen depletion, core temp rise, and plasma volume loss. <strong>Top chart:</strong> per-km pace + HR averaged across last 4 weeks (thin lines = individual runs, thick = average). <strong>Drift onset</strong> = the first km in the second half where HR exceeds first-half average + 5 bpm. <strong>Bottom chart:</strong> drift onset km per run over time — higher is better. Onset after km 15 (green zone) indicates strong aerobic base. Onset before km 10 suggests base work needed.",
        "rpe": "Garmin Effort = Aerobic Training Effect × 2 (dashed line, from every run). Your RPE = subjective effort from check-in (solid line, when available). When your RPE consistently exceeds Garmin's estimate, you're more fatigued than the numbers suggest.",
        "race_prediction": "Riegel formula: extrapolates from shorter race times using T2 = T1 × (D2/D1)^1.06. VDOT: from Daniels' tables using VO2max. Both are estimates — actual performance depends on training specificity, fueling, and conditions.",
        "acwr": f"Acute:Chronic Workload Ratio. Current: {acwr_val}. This week's load ÷ avg of previous 4 weeks. <strong style='color:var(--safe)'>0.8-1.3 = safe</strong>, <strong style='color:var(--caution)'>1.3-1.5 = caution</strong>, <strong style='color:var(--danger)'>> 1.5 = injury risk (spike)</strong>, < 0.6 = detraining. Critical for comeback training.",
        "pacecv": "Coefficient of Variation of pace within a run — how even your pacing is. Lower = more consistent. <strong style='color:var(--safe)'>< 5% = very even</strong>, <strong style='color:var(--caution)'>5-10% = moderate variation</strong>, <strong style='color:var(--danger)'>> 10% = erratic pacing</strong>. Even pacing is a key predictor of marathon success. Interval sessions naturally have higher CV.",
        "effort_gap": "Garmin Training Effect (TE) measures physiological load from sensor data. Check-in RPE is your subjective effort score (scaled to match). When RPE consistently exceeds TE, you're accumulating fatigue the watch can't see — consider extra recovery. When TE exceeds RPE, you're adapting well.",
    }



def _coaching(conn):
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    coaching_path = Path(db_path).parent / "reports" / "coaching.json"
    if not coaching_path.exists():
        return None

    data = json.loads(coaching_path.read_text())
    last_sync = conn.execute("SELECT MAX(date) FROM daily_health").fetchone()[0]
    stale = data.get("report_date", "") < last_sync if last_sync else False

    styles = {
        "critical": {"bg": "rgba(239,68,68,0.06)", "border": "rgba(239,68,68,0.15)", "color": DANGER, "icon": "🚨"},
        "warning": {"bg": "rgba(249,115,22,0.06)", "border": "rgba(249,115,22,0.15)", "color": Z4, "icon": "⚠️"},
        "positive": {"bg": "rgba(34,197,94,0.06)", "border": "rgba(34,197,94,0.15)", "color": SAFE, "icon": "✅"},
        "info": {"bg": "rgba(59,130,246,0.06)", "border": "rgba(59,130,246,0.15)", "color": "#3b82f6", "icon": "📊"},
        "target": {"bg": "rgba(167,139,250,0.06)", "border": "rgba(167,139,250,0.15)", "color": ACCENT, "icon": "🎯"},
    }
    insights = [{**styles.get(i.get("type", "info"), styles["info"]), "title": i.get("title", ""), "body": i.get("body", "")}
                for i in data.get("insights", [])]
    return {"generated_at": data.get("generated_at", ""), "stale": stale, "insights": insights}


# ── Milestones ──

def _milestones(conn):
    try:
        from fit.milestones import detect_milestones
        return detect_milestones(conn)
    except Exception:
        return []


# ── Goal Progress ──

def _goal_progress(conn):
    """Build goal progress cards from the goals table — no hardcoded targets."""
    results = []

    goals = conn.execute("SELECT * FROM goals WHERE active = 1 ORDER BY id").fetchall()

    for g in goals:
        name = g["name"]
        goal_type = g["type"]
        target_value = g["target_value"]
        target_unit = g["target_unit"] or ""

        current = None
        pct = None
        icon = "🎯"
        color = CAUTION
        tooltip = ""

        if goal_type == "metric" and target_value:
            name_lower = name.lower()
            if "vo2" in name_lower:
                icon = "📈"
                row = conn.execute(
                    "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
                ).fetchone()
                if row:
                    current = row["vo2max"]
                    pct = min(current / target_value * 100, 100)
                    color = SAFE if current >= target_value * 0.98 else CAUTION
                    tooltip = (f"Maximum oxygen uptake. Current: {current:.0f} {target_unit}. "
                               f"Target: {target_value:.0f}. Improves ~1/month with consistent training.")
                    results.append({
                        "icon": icon, "label": "VO2max",
                        "current": f"{current:.0f}", "target": f"{target_value:.0f}",
                        "unit": "", "pct": pct, "color": color, "tooltip": tooltip,
                    })
            elif "weight" in name_lower:
                icon = "⚖️"
                row = conn.execute(
                    "SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1"
                ).fetchone()
                if row:
                    current = row["weight_kg"]
                    # Progress: how close to target. Simple: if at/below target = 100%,
                    # otherwise show how far above target as a ratio (closer to target = higher %).
                    # E.g. 78.3/75 → need to lose 3.3kg. If max reasonable excess is 10kg, pct = (10-3.3)/10 = 67%.
                    max_excess = 10.0  # kg above target considered "start"
                    excess = max(0, current - target_value)
                    pct = max(0, min((max_excess - excess) / max_excess * 100, 100))
                    color = SAFE if current <= target_value * 1.01 else CAUTION if current <= target_value * 1.04 else DANGER
                    tooltip = (f"Current: {current:.1f}kg. Target: {target_value:.0f}kg. "
                               f"Each kg lost saves ~2-3 sec/km over 42km.")
                    results.append({
                        "icon": icon, "label": "Weight",
                        "current": f"{current:.1f}", "target": f"{target_value:.0f}",
                        "unit": "kg", "pct": pct, "color": color, "tooltip": tooltip,
                    })
            else:
                # Generic metric goal — show as-is
                results.append({
                    "icon": icon, "label": name[:15],
                    "current": "—", "target": f"{target_value:.0f}",
                    "unit": target_unit, "pct": None, "color": CAUTION,
                    "tooltip": f"Target: {target_value} {target_unit}",
                })

        elif goal_type == "habit" and target_value:
            icon = "🔥"
            row = conn.execute(
                "SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1"
            ).fetchone()
            s = row[0] if row and row[0] else 0
            pct = min(s / target_value * 100, 100)
            color = SAFE if s >= target_value * 0.75 else CAUTION if s >= target_value * 0.375 else DANGER
            tooltip = (f"Consecutive weeks with 3+ runs. Current: {s}. "
                       f"Target: {int(target_value)} weeks. The #1 predictor of marathon readiness.")
            results.append({
                "icon": icon, "label": "Streak",
                "current": str(s), "target": str(int(target_value)),
                "unit": "wk", "pct": pct, "color": color, "tooltip": tooltip,
            })

        elif goal_type in ("race", "marathon"):
            # Race-type goals are waypoints in the race calendar, not objectives.
            # They're shown in the race calendar section, not as objective cards.
            # Exception: the main marathon goal (type='marathon') shows target time.
            if goal_type == "marathon":
                icon = "🏁"
                target_time = g["target_time"] or ""
                tooltip = f"{name}. Target: {target_time}."
                results.append({
                    "icon": icon, "label": name[:15],
                    "current": target_time or "—", "target": "",
                    "unit": "", "pct": None, "color": ACCENT, "tooltip": tooltip,
                })
            # type='race' goals (stepping stones) are intentionally NOT shown as objectives

    # Next race countdown is shown in the upcoming races strip, not in objectives.
    # Objectives section only contains training objectives serving the target race.

    return results


# ── Recent Alerts ──

def _recent_alerts(conn):
    try:
        from fit.alerts import get_recent_alerts
        alerts = get_recent_alerts(conn, days=7)
        # Deduplicate by type — show only the most recent per alert type
        seen = set()
        deduped = []
        for a in alerts:
            if a["type"] not in seen:
                seen.add(a["type"])
                deduped.append(a)
        return deduped
    except Exception:
        return []


# ── Correlation Bars ──

def _correlation_bars(conn):
    try:
        rows = conn.execute("""
            SELECT metric_pair, spearman_r, sample_size, confidence
            FROM correlations WHERE status = 'computed' AND spearman_r IS NOT NULL
            ORDER BY ABS(spearman_r) DESC LIMIT 8
        """).fetchall()
        results = []
        for r in rows:
            sr = r["spearman_r"]
            label = r["metric_pair"].replace("_", " ").replace("lag1", "(next day)")
            color = SAFE if sr > 0 else DANGER
            width = min(abs(sr) * 100, 50)  # scale to max 50% bar width
            results.append({
                "label": label, "r": f"{sr:+.2f}", "n": r["sample_size"],
                "confidence": r["confidence"], "color": color, "width": int(width),
                "direction": "positive" if sr > 0 else "negative",
            })
        return results
    except Exception:
        return []




def _phase_compliance(conn):
    phase = conn.execute("SELECT * FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
    if not phase:
        return None
    from fit.goals import get_phase_compliance
    compliance = get_phase_compliance(conn, phase["id"])
    if compliance.get("status") == "no_data":
        return {"phase_name": f"{phase['phase']}: {phase['name']}", "dimensions": [], "no_data": True}
    return {"phase_name": f"{phase['phase']}: {phase['name']}", "dimensions": compliance.get("dimensions", []), "no_data": False}


# ── Calibration Panel (W9) ──

def _calibration_panel(conn):
    from fit.calibration import get_calibration_status
    return get_calibration_status(conn)


# ── Data Health Panel (W9) ──

def _data_health_panel(conn):
    from fit.data_health import check_data_sources
    return check_data_sources(conn)


# ── Sleep Mismatches (W10) ──

def _sleep_mismatches(conn):
    rows = conn.execute("""
        SELECT h.date, h.sleep_duration_hours, c.sleep_quality
        FROM daily_health h
        JOIN checkins c ON h.date = c.date
        WHERE h.date >= date('now', '-21 days')
          AND c.sleep_quality IS NOT NULL
          AND h.sleep_duration_hours IS NOT NULL
        ORDER BY h.date DESC
    """).fetchall()
    mismatches = []
    for r in rows:
        hours = r["sleep_duration_hours"]
        quality = r["sleep_quality"]
        if hours >= 7 and quality == "Poor":
            mismatches.append({"date": r["date"], "hours": f"{hours:.1f}", "quality": quality,
                               "msg": f"{hours:.1f}h sleep but felt Poor — possible stress or sleep disruption"})
        elif hours < 6 and quality == "Good":
            mismatches.append({"date": r["date"], "hours": f"{hours:.1f}", "quality": quality,
                               "msg": f"Only {hours:.1f}h but felt Good — monitor for cumulative deficit"})
    return mismatches


# ── Trend Badges (3.2) ──

def _trend_badges(conn):
    try:
        return generate_trend_badges(conn)
    except Exception:
        return []


# ── Why Connectors (3.3) ──

def _why_connectors(conn):
    try:
        return generate_why_connectors(conn)
    except Exception:
        return []


# ── Race Countdown (3.6) ──

def _race_countdown(conn):
    try:
        result = generate_race_countdown(conn)
        if not result:
            return None

        # Enrich with fields needed by the Overview tab template
        from fit.goals import get_target_race
        race = get_target_race(conn)
        if race:
            result["distance_km"] = race.get("distance_km", "")
            result["race_date"] = race.get("date", "")

            # Target time (formatted)
            target_str = race.get("target_time")
            if target_str:
                result["target_time"] = target_str
            else:
                # Fall back to goal-based target
                goal = conn.execute(
                    "SELECT target_time FROM goals WHERE type = 'marathon' AND active = 1 LIMIT 1"
                ).fetchone()
                result["target_time"] = goal["target_time"] if goal else None

            # Prediction: conservative = upper bound of chart's confidence band
            # at today. Uses VO2max-derived prediction + method spread margin,
            # exactly matching what the prediction trend chart shows.
            try:
                from fit.analysis import predict_race_time, _vdot_to_marathon_seconds

                def _parse_time(t):
                    parts = t.split(":")
                    if len(parts) == 3:
                        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        return int(parts[0]) * 60 + int(parts[1])
                    return 0

                def _fmt_time(s):
                    return f"{s // 3600}:{(s % 3600) // 60:02d}"

                # Current VO2max → predicted race time (center line of chart)
                vo2 = conn.execute(
                    "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
                ).fetchone()
                center_secs = None
                if vo2 and vo2["vo2max"] and vo2["vo2max"] > 30:
                    marathon_secs = _vdot_to_marathon_seconds(vo2["vo2max"])
                    target_km = race.get("distance_km") or 42.195
                    if target_km != 42.195:
                        center_secs = marathon_secs * (target_km / 42.195) ** 1.06
                    else:
                        center_secs = marathon_secs

                # Method spread margin (half-width of all prediction sources)
                races_db = conn.execute("""
                    SELECT distance_km, result_time FROM race_calendar
                    WHERE status = 'completed' AND result_time IS NOT NULL
                    ORDER BY date DESC LIMIT 5
                """).fetchall()
                race_data = [
                    {"distance_km": r["distance_km"], "time_seconds": _parse_time(r["result_time"])}
                    for r in races_db if r["distance_km"] and r["result_time"]
                ]
                preds = predict_race_time(
                    conn=conn, races=race_data,
                    vo2max=vo2["vo2max"] if vo2 else None,
                )
                all_secs = []
                if preds.get("riegel"):
                    all_secs.extend(p["predicted_seconds"] for p in preds["riegel"])
                if preds.get("vdot") and preds["vdot"].get("predicted_seconds"):
                    all_secs.append(preds["vdot"]["predicted_seconds"])

                margin_secs = 0
                if len(all_secs) >= 2:
                    margin_secs = (max(all_secs) - min(all_secs)) / 2
                else:
                    margin_secs = preds.get("confidence", {}).get("margin_seconds", 480)

                if center_secs:
                    # Conservative = center + margin (upper bound of chart band)
                    conservative_secs = center_secs + margin_secs
                    result["prediction_mid"] = _fmt_time(round(conservative_secs))
                    result["confidence_level"] = preds.get("confidence", {}).get("level", "low")

                    # Gap based on conservative prediction vs target
                    if result.get("target_time"):
                        target_secs = _parse_time(result["target_time"])
                        if target_secs > 0:
                            gap = round((conservative_secs - target_secs) / 60)
                            result["gap_minutes"] = gap

                # Trend badge: compare oldest vs newest weekly VO2max (proxy for prediction trend)
                trend_rows = conn.execute("""
                    SELECT week, vo2max_avg FROM (
                        SELECT strftime('%Y-W%W', date) as week,
                               AVG(vo2max) as vo2max_avg
                        FROM activities
                        WHERE vo2max IS NOT NULL
                          AND date >= date('now', '-56 days')
                        GROUP BY week
                        ORDER BY week
                    ) WHERE vo2max_avg IS NOT NULL
                """).fetchall()
                if len(trend_rows) >= 2:
                    old_v = trend_rows[0]["vo2max_avg"]
                    new_v = trend_rows[-1]["vo2max_avg"]
                    if old_v and new_v and old_v > 30:
                        # Convert VO2max change to approximate time change
                        old_secs = _vdot_to_marathon_seconds(old_v)
                        new_secs = _vdot_to_marathon_seconds(new_v)
                        delta_min = round((new_secs - old_secs) / 60)
                        weeks = len(trend_rows)
                        if delta_min != 0:
                            sign = "+" if delta_min > 0 else ""
                            result["trend_badge"] = f"{sign}{delta_min} min / {weeks} wk"
            except Exception:
                pass  # prediction enrichment is best-effort

        return result
    except Exception:
        return None


# ── Walk Break (3.7) ──

def _walk_break(conn):
    try:
        return detect_walk_break_need(conn)
    except Exception:
        return None


# ── Z2 Remediation (3.10) ──

def _z2_remediation(conn):
    try:
        from fit.config import get_config
        config = get_config()
    except Exception:
        config = {"profile": {"zones_max_hr": {"z2": [115, 134]}}}
    try:
        return generate_z2_remediation(conn, config)
    except Exception:
        return None


# ── Rolling Correlations (3.5) ──

def _rolling_correlations(conn):
    try:
        from fit.correlations import compute_rolling_correlations
        return compute_rolling_correlations(conn)
    except Exception:
        return []


def _split_data(conn):
    """Get split data for the most recent long run with parsed splits."""
    try:
        run = conn.execute(f"""
            SELECT a.id, a.name, a.date, a.distance_km, a.duration_min
            FROM activities a
            WHERE a.type IN {RUNNING_TYPES_SQL} AND a.splits_status = 'done'
            ORDER BY a.date DESC LIMIT 1
        """).fetchone()
        if not run:
            return None
        splits = conn.execute("""
            SELECT split_num, pace_sec_per_km, avg_hr, avg_cadence, time_above_z2_ceiling_sec
            FROM activity_splits WHERE activity_id = ? ORDER BY split_num
        """, (run["id"],)).fetchall()
        if not splits:
            return None

        from fit.fit_file import compute_cardiac_drift
        drift = compute_cardiac_drift([dict(s) for s in splits])

        return {
            "run_name": run["name"],
            "run_date": run["date"],
            "distance_km": run["distance_km"],
            "splits": [dict(s) for s in splits],
            "drift": drift,
        }
    except Exception:
        return None


def _upcoming_races(conn):
    """Get upcoming races as waypoint pills for the Today tab."""
    try:
        from fit.goals import get_target_race, get_race_calendar_upcoming
        target = get_target_race(conn)
        target_id = target["id"] if target else None
        upcoming = get_race_calendar_upcoming(conn)
        result = []
        for r in upcoming:
            days = (date.fromisoformat(r["date"]) - date.today()).days
            result.append({
                "name": r["name"],
                "distance": r["distance"],
                "days": days,
                "date": r["date"],
                "is_target": r["id"] == target_id,
            })
        return result
    except Exception:
        return []


def _plan_adherence(conn):
    """Get plan adherence data for the current week."""
    try:
        from fit.plan import compute_plan_adherence
        return compute_plan_adherence(conn)
    except Exception:
        return None


# ── Helpers ──

def _subtitle(conn):
    h = conn.execute("SELECT COUNT(*) FROM daily_health").fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
    # Training age: weeks since first activity
    first = conn.execute("SELECT MIN(date) FROM activities").fetchone()[0]
    weeks = ""
    if first:
        days_tracking = (date.today() - date.fromisoformat(first)).days
        weeks = f" · week {days_tracking // 7} of tracking"
    return f"{h}d · {a} activities · {c} check-ins{weeks}"





def _body_summary(conn):
    """One-line narrative for the Body tab."""
    try:
        return generate_body_summary(conn)
    except Exception:
        return None


def _volume_story(conn):
    """Gap and milestone annotations for volume/timeline charts."""
    try:
        return generate_volume_story(conn)
    except Exception:
        return None


def _checkin_progress(conn):
    """Progress toward correlation unlock thresholds."""
    try:
        return generate_checkin_progress(conn)
    except Exception:
        return {"total": 0, "target": 20, "pct": 0, "remaining": 20}


def _status_cards_with_actions(conn):
    """Status cards with actionable recommendation text."""
    cards = _status_cards(conn)
    for card in cards:
        label = card.get("label", "")
        value = card.get("value")
        if label == "Readiness" and value and isinstance(value, (int, float)):
            if value >= 75:
                card["action"] = "Ready for quality session"
            elif value >= 50:
                card["action"] = "Easy run or rest"
            else:
                card["action"] = "Rest day"
        elif label == "ACWR" and value and value != "—":
            try:
                v = float(value)
                if 0.8 <= v <= 1.3:
                    card["action"] = "Safe zone"
                elif v < 0.6:
                    card["action"] = "Build volume"
                elif v <= 1.5:
                    card["action"] = "Reduce load"
                else:
                    card["action"] = "Rest immediately"
            except (ValueError, TypeError):
                pass
        elif label == "HRV":
            card["action"] = "Trends > single values"
    return cards


def _fitness_profile_data(conn):
    """Fitness profile for dashboard rendering, enriched with weight data."""
    try:
        from fit.fitness import get_fitness_profile
        profile = get_fitness_profile(conn)
        if profile:
            profile["weight"] = _weight_card_data(conn)
        return profile
    except Exception:
        return None


def _weight_card_data(conn):
    """Weight summary for the fitness profile card."""
    try:
        rows = conn.execute(
            "SELECT date, weight_kg FROM body_comp WHERE weight_kg IS NOT NULL ORDER BY date DESC LIMIT 8"
        ).fetchall()
        if not rows:
            return None
        history = list(reversed([r["weight_kg"] for r in rows]))
        dates = list(reversed([r["date"] for r in rows]))
        current = history[-1]
        # Change over the history window
        change = round(current - history[0], 1) if len(history) >= 2 else None
        # Compute actual timespan for label
        change_span = None
        if len(dates) >= 2:
            days = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
            if days < 60:
                change_span = f"{days}d"
            elif days < 365:
                change_span = f"{days // 30}mo"
            else:
                change_span = f"{days // 365}yr"
        # Try to find weight target from goals
        target = None
        try:
            goal = conn.execute(
                "SELECT target_value FROM goals WHERE metric = 'weight' AND active = 1 LIMIT 1"
            ).fetchone()
            if goal:
                target = goal["target_value"]
        except Exception:
            pass
        return {
            "current": round(current, 1),
            "target": target,
            "change": change,
            "change_span": change_span,
            "history": history,
        }
    except Exception:
        return None


def _derived_objectives_data(conn):
    """Derived objectives with achievability — same computation as CLI."""
    try:
        from fit.goals import get_target_race
        from fit.fitness import derive_objectives, compute_achievability

        target = get_target_race(conn)
        if not target:
            return None

        days_left = (date.fromisoformat(target["date"]) - date.today()).days
        derived = derive_objectives(conn, target["id"])
        derived = compute_achievability(conn, derived, days_left)

        # Filter out internal _dim_ objectives
        visible = [o for o in derived if not o["name"].startswith("_dim_")]

        # Add sparkline history from weekly_agg
        history = _objective_history(conn)
        for obj in visible:
            key = obj["name"].lower().replace(" ", "_")
            obj["history"] = history.get(key, [])

        return {"objectives": visible, "race_name": target["name"], "target_time": target.get("target_time")}
    except Exception:
        return None


def _objective_history(conn):
    """Get last 8 weeks of objective-relevant metrics from weekly_agg."""
    rows = conn.execute("""
        SELECT run_km, longest_run_km, z12_pct, consecutive_weeks_3plus
        FROM weekly_agg ORDER BY week DESC LIMIT 8
    """).fetchall()
    if not rows:
        return {}
    # Reverse so oldest first (left-to-right in sparkline)
    rows = list(reversed(rows))
    return {
        "weekly_volume": [r["run_km"] or 0 for r in rows],
        "long_run": [r["longest_run_km"] or 0 for r in rows],
        "z2_time": [r["z12_pct"] or 0 for r in rows],
        "consistency": [r["consecutive_weeks_3plus"] or 0 for r in rows],
    }


def _next_workouts(conn):
    """Next 3 planned workouts for the Overview tab."""
    try:
        rows = conn.execute("""
            SELECT date, workout_name, workout_type, target_distance_km
            FROM planned_workouts
            WHERE date >= date('now') AND status = 'active'
            ORDER BY date LIMIT 3
        """).fetchall()
        result = []
        today = date.today()
        for r in rows:
            d = date.fromisoformat(r["date"])
            days = (d - today).days
            # Format date as "Wed Apr 9"
            date_label = d.strftime("%a %b %-d")
            # Clean up workout name (strip "W N Day. " prefix)
            name = r["workout_name"] or r["workout_type"] or "Run"
            for prefix in ["W ", "Wo "]:
                if name.startswith(prefix):
                    # Strip "W 1 Fr. " style prefix
                    parts = name.split(". ", 1)
                    if len(parts) > 1:
                        name = parts[1]
                    break
            # Truncate long names
            if len(name) > 40:
                name = name[:37] + "..."
            result.append({
                "name": name,
                "type": r["workout_type"] or "easy",
                "distance_km": r["target_distance_km"] or "?",
                "date_label": date_label,
                "days": max(0, days),
            })
        return result
    except Exception:
        return []


def _overview_objectives(conn):
    """Objectives summary for Overview tab — always from weekly_agg, not derived_objectives."""
    try:
        latest = conn.execute(
            "SELECT run_km, longest_run_km, z12_pct, consecutive_weeks_3plus "
            "FROM weekly_agg ORDER BY week DESC LIMIT 1"
        ).fetchone()
        if not latest:
            return None

        history = _objective_history(conn)

        # Try to get targets from derived objectives
        targets = {"weekly_volume": None, "long_run": None, "z2_time": 80, "consistency": 8}
        try:
            from fit.goals import get_target_race
            from fit.fitness import derive_objectives
            target = get_target_race(conn)
            if target:
                derived = derive_objectives(conn, target["id"])
                for obj in derived:
                    key = obj["name"].lower().replace(" ", "_")
                    if key in targets:
                        targets[key] = obj["target_value"]
        except Exception:
            pass

        def _pct(cur, tgt):
            if cur and tgt and tgt > 0:
                return int(cur / tgt * 100)
            return None

        def _color(pct):
            if pct is None:
                return "var(--text-dim)"
            if pct >= 80:
                return "var(--safe)"
            if pct >= 60:
                return "var(--caution)"
            return "var(--danger)"

        vol = latest["run_km"] or 0
        long_r = latest["longest_run_km"] or 0
        streak = latest["consecutive_weeks_3plus"] or 0

        # Z2 compliance: use rolling average over recent training weeks
        # (single-week snapshots are misleading — 1 easy run = 100%)
        z2_rows = conn.execute("""
            SELECT z12_pct FROM weekly_agg
            WHERE z12_pct IS NOT NULL AND run_km > 0
            ORDER BY week DESC LIMIT 4
        """).fetchall()
        z2 = round(sum(r["z12_pct"] for r in z2_rows) / len(z2_rows)) if z2_rows else 0

        vol_pct = _pct(vol, targets["weekly_volume"])
        long_pct = _pct(long_r, targets["long_run"])
        z2_pct = _pct(z2, targets["z2_time"])
        streak_pct = _pct(streak, targets["consistency"])

        return [
            {"label": "Weekly Volume", "value": f"{vol:.0f}", "sub": f"of {targets['weekly_volume']:.0f} km" if targets["weekly_volume"] else "km",
             "pct": vol_pct, "color": _color(vol_pct), "history": history.get("weekly_volume", []), "spark_id": "spark-obj-vol"},
            {"label": "Long Run", "value": f"{long_r:.0f}", "sub": f"of {targets['long_run']:.0f} km" if targets["long_run"] else "km",
             "pct": long_pct, "color": _color(long_pct), "history": history.get("long_run", []), "spark_id": "spark-obj-long"},
            {"label": "Z2 Time", "value": f"{z2:.0f}%", "sub": f"target {targets['z2_time']:.0f}% · 4wk avg",
             "pct": z2_pct, "color": _color(z2_pct), "history": history.get("z2_time", []), "spark_id": "spark-obj-z2"},
            {"label": "Consistency", "value": f"{streak:.0f}", "sub": f"of {targets['consistency']:.0f} wks",
             "pct": streak_pct, "color": _color(streak_pct), "history": history.get("consistency", []), "spark_id": "spark-obj-streak"},
        ]
    except Exception:
        return None


def _readiness_summary(conn):
    """Readiness summary cards for Overview tab — HRV, ACWR, Sleep, Monotony with sparklines."""
    try:
        # HRV
        hrv_rows = conn.execute(
            "SELECT hrv_last_night FROM daily_health WHERE hrv_last_night IS NOT NULL ORDER BY date DESC LIMIT 8"
        ).fetchall()
        hrv_history = list(reversed([r["hrv_last_night"] for r in hrv_rows]))
        hrv_now = hrv_history[-1] if hrv_history else None
        hrv_avg = sum(hrv_history[-7:]) / len(hrv_history[-7:]) if len(hrv_history) >= 2 else None

        # ACWR
        acwr_rows = conn.execute(
            "SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 8"
        ).fetchall()
        acwr_history = list(reversed([r["acwr"] for r in acwr_rows]))
        acwr_now = acwr_history[-1] if acwr_history else None

        # Sleep
        sleep_rows = conn.execute(
            "SELECT sleep_duration_hours FROM daily_health WHERE sleep_duration_hours IS NOT NULL ORDER BY date DESC LIMIT 8"
        ).fetchall()
        sleep_history_hrs = list(reversed([r["sleep_duration_hours"] for r in sleep_rows]))
        sleep_now = sleep_history_hrs[-1] if sleep_history_hrs else None
        sleep_avg = sum(sleep_history_hrs[-7:]) / len(sleep_history_hrs[-7:]) if len(sleep_history_hrs) >= 2 else None

        # Monotony
        mono_rows = conn.execute(
            "SELECT monotony FROM weekly_agg WHERE monotony IS NOT NULL ORDER BY week DESC LIMIT 8"
        ).fetchall()
        mono_history = list(reversed([r["monotony"] for r in mono_rows]))
        mono_now = mono_history[-1] if mono_history else None

        def _hrv_color(val, avg):
            if val is None:
                return "var(--text-dim)"
            if avg and val >= avg:
                return "var(--safe)"
            if avg and val >= avg * 0.85:
                return "var(--caution)"
            return "var(--danger)"

        def _acwr_color(val):
            if val is None:
                return "var(--text-dim)"
            if 0.8 <= val <= 1.3:
                return "var(--safe)"
            if 0.6 <= val <= 1.5:
                return "var(--caution)"
            return "var(--danger)"

        def _sleep_fmt(hrs):
            if hrs is None:
                return "—"
            h = int(hrs)
            m = int((hrs - h) * 60)
            return f"{h}:{m:02d}"

        def _mono_color(val):
            if val is None:
                return "var(--text-dim)"
            if val < 1.5:
                return "var(--safe)"
            if val < 2.0:
                return "var(--caution)"
            return "var(--danger)"

        return [
            {"label": "HRV", "value": f"{hrv_now:.0f}" if hrv_now else "—", "unit": "ms",
             "sub": f"7d avg: {hrv_avg:.0f}" if hrv_avg else "",
             "status": "above" if hrv_now and hrv_avg and hrv_now >= hrv_avg else "below" if hrv_now and hrv_avg else "",
             "color": _hrv_color(hrv_now, hrv_avg), "history": hrv_history, "spark_id": "spark-rd-hrv"},
            {"label": "ACWR", "value": f"{acwr_now:.2f}" if acwr_now else "—", "unit": "",
             "sub": "sweet spot (0.8–1.3)" if acwr_now and 0.8 <= acwr_now <= 1.3 else "caution" if acwr_now else "",
             "color": _acwr_color(acwr_now), "history": acwr_history, "spark_id": "spark-rd-acwr"},
            {"label": "Sleep", "value": _sleep_fmt(sleep_now), "unit": "hrs",
             "sub": f"avg {_sleep_fmt(sleep_avg)}" if sleep_avg else "",
             "color": "var(--safe)" if sleep_now and sleep_now >= 7 else "var(--caution)" if sleep_now and sleep_now >= 6 else "var(--danger)" if sleep_now else "var(--text-dim)",
             "history": [round(h, 1) for h in sleep_history_hrs], "spark_id": "spark-rd-sleep"},
            {"label": "Monotony", "value": f"{mono_now:.1f}" if mono_now else "—", "unit": "",
             "sub": "safe (<2.0)" if mono_now and mono_now < 2.0 else "high risk" if mono_now else "",
             "color": _mono_color(mono_now), "history": mono_history, "spark_id": "spark-rd-mono"},
        ]
    except Exception:
        return None


def _checkpoint_data(conn):
    """Checkpoint races with derived targets."""
    try:
        from fit.fitness import derive_checkpoint_targets
        return derive_checkpoint_targets(conn)
    except Exception:
        return []


def _prediction_trend_data(conn):
    """Generate prediction trend chart data for the Overview race card.

    Returns JSON-serializable dict with: labels, pred, upper, lower,
    checkpoints, phases, target_min, today.
    """
    try:
        from fit.analysis import _vdot_to_marathon_seconds
        from fit.goals import get_target_race

        target = get_target_race(conn)
        if not target:
            return None

        target_km = target.get("distance_km") or 42.195

        def _parse_time(t):
            parts = t.split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            elif len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            return 0

        # Target time in minutes
        target_str = target.get("target_time")
        target_min = None
        if target_str:
            target_min = _parse_time(target_str) / 60

        # Chart start: 1 month before first training phase (baseline context)
        from datetime import datetime, timedelta
        phase_start = conn.execute("""
            SELECT MIN(start_date) as s FROM training_phases WHERE status != 'revised'
        """).fetchone()
        if phase_start and phase_start["s"]:
            ps = datetime.fromisoformat(phase_start["s"])
            training_start = (ps - timedelta(days=30)).strftime("%Y-%m-%d")
        else:
            training_start = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")

        # Weekly VO2max → predicted race time (in minutes), from training start
        start_clause = f"AND date >= '{training_start}'" if training_start else ""
        weeks = conn.execute(f"""
            SELECT strftime('%Y-%m-%d', date, 'weekday 0', '-6 days') as week_start,
                   AVG(vo2max) as vo2max_avg
            FROM activities
            WHERE vo2max IS NOT NULL {start_clause}
            GROUP BY strftime('%Y-W%W', date)
            ORDER BY week_start
        """).fetchall()

        if len(weeks) < 3:
            return None

        labels = []
        pred = []
        for w in weeks:
            labels.append(w["week_start"])
            if w["vo2max_avg"] and w["vo2max_avg"] > 30:
                marathon_secs = _vdot_to_marathon_seconds(w["vo2max_avg"])
                if target_km != 42.195:
                    race_secs = marathon_secs * (target_km / 42.195) ** 1.06
                else:
                    race_secs = marathon_secs
                pred.append(round(race_secs / 60, 1))
            else:
                pred.append(None)

        # Extend labels to race date
        race_date = target.get("date", "")
        if race_date and (not labels or labels[-1] < race_date):
            from datetime import datetime, timedelta
            last = datetime.fromisoformat(labels[-1]) if labels else datetime.now()
            race_dt = datetime.fromisoformat(race_date)
            while last < race_dt:
                last += timedelta(days=7)
                if last.strftime("%Y-%m-%d") not in labels:
                    labels.append(last.strftime("%Y-%m-%d"))
                    pred.append(None)

        # Confidence band: method spread (same as header range).
        # Collect all prediction sources, compute half-spread as margin.
        from fit.analysis import predict_race_time
        races = conn.execute("""
            SELECT distance_km, result_time FROM race_calendar
            WHERE status = 'completed' AND result_time IS NOT NULL
            ORDER BY date DESC LIMIT 5
        """).fetchall()
        race_data = [
            {"distance_km": r["distance_km"],
             "time_seconds": _parse_time(r["result_time"])}
            for r in races if r["distance_km"] and r["result_time"]
        ]
        vo2_row = conn.execute(
            "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
        ).fetchone()
        preds = predict_race_time(
            conn=conn, races=race_data,
            vo2max=vo2_row["vo2max"] if vo2_row else None,
        )
        all_pred_secs = []
        if preds.get("riegel"):
            all_pred_secs.extend(p["predicted_seconds"] for p in preds["riegel"])
        if preds.get("vdot") and preds["vdot"].get("predicted_seconds"):
            all_pred_secs.append(preds["vdot"]["predicted_seconds"])

        if len(all_pred_secs) >= 2:
            margin_min = (max(all_pred_secs) - min(all_pred_secs)) / 2 / 60
        else:
            # Fallback: use confidence-based margin if only one source
            margin_min = preds.get("confidence", {}).get("margin_seconds", 480) / 60

        upper = [round(p + margin_min, 1) if p is not None else None for p in pred]
        lower = [round(p - margin_min, 1) if p is not None else None for p in pred]

        # Training phases for the band
        phases_raw = conn.execute("""
            SELECT name, start_date, end_date, status FROM training_phases
            WHERE status != 'revised'
            ORDER BY start_date
        """).fetchall()
        phases = []
        for p in phases_raw:
            label_text = p["name"] or ""
            if p["status"] == "active":
                label_text += " ←"
            phases.append({
                "name": p["name"],
                "start": p["start_date"],
                "end": p["end_date"],
                "label": label_text,
                "status": p["status"],
                "active": p["status"] == "active",
            })

        # All races in chart range, Riegel-extrapolated to target distance.
        # Completed races use actual result; upcoming use derived target.
        checkpoints = []
        try:
            from fit.goals import get_target_race
            target_race = get_target_race(conn)
            target_id = target_race["id"] if target_race else None

            # All non-target races in the chart time range
            chart_races = conn.execute("""
                SELECT id, name, date, distance, distance_km, status, result_time
                FROM race_calendar
                WHERE date >= ? AND date <= ?
                ORDER BY date
            """, (training_start, race_date)).fetchall()

            # Also get derived targets for upcoming checkpoints
            derived_map = {}
            try:
                from fit.fitness import derive_checkpoint_targets
                for cp in derive_checkpoint_targets(conn):
                    derived_map[cp.get("race_id")] = cp.get("derived_target", "")
            except Exception:
                pass

            # Target race time for back-calculation
            target_str = target.get("target_time")
            target_secs = _parse_time(target_str) if target_str else 0

            def _fmt_hm(s):
                h, rem = divmod(int(s), 3600)
                m, sec = divmod(rem, 60)
                if h > 0:
                    return f"{h}:{m:02d}:{sec:02d}"
                return f"{m}:{sec:02d}"

            idx = 1
            for r in chart_races:
                if r["id"] == target_id:
                    continue  # skip the target race itself
                r_km = r["distance_km"] or 0
                if r_km <= 0 or r_km == target_km:
                    continue

                # "Needed" time: Riegel back-calc from target race to this distance
                needed_secs = 0
                if target_secs > 0:
                    needed_secs = target_secs * (r_km / target_km) ** 1.06

                # Actual time (completed) or derived target (upcoming)
                time_secs = 0
                if r["status"] == "completed" and r["result_time"]:
                    time_secs = _parse_time(r["result_time"])
                elif derived_map.get(r["id"]):
                    time_secs = _parse_time(derived_map[r["id"]])
                elif needed_secs > 0:
                    time_secs = round(needed_secs)

                if time_secs > 0:
                    # Riegel forward: checkpoint time → target race equivalent
                    marathon_equiv = time_secs * (target_km / r_km) ** 1.06
                    me_min = marathon_equiv / 60

                    cp_data = {
                        "x": r["date"],
                        "y": round(me_min, 1),
                        "num": str(idx),
                        "name": r["name"],
                        "distance": r["distance"],
                        "done": r["status"] == "completed",
                        "marathon_equiv": f"{int(me_min) // 60}:{int(me_min) % 60:02d}",
                        "days": (datetime.fromisoformat(r["date"]) - datetime.now()).days,
                        "needed": _fmt_hm(round(needed_secs)) if needed_secs > 0 else None,
                    }
                    if r["status"] == "completed":
                        cp_data["result"] = _fmt_hm(time_secs)
                    checkpoints.append(cp_data)
                    idx += 1
        except Exception:
            pass

        today_str = date.today().isoformat()

        return json.dumps({
            "labels": labels,
            "pred": pred,
            "upper": upper,
            "lower": lower,
            "target_min": target_min,
            "target_label": f"Target {target_str}" if target_str else "Target",
            "checkpoints": checkpoints,
            "phases": phases,
            "today": today_str,
            "race_date": race_date,
        })
    except Exception as e:
        logger.debug("prediction_trend_data failed: %s", e)
        return None


# ── Profile Tab Data Functions ──


def _race_readiness_hero(conn):
    """Race readiness hero: current VDOT vs required, gap, trend, verdict.

    Answers: "Am I fit enough for race day?"
    """
    try:
        from fit.fitness import (
            get_fitness_profile,
            compute_vdot_from_race,
            vdot_to_race_time,
        )
        from fit.goals import get_target_race

        profile = get_fitness_profile(conn)
        if not profile:
            return None

        target = get_target_race(conn)
        effective_vdot = profile.get("effective_vdot")
        garmin_vo2 = profile.get("garmin_vo2max")
        race_vdot = profile.get("race_vdot")
        race_vdot_date = profile.get("race_vdot_date")

        result = {
            "effective_vdot": effective_vdot,
            "garmin_vo2max": garmin_vo2,
            "race_vdot": race_vdot,
            "race_vdot_date": race_vdot_date,
            "required_vdot": None,
            "vdot_gap": None,
            "predicted_time": None,
            "target_time": None,
            "gap_minutes": None,
            "trend": profile["aerobic"].get("trend"),
            "rate_per_month": profile["aerobic"].get("rate_per_month"),
            "verdict": None,
            "vdot_history": profile["aerobic"].get("history", []),
        }

        if not target or not target.get("target_time"):
            result["verdict"] = "no_target"
            return result

        distance_km = target.get("distance_km") or 42.195
        target_time = target["target_time"]
        result["target_time"] = target_time
        result["race_name"] = target.get("name")
        result["distance_km"] = distance_km

        # Parse target time to seconds
        parts = target_time.split(":")
        if len(parts) == 3:
            target_secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            target_secs = int(parts[0]) * 60 + int(parts[1])
        else:
            return result

        required_vdot = compute_vdot_from_race(distance_km, target_secs)
        result["required_vdot"] = required_vdot

        if effective_vdot and required_vdot:
            result["vdot_gap"] = round(required_vdot - effective_vdot, 1)

        # What can current fitness produce?
        if effective_vdot:
            pred_secs = vdot_to_race_time(effective_vdot, distance_km)
            if pred_secs:
                h = int(pred_secs // 3600)
                m = int((pred_secs % 3600) // 60)
                s = int(pred_secs % 60)
                result["predicted_time"] = f"{h}:{m:02d}:{s:02d}"
                gap_min = round((pred_secs - target_secs) / 60)
                result["gap_minutes"] = gap_min

        # Verdict based on gap and trend
        gap = result.get("vdot_gap")
        rate = result.get("rate_per_month")
        days_left = None
        if target.get("date"):
            days_left = (date.fromisoformat(target["date"]) - date.today()).days

        if gap is None:
            result["verdict"] = "insufficient_data"
        elif gap <= 0:
            result["verdict"] = "ready"
        elif gap <= 1.0:
            result["verdict"] = "almost"
        elif rate and rate > 0 and days_left and days_left > 0:
            months_needed = gap / rate
            months_left = days_left / 30
            if months_needed <= months_left:
                result["verdict"] = "on_track"
            elif months_needed <= months_left * 1.3:
                result["verdict"] = "tight"
            else:
                result["verdict"] = "at_risk"
        else:
            result["verdict"] = "at_risk"

        return result
    except Exception as e:
        logger.debug("race_readiness_hero failed: %s", e)
        return None


def _todays_capability(conn):
    """What can you run today? Sustainable pace + distance ceiling.

    Returns dict with pace and distance info from threshold + resilience dimensions.
    """
    try:
        from fit.fitness import get_fitness_profile

        profile = get_fitness_profile(conn)
        if not profile:
            return None

        threshold = profile.get("threshold", {})
        resilience = profile.get("resilience", {})

        result = {}

        # Sustainable pace from threshold (speed_per_bpm_z2)
        spd = threshold.get("current_value")
        if spd:
            # Convert speed_per_bpm to approximate pace
            # speed_per_bpm_z2 is in m/min/bpm. At Z2 HR ~130 bpm:
            # actual speed = spd * HR => m/min => pace = 1000/speed sec/km
            z2_hr = 130  # approximate mid-Z2
            speed_m_per_min = spd * z2_hr
            if speed_m_per_min > 0:
                pace_sec_per_km = 1000 / speed_m_per_min * 60
                pace_min = int(pace_sec_per_km // 60)
                pace_sec = int(pace_sec_per_km % 60)
                result["z2_pace"] = f"{pace_min}:{pace_sec:02d}"
                result["z2_pace_label"] = "min/km at Z2"
                result["z2_speed_per_bpm"] = round(spd, 4)
                result["threshold_trend"] = threshold.get("trend")
                result["threshold_rate"] = threshold.get("rate_per_month")
        else:
            result["z2_pace"] = None
            result["z2_pace_label"] = threshold.get("message", "Need 3+ Z2 runs")

        # Distance ceiling from resilience (drift onset km)
        drift_km = resilience.get("current_value")
        if drift_km:
            result["distance_ceiling"] = drift_km
            result["distance_unit"] = "km before HR decouples"
            result["resilience_trend"] = resilience.get("trend")
            result["resilience_rate"] = resilience.get("rate_per_month")
        else:
            result["distance_ceiling"] = None
            result["distance_unit"] = resilience.get(
                "message", "Need split data from long runs"
            )

        return result
    except Exception as e:
        logger.debug("todays_capability failed: %s", e)
        return None


def _fitness_gap_analysis(conn):
    """4 dimensions with current vs required for target race.

    Returns list of dicts: name, current, required, gap, pct, trend, history.
    """
    try:
        from fit.fitness import (
            get_fitness_profile,
            derive_objectives,
        )
        from fit.goals import get_target_race

        profile = get_fitness_profile(conn)
        if not profile:
            return None

        target = get_target_race(conn)
        targets = {}
        if target:
            derived = derive_objectives(conn, target["id"])
            for obj in derived:
                if obj["name"].startswith("_dim_"):
                    dim_name = obj["name"].replace("_dim_", "")
                    targets[dim_name] = obj["target_value"]

        dims = []
        dim_config = [
            ("aerobic", "VO2max", "var(--z2)", True),     # higher is better
            ("threshold", "spd/bpm", "var(--z3)", True),   # higher is better
            ("economy", "spd/bpm", "var(--accent)", True), # higher is better
            ("resilience", "km", "var(--purple)", True),   # higher is better
        ]
        for name, unit, color, higher_better in dim_config:
            dim = profile.get(name, {})
            current = dim.get("current_value")
            required = targets.get(name)
            gap = None
            pct = None
            if current is not None and required is not None and required > 0:
                gap = round(required - current, 2)
                pct = min(int(current / required * 100), 100)

            dims.append({
                "name": name.capitalize(),
                "current": current,
                "required": required,
                "gap": gap,
                "pct": pct,
                "unit": unit,
                "color": color,
                "trend": dim.get("trend"),
                "rate_per_month": dim.get("rate_per_month"),
                "history": dim.get("history", []),
                "message": dim.get("message"),
            })

        return dims
    except Exception as e:
        logger.debug("fitness_gap_analysis failed: %s", e)
        return None


def _body_comp_data(conn):
    """Weight + body composition cards and history for Profile tab.

    Returns dict with weight, body_fat, muscle_mass cards and chart history.
    """
    try:
        rows = conn.execute("""
            SELECT date, weight_kg, body_fat_pct, muscle_mass_kg
            FROM body_comp
            WHERE weight_kg IS NOT NULL
            ORDER BY date DESC LIMIT 20
        """).fetchall()
        if not rows:
            return None

        rows = list(reversed(rows))  # oldest first
        latest = rows[-1]

        # Weight target from goals
        weight_target = None
        try:
            goal = conn.execute(
                "SELECT target_value FROM goals WHERE metric = 'weight' AND active = 1 LIMIT 1"
            ).fetchone()
            if goal:
                weight_target = goal["target_value"]
        except Exception:
            pass

        # Compute change over window
        weight_change = None
        change_span = None
        if len(rows) >= 2:
            weight_change = round(rows[-1]["weight_kg"] - rows[0]["weight_kg"], 1)
            days = (
                date.fromisoformat(rows[-1]["date"])
                - date.fromisoformat(rows[0]["date"])
            ).days
            if days < 60:
                change_span = f"{days}d"
            elif days < 365:
                change_span = f"{days // 30}mo"
            else:
                change_span = f"{days // 365}yr"

        return {
            "weight": round(latest["weight_kg"], 1),
            "weight_target": weight_target,
            "weight_change": weight_change,
            "weight_change_span": change_span,
            "body_fat": round(latest["body_fat_pct"], 1) if latest["body_fat_pct"] else None,
            "muscle_mass": round(latest["muscle_mass_kg"], 1) if latest["muscle_mass_kg"] else None,
            "dates": [r["date"] for r in rows],
            "weight_history": [r["weight_kg"] for r in rows],
            "body_fat_history": [r["body_fat_pct"] for r in rows],
            "muscle_mass_history": [r["muscle_mass_kg"] for r in rows],
        }
    except Exception as e:
        logger.debug("body_comp_data failed: %s", e)
        return None


def _training_phases_json(conn):
    """Return training phases as JSON string for Chart.js phase bar plugin."""
    import json
    try:
        rows = conn.execute("""
            SELECT name, start_date, end_date, status
            FROM training_phases ORDER BY start_date
        """).fetchall()
        phases = []
        for r in rows:
            phases.append({
                "label": r["name"],
                "start": r["start_date"],
                "end": r["end_date"],
                "status": r["status"] or "planned",
                "active": r["status"] == "active",
            })
        return json.dumps(phases) if phases else None
    except Exception:
        return None
