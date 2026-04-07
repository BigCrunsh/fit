"""Dashboard HTML generator — queries DB, builds Chart.js configs, renders Jinja2."""

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from fit.report.headline import generate_headline
from fit.narratives import (
    generate_trend_badges,
    generate_why_connectors,
    generate_race_countdown,
    detect_walk_break_need,
    generate_z2_remediation,
)

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
CHARTJS_PATH = Path(__file__).parent / "chartjs.min.js"
ANNOTATION_PATH = Path(__file__).parent / "chartjs-annotation.min.js"
DATE_ADAPTER_PATH = Path(__file__).parent / "chartjs-date-adapter.min.js"

SAFE = "#22c55e"
CAUTION = "#eab308"
DANGER = "#ef4444"
Z12 = "#38bdf8"
Z3 = "#f59e0b"
Z45 = "#f97316"
ACCENT = "#818cf8"


def generate_dashboard(conn: sqlite3.Connection, output_path: Path) -> None:
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("dashboard.html")

    chartjs_code = CHARTJS_PATH.read_text() if CHARTJS_PATH.exists() else ""
    annotation_code = ANNOTATION_PATH.read_text() if ANNOTATION_PATH.exists() else ""
    date_adapter_code = DATE_ADAPTER_PATH.read_text() if DATE_ADAPTER_PATH.exists() else ""

    context = {
        "title": "fit — Dashboard",
        "subtitle": _subtitle(conn),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "chartjs_code": chartjs_code,
        "annotation_code": annotation_code,
        "date_adapter_code": date_adapter_code,
        "tabs": [
            {"id": "today", "label": "Today"},
            {"id": "training", "label": "Training"},
            {"id": "body", "label": "Body"},
            {"id": "fitness", "label": "Fitness"},
            {"id": "coach", "label": "Coach"},
        ],
        "headline": _headline(conn),
        "headline_signal": _headline_signal(conn),
        "prediction_summary": _prediction_summary(conn),
        "status_cards": _status_cards(conn),
        "checkin": _checkin(conn),
        "journey": _journey(conn),
        "wow": _week_over_week(conn),
        "run_timeline": _run_timeline(conn),
        "charts": _all_charts(conn),
        "definitions": _definitions(conn),
        "race_prediction": _race_prediction(conn),
        "coaching": _coaching(conn),
        "recent_alerts": _recent_alerts(conn),
        "rpe_checkin_count": conn.execute("SELECT COUNT(*) FROM activities WHERE type IN ('running', 'track_running', 'trail_running') AND rpe IS NOT NULL").fetchone()[0],
        "rpe_garmin_count": conn.execute("SELECT COUNT(*) FROM activities WHERE type IN ('running', 'track_running', 'trail_running') AND aerobic_te IS NOT NULL AND date >= date('now', '-90 days')").fetchone()[0],
        "run_count": conn.execute("SELECT COUNT(*) FROM activities WHERE type IN ('running', 'track_running', 'trail_running')").fetchone()[0],
        "milestones": _milestones(conn),
        "goal_progress": _goal_progress(conn),
        "correlation_bars": _correlation_bars(conn),
        "phase_compliance": _phase_compliance(conn),
        "calibration_panel": _calibration_panel(conn),
        "data_health": _data_health_panel(conn),
        "sleep_mismatches": _sleep_mismatches(conn),
        "trend_badges": _trend_badges(conn),
        "why_connectors": _why_connectors(conn),
        "race_countdown": _race_countdown(conn),
        "walk_break": _walk_break(conn),
        "z2_remediation": _z2_remediation(conn),
        "rolling_correlations": _rolling_correlations(conn),
        "split_data": _split_data(conn),
        "plan_adherence": _plan_adherence(conn),
        "upcoming_races": _upcoming_races(conn),
    }

    html = template.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    logger.info("Dashboard written to %s (%d bytes)", output_path, len(html))


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
        from fit.analysis import predict_marathon_time
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
        preds = predict_marathon_time(races=race_data, vo2max=vo2["vo2max"] if vo2 else None)

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
    # Check if current week is incomplete
    if date.today().weekday() < 6:  # Not Sunday
        parts.append("(week in progress)")
    return " · ".join(parts)


# ── Run Timeline ──

def _run_timeline(conn):
    runs = conn.execute("""
        SELECT date, distance_km, hr_zone, run_type, rpe FROM activities
        WHERE type IN ('running', 'track_running', 'trail_running') ORDER BY date DESC LIMIT 12
    """).fetchall()
    max_km = max((r["distance_km"] or 0 for r in runs), default=1) or 1
    result = []
    for r in runs:
        km = r["distance_km"] or 0
        zone = r["hr_zone"] or "Z2"
        color = Z12 if zone in ("Z1", "Z2") else Z3 if zone == "Z3" else Z45
        result.append({
            "date": r["date"][5:],  # MM-DD
            "distance_km": f"{km:.1f}",
            "width": max(10, int(km / max_km * 100)),
            "color": color,
            "zone": zone,
            "run_type": r["run_type"] or "",
            "rpe": r["rpe"],
        })
    return result


# ── Charts ──

