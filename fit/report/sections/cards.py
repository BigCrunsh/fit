"""Dashboard section builders — status cards, checkin, journey, alerts, coaching, definitions."""

import json
import logging
from datetime import date
from pathlib import Path

from fit.report.headline import generate_headline

logger = logging.getLogger(__name__)

SAFE = "#22c55e"
CAUTION = "#eab308"
DANGER = "#ef4444"
Z12 = "#38bdf8"
Z3 = "#f59e0b"
Z45 = "#f97316"
ACCENT = "#818cf8"


# ── Headline ──

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
    )


# ── Status Cards ──

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
        fields.append(f"\U0001f4a7 {row['hydration']}")
    if row["alcohol"] is not None:
        detail = f" ({row['alcohol_detail']})" if row["alcohol_detail"] else ""
        fields.append(f"\U0001f37a {row['alcohol']}{detail}")
    if row["legs"]:
        fields.append(f"\U0001f9b5 {row['legs']}")
    if row["eating"]:
        fields.append(f"\U0001f37d\ufe0f {row['eating']}")
    if row["water_liters"]:
        fields.append(f"\U0001f4a7 {row['water_liters']}L")
    if row["energy"]:
        fields.append(f"\u26a1 {row['energy']}")
    if row["sleep_quality"]:
        fields.append(f"\U0001f634 {row['sleep_quality']}")
    if row["rpe"] is not None:
        fields.append(f"\U0001f4aa RPE {row['rpe']}")
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
    weeks = conn.execute("SELECT * FROM weekly_agg ORDER BY week DESC LIMIT 2").fetchall()
    if len(weeks) < 2:
        return None
    this, last = weeks[0], weeks[1]
    km_delta = (this["run_km"] or 0) - (last["run_km"] or 0)
    runs_delta = (this["run_count"] or 0) - (last["run_count"] or 0)
    parts = []
    parts.append(f"{this['run_km'] or 0:.0f}km ({'+' if km_delta >= 0 else ''}{km_delta:.0f}km)")
    parts.append(f"{this['run_count'] or 0} runs ({'+' if runs_delta >= 0 else ''}{runs_delta})")
    if this["z12_pct"] is not None and last["z12_pct"] is not None:
        parts.append(f"Z1+Z2: {last['z12_pct']:.0f}%→{this['z12_pct']:.0f}%")
    if this["acwr"] is not None:
        parts.append(f"ACWR {this['acwr']:.2f}")
    if date.today().weekday() < 6:
        parts.append("(week in progress)")
    return " · ".join(parts)


# ── Run Timeline ──

def _run_timeline(conn):
    runs = conn.execute("""
        SELECT date, distance_km, hr_zone, run_type, rpe FROM activities
        WHERE type = 'running' ORDER BY date DESC LIMIT 12
    """).fetchall()
    max_km = max((r["distance_km"] or 0 for r in runs), default=1) or 1
    result = []
    for r in runs:
        km = r["distance_km"] or 0
        zone = r["hr_zone"] or "Z2"
        color = Z12 if zone in ("Z1", "Z2") else Z3 if zone == "Z3" else Z45
        result.append({
            "date": r["date"][5:],
            "distance_km": f"{km:.1f}",
            "width": max(10, int(km / max_km * 100)),
            "color": color,
            "zone": zone,
            "run_type": r["run_type"] or "",
            "rpe": r["rpe"],
        })
    return result


# ── Goal Progress ──

