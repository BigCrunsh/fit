"""Dashboard cards, panels, and small section generators."""

import json
import logging
from datetime import date
from pathlib import Path

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
    runs = conn.execute("""
        SELECT date, distance_km, hr_zone, run_type, rpe FROM activities
        WHERE type IN ('running', 'track_running', 'trail_running') ORDER BY date DESC LIMIT 12
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
    avg_cadence = conn.execute("SELECT ROUND(AVG(avg_cadence), 0) as v FROM activities WHERE type IN ('running', 'track_running', 'trail_running') AND avg_cadence IS NOT NULL AND date >= date('now', '-30 days')").fetchone()
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
        "rpe": "Garmin Effort = Aerobic Training Effect × 2 (dashed line, from every run). Your RPE = subjective effort from check-in (solid line, when available). When your RPE consistently exceeds Garmin's estimate, you're more fatigued than the numbers suggest.",
        "race_prediction": "Riegel formula: extrapolates from shorter race times using T2 = T1 × (D2/D1)^1.06. VDOT: from Daniels' tables using VO2max. Both are estimates — actual performance depends on training specificity, fueling, and conditions.",
        "acwr": f"Acute:Chronic Workload Ratio. Current: {acwr_val}. This week's load ÷ avg of previous 4 weeks. <strong style='color:var(--safe)'>0.8-1.3 = safe</strong>, <strong style='color:var(--caution)'>1.3-1.5 = caution</strong>, <strong style='color:var(--danger)'>> 1.5 = injury risk (spike)</strong>, < 0.6 = detraining. Critical for comeback training.",
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
        return generate_race_countdown(conn)
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
        from fit.config import load_config
        config = load_config()
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
        run = conn.execute("""
            SELECT a.id, a.name, a.date, a.distance_km, a.duration_min
            FROM activities a
            WHERE a.type IN ('running', 'track_running', 'trail_running') AND a.splits_status = 'done'
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
    """Fitness profile for dashboard rendering."""
    try:
        from fit.fitness import get_fitness_profile
        return get_fitness_profile(conn)
    except Exception:
        return None


def _checkpoint_data(conn):
    """Checkpoint races with derived targets."""
    try:
        from fit.fitness import derive_checkpoint_targets
        return derive_checkpoint_targets(conn)
    except Exception:
        return []