def _all_charts(conn):
    charts = []

    # Event annotations for all time-series charts
    event_annots = _get_event_annotations(conn)

    # Volume (Training tab)
    weeks = conn.execute("SELECT week, run_km, longest_run_km FROM weekly_agg WHERE run_km > 0 ORDER BY week").fetchall()
    if weeks:
        # Get phase volume target for annotation
        phase_vol = conn.execute("SELECT weekly_km_min, weekly_km_max FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
        vol_annots = {}
        if phase_vol and phase_vol["weekly_km_min"]:
            vol_annots["target_lo"] = {"type": "line", "yMin": phase_vol["weekly_km_min"], "yMax": phase_vol["weekly_km_min"],
                                       "borderColor": SAFE + "30", "borderDash": [4, 4], "borderWidth": 1}
            vol_annots["target_hi"] = {"type": "line", "yMin": phase_vol["weekly_km_max"], "yMax": phase_vol["weekly_km_max"],
                                       "borderColor": SAFE + "30", "borderDash": [4, 4], "borderWidth": 1,
                                       "label": {"content": f"target {phase_vol['weekly_km_min']}-{phase_vol['weekly_km_max']}km",
                                                 "display": True, "position": "end", "font": {"size": 7}, "color": SAFE + "60"}}
        charts.append({"id": "chart-volume", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [w["week"] for w in weeks],
                     "datasets": [{"label": "km/week", "data": [w["run_km"] for w in weeks],
                                   "backgroundColor": "rgba(56,189,248,0.5)", "borderRadius": 4}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                                                         "annotation": {"annotations": vol_annots} if vol_annots else {}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Load (Training tab)
    runs = conn.execute("SELECT date, training_load FROM activities WHERE type IN ('running', 'track_running', 'trail_running') AND training_load IS NOT NULL ORDER BY date").fetchall()
    if runs:
        colors = [Z12 + "99" if (r["training_load"] or 0) < 150 else Z3 + "99" if r["training_load"] < 250 else Z45 + "99" if r["training_load"] < 350 else DANGER + "99" for r in runs]
        charts.append({"id": "chart-load", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [r["date"] for r in runs],
                     "datasets": [{"label": "Load", "data": [r["training_load"] for r in runs],
                                   "backgroundColor": colors, "borderRadius": 3}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                        "annotation": {"annotations": {
                            "easy": {"type": "line", "yMin": 150, "yMax": 150,
                                     "borderColor": SAFE + "25", "borderDash": [4, 4], "borderWidth": 1,
                                     "label": {"content": "easy <150", "display": True, "position": "start", "font": {"size": 7}, "color": SAFE + "50"}},
                            "hard": {"type": "line", "yMin": 350, "yMax": 350,
                                     "borderColor": DANGER + "25", "borderDash": [4, 4], "borderWidth": 1,
                                     "label": {"content": "overload >350", "display": True, "position": "end", "font": {"size": 7}, "color": DANGER + "50"}},
                        }}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Readiness (Body tab) — standalone bar chart, no competing lines
    health = conn.execute("SELECT date, training_readiness, resting_heart_rate, hrv_last_night FROM daily_health WHERE date >= date('now','-21 days') ORDER BY date").fetchall()
    if health:
        r_colors = [SAFE + "80" if (h["training_readiness"] or 0) >= 75 else CAUTION + "80" if (h["training_readiness"] or 0) >= 50 else DANGER + "80" for h in health]
        charts.append({"id": "chart-readiness", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [h["date"] for h in health],
                     "datasets": [
                         {"label": "Readiness", "data": [h["training_readiness"] for h in health], "backgroundColor": r_colors, "borderRadius": 3},
                     ]},
            "options": {"responsive": True,
                        "plugins": {"legend": {"display": False},
                                    "annotation": {"annotations": {
                            "good": {"type": "box", "yMin": 75, "yMax": 100,
                                     "backgroundColor": SAFE + "08", "borderWidth": 0,
                                     "label": {"content": "Ready >=75", "display": True, "position": "start", "font": {"size": 7}, "color": SAFE + "60"}},
                            "rest": {"type": "box", "yMin": 0, "yMax": 50,
                                     "backgroundColor": DANGER + "06", "borderWidth": 0,
                                     "label": {"content": "Rest <50", "display": True, "position": "start", "font": {"size": 7}, "color": DANGER + "40"}},
                        }}},
                        "scales": {
                "y": {"min": 0, "max": 100, "grid": {"color": "rgba(255,255,255,0.03)"}},
                "x": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # RHR + HRV (Body tab) — separate chart for two recovery signals
    if health:
        charts.append({"id": "chart-rhr-hrv", "config": json.dumps({
            "type": "line",
            "data": {"labels": [h["date"] for h in health],
                     "datasets": [
                         {"label": "RHR (bpm)", "data": [h["resting_heart_rate"] for h in health],
                          "borderColor": DANGER, "borderWidth": 2, "pointRadius": 3, "fill": False, "yAxisID": "y"},
                         {"label": "HRV (ms)", "data": [h["hrv_last_night"] for h in health],
                          "borderColor": ACCENT, "borderWidth": 2, "pointRadius": 3, "fill": False, "yAxisID": "y1"},
                     ]},
            "options": {"responsive": True,
                        "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
                        "scales": {
                "y": {"position": "left", "grid": {"color": "rgba(255,255,255,0.03)"},
                       "title": {"display": True, "text": "RHR (bpm)", "color": DANGER}},
                "y1": {"position": "right", "grid": {"drawOnChartArea": False},
                        "title": {"display": True, "text": "HRV (ms)", "color": ACCENT}},
                "x": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Sleep (Body tab)
    sleep = conn.execute("SELECT date, deep_sleep_hours, rem_sleep_hours, light_sleep_hours FROM daily_health WHERE date >= date('now','-21 days') ORDER BY date").fetchall()
    if sleep:
        charts.append({"id": "chart-sleep", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [s["date"] for s in sleep],
                     "datasets": [
                         {"label": "Deep", "data": [s["deep_sleep_hours"] for s in sleep], "backgroundColor": "rgba(56,189,248,0.7)", "stack": "s"},
                         {"label": "REM", "data": [s["rem_sleep_hours"] for s in sleep], "backgroundColor": "rgba(129,140,248,0.6)", "stack": "s"},
                         {"label": "Light", "data": [s["light_sleep_hours"] for s in sleep], "backgroundColor": "rgba(100,116,139,0.35)", "stack": "s"},
                     ]},
            "options": {"responsive": True,
                        "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}},
                                    "annotation": {"annotations": {
                                        "target": {"type": "line", "yMin": 7.5, "yMax": 7.5,
                                                   "borderColor": SAFE + "30", "borderDash": [4, 4], "borderWidth": 1,
                                                   "label": {"content": "≥7.5h", "display": True, "position": "end", "font": {"size": 7}, "color": SAFE + "60"}},
                                        "avg_total": {"type": "line",
                                                      "yMin": sum((s["deep_sleep_hours"] or 0) + (s["rem_sleep_hours"] or 0) + (s["light_sleep_hours"] or 0) for s in sleep) / max(len(sleep), 1),
                                                      "yMax": sum((s["deep_sleep_hours"] or 0) + (s["rem_sleep_hours"] or 0) + (s["light_sleep_hours"] or 0) for s in sleep) / max(len(sleep), 1),
                                                      "borderColor": SAFE + "40", "borderDash": [4, 3],
                                                      "label": {"content": "avg", "display": True, "position": "end", "font": {"size": 8}}},
                                    }}},
                        "scales": {"x": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Stress vs Body Battery (Body tab — W2)
    stress = conn.execute("""
        SELECT date, avg_stress_level, body_battery_high
        FROM daily_health WHERE date >= date('now','-21 days') AND (avg_stress_level IS NOT NULL OR body_battery_high IS NOT NULL)
        ORDER BY date
    """).fetchall()
    if stress:
        charts.append({"id": "chart-stress", "config": json.dumps({
            "type": "line",
            "data": {"labels": [s["date"] for s in stress],
                     "datasets": [
                         {"label": "Battery Peak", "data": [s["body_battery_high"] for s in stress],
                          "borderColor": SAFE, "backgroundColor": SAFE + "10", "fill": True, "borderWidth": 1.5, "pointRadius": 0},
                         {"label": "Avg Stress", "data": [s["avg_stress_level"] for s in stress],
                          "borderColor": DANGER, "borderWidth": 1.5, "pointRadius": 2, "fill": False},
                     ]},
            "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
                        "scales": {"y": {"min": 0, "max": 100, "grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "x": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Weight (Body tab) with race target
    weight = conn.execute("SELECT date, weight_kg, body_fat_pct FROM body_comp ORDER BY date").fetchall()
    if weight:
        weight_target = conn.execute("SELECT target_value FROM goals WHERE type = 'metric' AND name LIKE '%eight%' AND active = 1 LIMIT 1").fetchone()
        weight_annots = dict(event_annots)
        if weight_target and weight_target["target_value"]:
            weight_annots["target"] = {
                "type": "line", "yMin": weight_target["target_value"], "yMax": weight_target["target_value"],
                "borderColor": SAFE + "60", "borderDash": [6, 3],
                "label": {"content": f"Target {weight_target['target_value']}kg", "display": True, "position": "end", "font": {"size": 8}},
            }
        datasets = [{"label": "Weight", "data": [w["weight_kg"] for w in weight],
                      "borderColor": Z3, "backgroundColor": Z3 + "15", "fill": True, "borderWidth": 2, "pointRadius": 3, "yAxisID": "y"}]
        # Body fat second y-axis if data exists
        bf_data = [w["body_fat_pct"] for w in weight]
        has_bf = any(v is not None for v in bf_data)
        scales = {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                  "y": {"grid": {"color": "rgba(255,255,255,0.03)"}, "position": "left", "title": {"display": True, "text": "kg"}}}
        if has_bf:
            datasets.append({"label": "Body Fat %", "data": bf_data, "borderColor": DANGER + "60",
                              "borderWidth": 1.5, "pointRadius": 2, "fill": False, "yAxisID": "y1", "spanGaps": True})
            scales["y1"] = {"grid": {"drawOnChartArea": False}, "position": "right",
                            "title": {"display": True, "text": "%"}, "min": 5, "max": 30}
        charts.append({"id": "chart-weight", "config": json.dumps({
            "type": "line",
            "data": {"labels": [w["date"] for w in weight], "datasets": datasets},
            "options": {"responsive": True, "plugins": {"legend": {"display": has_bf, "position": "bottom", "labels": {"boxWidth": 12}},
                                                         "annotation": {"annotations": weight_annots}},
                        "scales": scales}
        })})

    # Speed per BPM (Fitness tab — hero chart)
    eff = conn.execute("SELECT date, speed_per_bpm, speed_per_bpm_z2 FROM activities WHERE type IN ('running', 'track_running', 'trail_running') AND speed_per_bpm IS NOT NULL AND date >= date('now','-90 days') ORDER BY date").fetchall()
    if eff:
        charts.append({"id": "chart-efficiency", "config": json.dumps({
            "type": "line",
            "data": {"labels": [e["date"] for e in eff],
                     "datasets": [
                         {"label": "All runs", "data": [e["speed_per_bpm"] for e in eff], "borderColor": Z3 + "50", "borderWidth": 1.5, "pointRadius": 2, "pointBackgroundColor": Z3 + "40", "fill": False},
                         {"label": "Z2 only (key signal)", "data": [e["speed_per_bpm_z2"] for e in eff], "borderColor": ACCENT, "borderWidth": 2.5, "pointRadius": 4, "fill": False, "spanGaps": True},
                     ]},
            "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}},
                                                         "annotation": {"annotations": event_annots}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}, "title": {"display": True, "text": "m/min/bpm (higher=better)"}}}}
        })})

    # VO2max (Fitness tab)
    vo2 = conn.execute("SELECT date, vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date").fetchall()
    if vo2:
        charts.append({"id": "chart-vo2", "config": json.dumps({
            "type": "line",
            "data": {"labels": [v["date"] for v in vo2],
                     "datasets": [{"label": "VO2max", "data": [v["vo2max"] for v in vo2],
                                   "borderColor": ACCENT, "backgroundColor": ACCENT + "20", "fill": True, "borderWidth": 2, "pointRadius": 3}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                                                         "annotation": {"annotations": {**event_annots, "sub4": {"type": "line", "yMin": 50, "yMax": 50, "borderColor": CAUTION + "60", "borderDash": [6, 3], "label": {"content": "Sub-4 ≥50", "display": True, "position": "end", "font": {"size": 8}}}}}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Zone distribution (Fitness tab) with phase target
    zone_weeks = conn.execute("SELECT week, z1_min, z2_min, z3_min, z4_min, z5_min FROM weekly_agg WHERE (z1_min+z2_min+z3_min+z4_min+z5_min) > 0 ORDER BY week DESC LIMIT 8").fetchall()
    if zone_weeks:
        zone_weeks = list(reversed(zone_weeks))
        # Get phase target for subtitle
        phase = conn.execute("SELECT z12_pct_target, z45_pct_target, name FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
        phase_note = f" (Phase target: Z1+Z2 ≥{phase['z12_pct_target']}%)" if phase and phase["z12_pct_target"] else ""
        charts.append({"id": "chart-zones", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [w["week"] for w in zone_weeks],
                     "datasets": [
                         {"label": f"Z1+Z2{phase_note}", "data": [(w["z1_min"] or 0) + (w["z2_min"] or 0) for w in zone_weeks], "backgroundColor": Z12 + "80", "stack": "s"},
                         {"label": "Z3", "data": [w["z3_min"] or 0 for w in zone_weeks], "backgroundColor": Z3 + "80", "stack": "s"},
                         {"label": "Z4+Z5", "data": [(w["z4_min"] or 0) + (w["z5_min"] or 0) for w in zone_weeks], "backgroundColor": Z45 + "80", "stack": "s"},
                     ]},
            "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
                        "scales": {"x": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}, "title": {"display": True, "text": "minutes"}}}}
        })})

    # ACWR trend (Body tab) — line chart with safe zone band
    acwr_data = conn.execute("""
        SELECT week, acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week
    """).fetchall()
    if acwr_data:
        # Color each point based on zone
        point_colors = [SAFE if 0.8 <= (a["acwr"] or 0) <= 1.3 else CAUTION if (a["acwr"] or 0) <= 1.5 else DANGER for a in acwr_data]
        charts.append({"id": "chart-acwr", "config": json.dumps({
            "type": "line",
            "data": {"labels": [a["week"] for a in acwr_data],
                     "datasets": [{"label": "ACWR", "data": [a["acwr"] for a in acwr_data],
                                   "borderColor": ACCENT, "borderWidth": 2, "pointRadius": 4,
                                   "pointBackgroundColor": point_colors, "pointBorderColor": point_colors,
                                   "fill": False}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                        "annotation": {"annotations": {
                            "safe_zone": {"type": "box", "yMin": 0.8, "yMax": 1.3,
                                          "backgroundColor": SAFE + "10", "borderWidth": 0,
                                          "label": {"content": "Safe zone 0.8-1.3", "display": True, "position": "end",
                                                    "font": {"size": 8}, "color": SAFE + "60"}},
                            "danger": {"type": "line", "yMin": 1.5, "yMax": 1.5, "borderColor": DANGER + "60", "borderDash": [6, 3],
                                       "label": {"content": "1.5 danger", "display": True, "position": "end", "font": {"size": 8}}},
                        }}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"min": 0, "max": 2.5, "grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Run type breakdown stacked (Training tab)
    type_weeks = conn.execute("""
        SELECT strftime('%Y-W', date, 'weekday 0', '-6 days') ||
               substr('0' || (cast(strftime('%W', date) as integer)), -2) as week,
               run_type, COUNT(*) as n
        FROM activities WHERE type IN ('running', 'track_running', 'trail_running') AND run_type IS NOT NULL
        GROUP BY week, run_type ORDER BY week
    """).fetchall()
    if type_weeks:
        weeks_set = sorted({r["week"] for r in type_weeks})[-12:]  # last 12 weeks
        type_names = ["easy", "long", "tempo", "intervals", "recovery", "race"]
        type_colors = {"easy": Z12, "long": Z12 + "CC", "tempo": Z3, "intervals": Z45, "recovery": Z12 + "66", "race": Z45 + "CC"}
        datasets = []
        for t in type_names:
            data = []
            for w in weeks_set:
                count = sum(r["n"] for r in type_weeks if r["week"] == w and r["run_type"] == t)
                data.append(count)
            if any(d > 0 for d in data):
                datasets.append({"label": t, "data": data, "backgroundColor": type_colors.get(t, Z12), "stack": "s"})
        if datasets:
            charts.append({"id": "chart-runtypes", "config": json.dumps({
                "type": "bar",
                "data": {"labels": weeks_set, "datasets": datasets},
                "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
                            "scales": {"x": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}},
                                       "y": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"},
                                             "title": {"display": True, "text": "runs"}}}}
            })})

    # Cadence trend (Fitness tab — W3)
    cadence = conn.execute("""
        SELECT date, avg_cadence FROM activities
        WHERE type IN ('running', 'track_running', 'trail_running') AND avg_cadence IS NOT NULL AND date >= date('now','-90 days')
        ORDER BY date
    """).fetchall()
    if cadence:
        charts.append({"id": "chart-cadence", "config": json.dumps({
            "type": "line",
            "data": {"labels": [c["date"] for c in cadence],
                     "datasets": [{"label": "Cadence (spm)", "data": [c["avg_cadence"] for c in cadence],
                                   "borderColor": Z12, "borderWidth": 2, "pointRadius": 3, "fill": False}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                        "annotation": {"annotations": {**event_annots, "threshold": {"type": "line", "yMin": 165, "yMax": 165,
                                       "borderColor": CAUTION + "60", "borderDash": [6, 3],
                                       "label": {"content": "Low threshold 165", "display": True, "position": "end", "font": {"size": 8}}}}}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # RPE chart (Fitness tab) — Garmin effort (from aerobic_te) vs actual RPE
    # aerobic_te is 1-5 Garmin scale, map to RPE 1-10: RPE ≈ aerobic_te * 2
    rpe_data = conn.execute("""
        SELECT a.date, a.rpe as actual_rpe, a.aerobic_te,
               ROUND(a.aerobic_te * 2, 1) as garmin_rpe
        FROM activities a
        WHERE a.type IN ('running', 'track_running', 'trail_running') AND a.aerobic_te IS NOT NULL
        AND a.date >= date('now', '-90 days')
        ORDER BY a.date
    """).fetchall()
    if len(rpe_data) >= 3:
        datasets = [
            {"label": "Garmin Effort (TE×2)", "data": [r["garmin_rpe"] for r in rpe_data],
             "borderColor": Z12, "borderWidth": 1.5, "borderDash": [4, 2], "pointRadius": 2, "fill": False},
        ]
        # Add actual RPE line if any check-in RPE data exists
        actual_rpes = [r["actual_rpe"] for r in rpe_data]
        if any(v is not None for v in actual_rpes):
            datasets.append({"label": "Your RPE (checkin)", "data": actual_rpes,
                             "borderColor": Z45, "borderWidth": 2, "pointRadius": 4, "fill": False,
                             "spanGaps": True})
        charts.append({"id": "chart-rpe", "config": json.dumps({
            "type": "line",
            "data": {"labels": [r["date"] for r in rpe_data],
                     "datasets": datasets},
            "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
                        "scales": {"y": {"min": 1, "max": 10, "grid": {"color": "rgba(255,255,255,0.03)"},
                                         "title": {"display": True, "text": "RPE (gap = fatigue)"}},
                                   "x": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Race prediction trend (Fitness tab) — VDOT line + Riegel race points
    # Get target race distance for adaptive prediction
    try:
        from fit.goals import get_target_race as _gtr
        _target = _gtr(conn)
        target_km = _target["distance_km"] if _target and _target.get("distance_km") else 42.195
        target_time_str = _target.get("target_time") if _target else None
    except Exception:
        target_km = 42.195
        target_time_str = None

    # Parse target time for annotation
    target_min = None
    if target_time_str:
        _tp = target_time_str.split(":")
        if len(_tp) == 3:
            target_min = int(_tp[0]) * 60 + int(_tp[1]) + int(_tp[2]) / 60
        elif len(_tp) == 2:
            target_min = int(_tp[0]) + int(_tp[1]) / 60

    vo2_monthly = conn.execute("""
        SELECT substr(date, 1, 7) as month, ROUND(AVG(vo2max), 1) as avg_vo2
        FROM activities WHERE vo2max IS NOT NULL
        GROUP BY month ORDER BY month
    """).fetchall()

    # Riegel predictions from actual races (scatter points)
    race_points = conn.execute("""
        SELECT date, name, distance_km, result_time FROM race_calendar
        WHERE status = 'completed' AND result_time IS NOT NULL AND distance_km IS NOT NULL
        ORDER BY date
    """).fetchall()

    def _parse_t(t):
        p = t.split(":")
        if len(p) == 3:
            return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
        return int(p[0]) * 60 + int(p[1]) if len(p) == 2 else 0

    datasets = []
    all_labels = set()

    # Dataset 1: VDOT line (monthly VO2max → predicted time)
    if len(vo2_monthly) >= 3:
        from fit.analysis import _vdot_to_marathon_seconds
        vdot_labels = []
        vdot_times = []
        for v in vo2_monthly:
            secs = _vdot_to_marathon_seconds(v["avg_vo2"])
            # Scale to target distance if not marathon
            if target_km != 42.195:
                secs = secs * (target_km / 42.195) ** 1.06
            vdot_times.append(round(secs / 60, 1))
            vdot_labels.append(v["month"])
            all_labels.add(v["month"])
        datasets.append({
            "label": "VDOT (from VO2max)", "data": vdot_times,
            "borderColor": ACCENT, "backgroundColor": ACCENT + "15", "fill": True,
            "borderWidth": 2, "pointRadius": 2,
        })

    # Dataset 2: Riegel scatter (actual race → extrapolated to target distance)
    if race_points:
        riegel_labels = []
        riegel_times = []
        for r in race_points:
            d1 = r["distance_km"]
            t1 = _parse_t(r["result_time"])
            if d1 > 0 and t1 > 0 and d1 != target_km:
                t2 = t1 * (target_km / d1) ** 1.06
                riegel_times.append(round(t2 / 60, 1))
                riegel_labels.append(r["date"][:7])  # month
                all_labels.add(r["date"][:7])
        if riegel_times:
            datasets.append({
                "label": "Riegel (from races)", "data": riegel_times,
                "borderColor": Z3, "borderWidth": 0,
                "pointRadius": 5, "pointBackgroundColor": Z3,
                "pointBorderColor": Z3 + "80", "pointBorderWidth": 2,
                "showLine": False, "fill": False,
            })

    if datasets:
        sorted_labels = sorted(all_labels)
        # Align datasets to common label axis
        for ds in datasets:
            old_data = ds["data"]
            if ds.get("showLine") is False:
                # Scatter: use sparse data (null for missing months)
                ds_labels = [r["date"][:7] for r in race_points] if "Riegel" in ds["label"] else []
                aligned = []
                idx = 0
                for lbl in sorted_labels:
                    if idx < len(ds_labels) and ds_labels[idx] == lbl:
                        aligned.append(old_data[idx])
                        idx += 1
                    else:
                        aligned.append(None)
                ds["data"] = aligned
            else:
                # Line: also align
                ds_labels = [v["month"] for v in vo2_monthly] if "VDOT" in ds["label"] else []
                aligned = []
                idx = 0
                for lbl in sorted_labels:
                    if idx < len(ds_labels) and ds_labels[idx] == lbl:
                        aligned.append(old_data[idx])
                        idx += 1
                    else:
                        aligned.append(None)
                ds["data"] = aligned
                ds["spanGaps"] = True

        # Target annotation
        pred_annots = {}
        if target_min:
            pred_annots["target"] = {
                "type": "line", "yMin": target_min, "yMax": target_min,
                "borderColor": SAFE + "60", "borderDash": [6, 3],
                "label": {"content": f"Target {target_time_str}", "display": True,
                           "position": "end", "font": {"size": 8}},
            }

        charts.append({"id": "chart-marathon-pred", "config": json.dumps({
            "type": "line",
            "data": {"labels": sorted_labels, "datasets": datasets},
            "options": {"responsive": True,
                        "plugins": {"legend": {"display": True, "position": "bottom", "labels": {"boxWidth": 12}},
                                    "annotation": {"annotations": pred_annots}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"reverse": True, "grid": {"color": "rgba(255,255,255,0.03)"},
                                         "title": {"display": True, "text": "time (lower = faster)"}}}}
        })})

    # Plan adherence mirrored bar chart (Training tab)
    try:
        from fit.plan import compute_plan_adherence
        adherence = compute_plan_adherence(conn)
        if adherence and (adherence.get("planned") or adherence.get("actuals")):
            # Build per-day data from planned + matches + missed + unplanned
            day_data = {}
            for p in adherence.get("planned", []):
                d = p.get("date", "")
                day_data.setdefault(d, {"planned_km": 0, "actual_km": 0, "status": "missed", "label": ""})
                day_data[d]["planned_km"] = p.get("target_distance_km") or 0
                day_data[d]["label"] = p.get("workout_type", "")
            for m in adherence.get("matches", []):
                d = m.get("planned", {}).get("date", "")
                if d in day_data and m.get("actual"):
                    day_data[d]["actual_km"] = m["actual"].get("distance_km") or 0
                    day_data[d]["status"] = "matched"
            for u in adherence.get("unplanned", []):
                d = u.get("date", "")
                day_data.setdefault(d, {"planned_km": 0, "actual_km": 0, "status": "unplanned"})
                day_data[d]["actual_km"] = u.get("distance_km") or 0
                day_data[d]["status"] = "unplanned"

            if day_data:
                sorted_days = sorted(day_data.items())
                planned_vals = [-(v["planned_km"]) for _, v in sorted_days]
                actual_vals = [v["actual_km"] for _, v in sorted_days]
                colors = []
                for _, v in sorted_days:
                    if v["status"] == "matched":
                        colors.append(SAFE + "80")
                    elif v["status"] == "missed":
                        colors.append("#64748b80")
                    elif v["status"] == "unplanned":
                        colors.append(Z12 + "80")
                    else:
                        colors.append(Z3 + "80")

                # Short labels for readability
                short_labels = []
                for d, v in sorted_days:
                    day = d[5:]  # "04-07"
                    wtype = v.get("label", "")
                    short_labels.append(f"{day} ({wtype})" if wtype else day)

                charts.append({"id": "chart-plan-adherence", "config": json.dumps({
                    "type": "bar",
                    "data": {"labels": short_labels,
                             "datasets": [
                                 {"label": "Planned", "data": [abs(v) for v in planned_vals],
                                  "backgroundColor": ACCENT + "40", "borderColor": ACCENT + "60", "borderWidth": 1},
                                 {"label": "Actual", "data": actual_vals,
                                  "backgroundColor": colors,
                                  "borderColor": [c.replace("80", "cc") for c in colors], "borderWidth": 1},
                             ]},
                    "options": {"responsive": True,
                                "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
                                "scales": {"y": {"grid": {"color": "rgba(255,255,255,0.03)"},
                                                 "title": {"display": True, "text": "km"}},
                                           "x": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
                })})
    except Exception:
        pass

    return charts


# ── Definitions ──

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


# ── Race Prediction ──

def _race_prediction(conn):
    """Generate race prediction table — adapts to target race distance."""
    races = conn.execute("""
        SELECT rc.date, rc.name, rc.distance, rc.distance_km, rc.result_time
        FROM race_calendar rc
        WHERE rc.status = 'completed' AND rc.result_time IS NOT NULL
        ORDER BY rc.date DESC LIMIT 8
    """).fetchall()
    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    if not races and not vo2:
        return None

    # Get target race and its distance
    from fit.goals import get_target_race
    target_race = get_target_race(conn)
    target_km = target_race["distance_km"] if target_race and target_race.get("distance_km") else 42.195
    target_label = target_race["distance"] if target_race else "Marathon"

    # Get target time
    target_str = target_race.get("target_time") if target_race else None
    if not target_str:
        target_goal = conn.execute("SELECT target_time FROM goals WHERE type = 'marathon' AND active = 1 LIMIT 1").fetchone()
        target_str = target_goal["target_time"] if target_goal and target_goal["target_time"] else "4:00:00"

    def _parse_time_to_seconds(t):
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0

    target_secs = _parse_time_to_seconds(target_str)

    # Riegel predictions extrapolated to TARGET distance (not always 42.195)
    race_data = []
    for r in races:
        if r["distance_km"] and r["result_time"]:
            d1 = r["distance_km"]
            t1 = _parse_time_to_seconds(r["result_time"])
            if d1 > 0 and t1 > 0 and d1 != target_km:
                t2 = t1 * (target_km / d1) ** 1.06
                race_data.append({
                    "from_race": r["name"], "from_date": r["date"],
                    "distance_km": d1, "predicted_seconds": round(t2),
                })

    # VDOT prediction
    from fit.analysis import _vdot_to_marathon_seconds
    vdot_pred = None
    if vo2 and vo2["vo2max"] and vo2["vo2max"] > 30:
        marathon_secs = _vdot_to_marathon_seconds(vo2["vo2max"])
        # Scale from marathon to target distance
        vdot_secs = round(marathon_secs * (target_km / 42.195) ** 1.06) if target_km != 42.195 else round(marathon_secs)
        vdot_pred = {"vo2max": vo2["vo2max"], "predicted_seconds": vdot_secs}

    def _fmt_time(secs):
        h = secs // 3600
        m = (secs % 3600) // 60
        if h > 0:
            return f"{h}:{m:02d}"
        return f"{m} min"

    def _fmt_pace(secs):
        pace = secs / target_km
        return f"{int(pace // 60)}:{int(pace % 60):02d}/km"

    parts = []
    parts.append(f"<div style='text-align:center;margin-bottom:10px'>"
                 f"<div style='font-size:9px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.1em'>{target_label} Target</div>"
                 f"<div style='font-size:28px;font-weight:700;color:var(--accent);font-family:var(--mono)'>{target_str}</div>"
                 f"</div>")

    # Build prediction rows
    rows = []
    for r in race_data:
        t = r["predicted_seconds"]
        dist = r.get("distance_km") or 0
        if dist > 18:
            short = "Half Marathon"
        elif dist > 8:
            short = "10K"
        elif dist > 3:
            short = "5K"
        else:
            short = (r.get("from_race") or "")[:20]
        race_date = (r.get("from_date") or "")[:7]
        delta = t - target_secs
        delta_str = f"{'−' if delta < 0 else '+'}{abs(delta) // 60} min" if abs(delta) > 30 else "= target"
        color = "var(--safe)" if delta < 0 else "var(--caution)" if delta < 300 else "var(--danger)"
        rows.append(f"<tr><td style='color:var(--text-muted);font-size:10px'>{short}<br>{race_date}</td>"
                    f"<td style='font-family:var(--mono);font-size:16px;font-weight:600'>{_fmt_time(t)}</td>"
                    f"<td style='font-size:10px;color:var(--text-dim)'>{_fmt_pace(t)}</td>"
                    f"<td style='font-size:10px;color:{color};font-weight:600'>{delta_str}</td></tr>")

    if vdot_pred:
        t = vdot_pred["predicted_seconds"]
        delta = t - target_secs
        delta_str = f"{'−' if delta < 0 else '+'}{abs(delta) // 60} min" if abs(delta) > 30 else "= target"
        color = "var(--safe)" if delta < 0 else "var(--caution)" if delta < 300 else "var(--danger)"
        rows.append(f"<tr><td style='color:var(--text-muted);font-size:10px'>VO2max<br>{vdot_pred['vo2max']}</td>"
                    f"<td style='font-family:var(--mono);font-size:16px;font-weight:600'>{_fmt_time(t)}</td>"
                    f"<td style='font-size:10px;color:var(--text-dim)'>{_fmt_pace(t)}</td>"
                    f"<td style='font-size:10px;color:{color};font-weight:600'>{delta_str}</td></tr>")

    if rows:
        parts.append("<table style='width:100%;border-collapse:collapse;margin:8px 0'>"
                     "<thead><tr style='border-bottom:1px solid rgba(255,255,255,0.06)'>"
                     "<th style='text-align:left;font-size:9px;color:var(--text-dim);padding:4px'>Source</th>"
                     "<th style='text-align:left;font-size:9px;color:var(--text-dim);padding:4px'>Time</th>"
                     "<th style='text-align:left;font-size:9px;color:var(--text-dim);padding:4px'>Pace</th>"
                     "<th style='text-align:left;font-size:9px;color:var(--text-dim);padding:4px'>vs Target</th>"
                     "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")

    parts.append("<div style='font-size:10px;color:var(--text-dim);margin-top:6px'>"
                 "Riegel extrapolates from race times. VDOT from Daniels' tables. "
                 "After a training gap, actual fitness is likely 5-10 min slower than peak predictions.</div>")

    return "\n".join(parts)


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
        "critical": {"bg": "rgba(239,68,68,0.06)", "border": "rgba(239,68,68,0.15)", "color": DANGER, "icon": "🚨"},
        "warning": {"bg": "rgba(249,115,22,0.06)", "border": "rgba(249,115,22,0.15)", "color": Z45, "icon": "⚠️"},
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


# ── Event Annotations (W5) ──

def _get_event_annotations(conn) -> dict:
    """Build Chart.js annotation config for key events."""
    annotations = {}

    # Races — minimal labels, just markers
    try:
        races = conn.execute("SELECT date, distance FROM race_calendar WHERE activity_id IS NOT NULL ORDER BY date").fetchall()
    except Exception:
        races = conn.execute("SELECT date, name FROM activities WHERE run_type = 'race' ORDER BY date").fetchall()
    for i, r in enumerate(races):
        label = r["distance"] if "distance" in r.keys() else (r["name"][:10] if "name" in r.keys() else "🏁")
        annotations[f"race_{i}"] = {
            "type": "line", "xMin": r["date"], "xMax": r["date"],
            "borderColor": ACCENT + "50", "borderWidth": 1,
            "label": {"content": label, "display": True, "position": "start",
                      "font": {"size": 7}, "color": ACCENT + "80"},
        }

    # Calibration changes
    try:
        cals = conn.execute("SELECT date, metric, value FROM calibration ORDER BY date").fetchall()
        for i, c in enumerate(cals):
            annotations[f"cal_{i}"] = {
                "type": "line", "xMin": c["date"], "xMax": c["date"],
                "borderColor": CAUTION + "30", "borderWidth": 1, "borderDash": [2, 4],
                "label": {"content": f"{c['metric']}", "display": True, "position": "end",
                          "font": {"size": 6}, "color": CAUTION + "50"},
            }
    except Exception:
        pass

    # Goal milestones
    try:
        milestones = conn.execute("""
            SELECT date, description FROM goal_log
            WHERE type IN ('milestone_achieved', 'goal_completed', 'phase_completed')
            ORDER BY date
        """).fetchall()
        for i, m in enumerate(milestones):
            annotations[f"mile_{i}"] = {
                "type": "line", "xMin": m["date"], "xMax": m["date"],
                "borderColor": SAFE + "40", "borderWidth": 1,
                "label": {"content": "🎯", "display": True, "position": "start",
                          "font": {"size": 8}, "color": SAFE + "60"},
            }
    except Exception:
        pass

    # Training gaps only (> 14 days — skip short gaps to reduce clutter)
    dates = conn.execute("SELECT DISTINCT date FROM activities ORDER BY date").fetchall()
    date_list = [d["date"] for d in dates]
    for i in range(1, len(date_list)):
        d1 = date.fromisoformat(date_list[i - 1])
        d2 = date.fromisoformat(date_list[i])
        gap_days = (d2 - d1).days
        if gap_days > 14:
            annotations[f"gap_{i}"] = {
                "type": "box", "xMin": date_list[i - 1], "xMax": date_list[i],
                "backgroundColor": "rgba(239,68,68,0.03)", "borderWidth": 0,
                "label": {"content": f"{gap_days}d", "display": True, "position": "center",
                          "font": {"size": 7}, "color": DANGER + "60"},
            }

    return annotations


# ── Phase Compliance (W8) ──

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
            WHERE a.type IN ('running', 'track_running', 'trail_running') AND a.splits_status = 'parsed'
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
    return f"{h}d · {a} activities · {c} check-ins"