def _goal_progress(conn):
    results = []

    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    if vo2:
        results.append({"icon": "\U0001f4c8", "label": "VO2max", "current": f"{vo2['vo2max']:.0f}", "target": "51", "unit": "",
                        "pct": min(vo2["vo2max"] / 51 * 100, 100), "color": SAFE if vo2["vo2max"] >= 50 else CAUTION,
                        "tooltip": f"Maximum oxygen uptake. Current: {vo2['vo2max']:.0f} ml/kg/min. Need ≥50 for sub-4:00 marathon. Improves ~1/month with consistent training."})

    weight = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
    if weight:
        w = weight["weight_kg"]
        pct = max(0, (78.3 - w) / (78.3 - 75) * 100)
        results.append({"icon": "\u2696\ufe0f", "label": "Weight", "current": f"{w:.1f}", "target": "75", "unit": "kg",
                        "pct": min(pct, 100), "color": SAFE if w <= 76 else CAUTION if w <= 78 else DANGER,
                        "tooltip": f"Current: {w:.1f}kg. Target: 75kg through training volume. Each kg lost saves ~2-3 sec/km over 42km = 7-10 min total."})

    streak = conn.execute("SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
    if streak:
        s = streak[0] or 0
        results.append({"icon": "\U0001f525", "label": "Streak", "current": str(s), "target": "8", "unit": "wk",
                        "pct": min(s / 8 * 100, 100), "color": SAFE if s >= 6 else CAUTION if s >= 3 else DANGER,
                        "tooltip": f"Consecutive weeks with 3+ runs. Current: {s}. Target: 8 weeks of consistency before increasing intensity. The #1 predictor of marathon readiness."})

    next_race = conn.execute("""
        SELECT name, date, distance, target_time FROM race_calendar
        WHERE status = 'registered' ORDER BY date LIMIT 1
    """).fetchone()
    if next_race:
        from datetime import date as d
        days_left = (d.fromisoformat(next_race["date"]) - d.today()).days
        target_str = f" Target: {next_race['target_time']}." if next_race["target_time"] else ""
        results.append({"icon": "\U0001f3c1", "label": next_race["name"][:15], "current": str(days_left), "target": "", "unit": "days",
                        "pct": None, "color": ACCENT,
                        "tooltip": f"{next_race['name']} ({next_race['distance']}) on {next_race['date']}.{target_str} {days_left} days to go."})

    return results


# ── Recent Alerts ──

def _recent_alerts(conn):
    try:
        from fit.alerts import get_recent_alerts
        return get_recent_alerts(conn, days=7)
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
            width = min(abs(sr) * 100, 50)
            results.append({
                "label": label, "r": f"{sr:+.2f}", "n": r["sample_size"],
                "confidence": r["confidence"], "color": color, "width": int(width),
                "direction": "positive" if sr > 0 else "negative",
            })
        return results
    except Exception:
        return []


# ── Phase Compliance ──

def _phase_compliance(conn):
    phase = conn.execute("SELECT * FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
    if not phase:
        return None
    from fit.goals import get_phase_compliance
    compliance = get_phase_compliance(conn, phase["id"])
    if compliance.get("status") == "no_data":
        return {"phase_name": f"{phase['phase']}: {phase['name']}", "dimensions": [], "no_data": True}
    return {"phase_name": f"{phase['phase']}: {phase['name']}", "dimensions": compliance.get("dimensions", []), "no_data": False}


# ── Calibration Panel ──

def _calibration_panel(conn):
    from fit.calibration import get_calibration_status
    return get_calibration_status(conn)


# ── Data Health Panel ──

def _data_health_panel(conn):
    from fit.data_health import check_data_sources
    return check_data_sources(conn)


# ── Sleep Mismatches ──

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


# ── Coaching ──

def _coaching(conn):
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    coaching_path = Path(db_path).parent / "reports" / "coaching.json"
    if not coaching_path.exists():
        return None

    data = json.loads(coaching_path.read_text())
    last_sync = conn.execute("SELECT MAX(date) FROM daily_health").fetchone()[0]
    stale = data.get("report_date", "") < last_sync if last_sync else False

    styles = {
        "critical": {"bg": "rgba(239,68,68,0.06)", "border": "rgba(239,68,68,0.15)", "color": DANGER, "icon": "\U0001f6a8"},
        "warning": {"bg": "rgba(249,115,22,0.06)", "border": "rgba(249,115,22,0.15)", "color": Z45, "icon": "\u26a0\ufe0f"},
        "positive": {"bg": "rgba(34,197,94,0.06)", "border": "rgba(34,197,94,0.15)", "color": SAFE, "icon": "\u2705"},
        "info": {"bg": "rgba(59,130,246,0.06)", "border": "rgba(59,130,246,0.15)", "color": "#3b82f6", "icon": "\U0001f4ca"},
        "target": {"bg": "rgba(167,139,250,0.06)", "border": "rgba(167,139,250,0.15)", "color": ACCENT, "icon": "\U0001f3af"},
    }
    insights = [{**styles.get(i.get("type", "info"), styles["info"]), "title": i.get("title", ""), "body": i.get("body", "")}
                for i in data.get("insights", [])]
    return {"generated_at": data.get("generated_at", ""), "stale": stale, "insights": insights}


# ── Definitions ──

def _definitions(conn):
    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    vo2_val = vo2["vo2max"] if vo2 else "?"
    acwr_row = conn.execute("SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
    acwr_val = f"{acwr_row['acwr']:.2f}" if acwr_row else "?"
    weight_row = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
    weight_val = f"{weight_row['weight_kg']:.1f}" if weight_row else "?"
    avg_sleep = conn.execute("SELECT ROUND(AVG(sleep_duration_hours), 1) as v FROM daily_health WHERE date >= date('now', '-14 days')").fetchone()
    avg_sleep_val = avg_sleep["v"] if avg_sleep and avg_sleep["v"] else "?"
    avg_deep = conn.execute("SELECT ROUND(AVG(deep_sleep_hours), 2) as v FROM daily_health WHERE date >= date('now', '-14 days')").fetchone()
    avg_deep_val = avg_deep["v"] if avg_deep and avg_deep["v"] else "?"
    avg_cadence = conn.execute("SELECT ROUND(AVG(avg_cadence), 0) as v FROM activities WHERE type='running' AND avg_cadence IS NOT NULL AND date >= date('now', '-30 days')").fetchone()
    avg_cadence_val = avg_cadence["v"] if avg_cadence and avg_cadence["v"] else "?"
    avg_stress = conn.execute("SELECT ROUND(AVG(avg_stress_level), 0) as v FROM daily_health WHERE date >= date('now', '-7 days')").fetchone()
    avg_stress_val = avg_stress["v"] if avg_stress and avg_stress["v"] else "?"

    return {
        "speed_per_bpm": "Speed per heartbeat: (meters/min) \u00f7 avg HR. Higher = more efficient. The Z2-filtered line (bold) shows pure aerobic fitness at controlled effort \u2014 the most honest fitness signal.",
        "vo2max": f"Maximum oxygen uptake (ml/kg/min). Current: {vo2_val}. For sub-4:00 marathon at ~75kg, you need \u226550. Declines ~3-5% per month of inactivity, recovers ~1/month with consistent training.",
        "training_load": "Garmin's EPOC-based measure of physiological stress per session. <strong style='color:var(--z12)'>< 150 = easy</strong>, <strong style='color:var(--z3)'>150-250 = moderate</strong>, <strong style='color:var(--z45)'>250-350 = hard</strong>, <strong style='color:var(--danger)'>> 350 = overload risk</strong>. A typical well-trained week sums to 400-800 across all sessions.",
        "readiness": "Garmin's composite 0-100 score combining sleep quality, recovery time, HRV status, stress, and recent training load. <strong style='color:var(--safe)'>\u226575 = ready for quality sessions</strong>, <strong style='color:var(--caution)'>50-74 = easy day</strong>, <strong style='color:var(--danger)'>< 50 = rest</strong>.",
        "sleep": f"Your 14d avg: {avg_sleep_val}h total, {avg_deep_val}h deep. For runners: \u22651h deep + \u22651.5h REM is good. Total \u22657.5h supports adaptation. Post-hard-effort, deep sleep often collapses \u2014 a key recovery signal.",
        "stress_battery": f"Your 7d avg stress: {avg_stress_val}. Body Battery: energy reserve (0-100), charged by rest, drained by activity. Stress: 0-100 from HRV. When stress rises and battery drops simultaneously, your body is under load.",
        "weight": f"Current: {weight_val} kg. Each kg lost saves ~2-3 sec/km at the same effort. Over 42.2 km, 3 kg = ~7-10 min faster. Target weight through training volume (not dieting).",
        "zones": "HR zones by training TIME (minutes per week), not run count. Compared to your active training phase targets. Blue = Z1+Z2 (easy), amber = Z3 (moderate), orange = Z4+Z5 (hard). Phase 1 targets ~90% easy.",
        "volume": "Total running km per week. The darker segment shows the longest single run. For marathon training: long run should build gradually to 30-32 km, weekly volume to 50-60 km at peak.",
        "cadence": f"Your 30d avg cadence: {avg_cadence_val} spm. Below 165 often indicates overstriding. Target: 170-180. Tends to improve with fatigue resilience and form work.",
        "rpe": "Garmin Effort = Aerobic Training Effect \u00d7 2 (dashed line, from every run). Your RPE = subjective effort from check-in (solid line, when available). When your RPE consistently exceeds Garmin's estimate, you're more fatigued than the numbers suggest.",
        "race_prediction": "Riegel formula: extrapolates from shorter race times using T2 = T1 \u00d7 (D2/D1)^1.06. VDOT: from Daniels' tables using VO2max. Both are estimates \u2014 actual performance depends on training specificity, fueling, and conditions.",
        "acwr": f"Acute:Chronic Workload Ratio. Current: {acwr_val}. This week's load \u00f7 avg of previous 4 weeks. <strong style='color:var(--safe)'>0.8-1.3 = safe</strong>, <strong style='color:var(--caution)'>1.3-1.5 = caution</strong>, <strong style='color:var(--danger)'>> 1.5 = injury risk (spike)</strong>, < 0.6 = detraining. Critical for comeback training.",
    }


# ── Helpers ──

def _subtitle(conn):
    h = conn.execute("SELECT COUNT(*) FROM daily_health").fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
    return f"{h}d \u00b7 {a} activities \u00b7 {c} check-ins"
