"""Dashboard HTML generator — queries DB, builds Chart.js configs, renders Jinja2."""

import json
import logging
import sqlite3
from datetime import date, datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from fit.report.headline import generate_headline

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
CHARTJS_PATH = Path(__file__).parent / "chartjs.min.js"
ANNOTATION_PATH = Path(__file__).parent / "chartjs-annotation.min.js"

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

    context = {
        "title": "fit — Dashboard",
        "subtitle": _subtitle(conn),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "chartjs_code": chartjs_code,
        "annotation_code": annotation_code,
        "tabs": [
            {"id": "today", "label": "Today"},
            {"id": "training", "label": "Training"},
            {"id": "body", "label": "Body"},
            {"id": "fitness", "label": "Fitness"},
            {"id": "coach", "label": "Coach"},
        ],
        "headline": _headline(conn),
        "status_cards": _status_cards(conn),
        "checkin": _checkin(conn),
        "journey": _journey(conn),
        "wow": _week_over_week(conn),
        "run_timeline": _run_timeline(conn),
        "charts": _all_charts(conn),
        "definitions": _definitions(conn),
        "race_prediction": _race_prediction(conn),
        "coaching": _coaching(conn),
        "phase_compliance": _phase_compliance(conn),
        "calibration_panel": _calibration_panel(conn),
        "data_health": _data_health_panel(conn),
        "sleep_mismatches": _sleep_mismatches(conn),
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
    last_ci = conn.execute("SELECT MAX(date) FROM checkins").fetchone()[0]
    return generate_headline(
        readiness=latest["training_readiness"] if latest else None,
        acwr=acwr_row["acwr"] if acwr_row else None,
        phase=dict(phase) if phase else None,
        last_checkin_date=last_ci,
        today=date.today().isoformat(),
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
        good = (d < 0) if invert else (d > 0)
        return f"{arrow}{abs(d):.0f}" if not invert else f"{arrow}{abs(d):.0f}"

    r = h["training_readiness"]
    cards.append({"label": "Readiness", "value": r or "—", "unit": "",
                  "color": SAFE if r and r >= 75 else CAUTION if r and r >= 50 else DANGER,
                  "sub": delta(r, h4["training_readiness"] if h4 else None) + " 4wk" if h4 else ""})

    rhr = h["resting_heart_rate"]
    cards.append({"label": "RHR", "value": rhr or "—", "unit": "bpm",
                  "color": SAFE if rhr and rhr <= 58 else CAUTION,
                  "sub": delta(rhr, h4["resting_heart_rate"] if h4 else None, invert=True) + " 4wk" if h4 else ""})

    cards.append({"label": "Sleep", "value": f"{h['sleep_duration_hours']:.1f}" if h["sleep_duration_hours"] else "—",
                  "unit": "h", "color": SAFE, "sub": f"D{h['deep_sleep_hours']:.1f}" if h["deep_sleep_hours"] else ""})

    hrv = h["hrv_last_night"]
    cards.append({"label": "HRV", "value": hrv or "—", "unit": "ms", "color": ACCENT,
                  "sub": delta(hrv, h4["hrv_last_night"] if h4 else None) + " 4wk" if h4 else ""})

    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    cards.append({"label": "VO2max", "value": vo2["vo2max"] if vo2 else "—", "unit": "", "color": ACCENT, "sub": ""})

    w = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
    cards.append({"label": "Weight", "value": f"{w['weight_kg']:.1f}" if w else "—", "unit": "kg", "color": CAUTION, "sub": ""})

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
        seg = {"label": p["name"][:12], "width": 1, "color": colors.get(p["status"], colors["planned"])}
        segments.append(seg)
        if p["status"] == "active":
            position = f"You are here — {p['phase']}: {p['name']}"

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

    # Volume (Training tab)
    weeks = conn.execute("SELECT week, run_km, longest_run_km FROM weekly_agg WHERE run_km > 0 ORDER BY week").fetchall()
    if weeks:
        charts.append({"id": "chart-volume", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [w["week"] for w in weeks],
                     "datasets": [{"label": "km/week", "data": [w["run_km"] for w in weeks],
                                   "backgroundColor": "rgba(56,189,248,0.5)", "borderRadius": 4}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Load (Training tab)
    runs = conn.execute("SELECT date, training_load FROM activities WHERE type='running' AND training_load IS NOT NULL ORDER BY date").fetchall()
    if runs:
        colors = [Z12 + "99" if (r["training_load"] or 0) < 150 else Z3 + "99" if r["training_load"] < 250 else Z45 + "99" if r["training_load"] < 350 else DANGER + "99" for r in runs]
        charts.append({"id": "chart-load", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [r["date"] for r in runs],
                     "datasets": [{"label": "Load", "data": [r["training_load"] for r in runs],
                                   "backgroundColor": colors, "borderRadius": 3}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Readiness + RHR + HRV (Body tab)
    health = conn.execute("SELECT date, training_readiness, resting_heart_rate, hrv_last_night FROM daily_health WHERE date >= date('now','-21 days') ORDER BY date").fetchall()
    if health:
        r_colors = [SAFE + "80" if (h["training_readiness"] or 0) >= 75 else CAUTION + "80" if (h["training_readiness"] or 0) >= 50 else DANGER + "80" for h in health]
        charts.append({"id": "chart-readiness", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [h["date"] for h in health],
                     "datasets": [
                         {"label": "Readiness", "data": [h["training_readiness"] for h in health], "backgroundColor": r_colors, "borderRadius": 3, "yAxisID": "y", "order": 2},
                         {"label": "RHR", "data": [h["resting_heart_rate"] for h in health], "type": "line", "borderColor": DANGER, "borderWidth": 2, "pointRadius": 2.5, "yAxisID": "y1", "order": 1},
                         {"label": "HRV", "data": [h["hrv_last_night"] for h in health], "type": "line", "borderColor": ACCENT, "borderWidth": 1.5, "borderDash": [4, 2], "pointRadius": 2, "yAxisID": "y", "order": 1},
                     ]},
            "options": {"responsive": True, "scales": {
                "y": {"position": "left", "min": 0, "max": 100, "grid": {"color": "rgba(255,255,255,0.03)"}},
                "y1": {"position": "right", "min": 45, "max": 75, "grid": {"drawOnChartArea": False}},
                "x": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Sleep (Body tab)
    sleep = conn.execute("SELECT date, deep_sleep_hours, rem_sleep_hours, light_sleep_hours FROM daily_health WHERE date >= date('now','-21 days') ORDER BY date").fetchall()
    if sleep:
        charts.append({"id": "chart-sleep", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [s["date"] for s in sleep],
                     "datasets": [
                         {"label": "Deep", "data": [s["deep_sleep_hours"] for s in sleep], "backgroundColor": "#1e3a5f", "stack": "s"},
                         {"label": "REM", "data": [s["rem_sleep_hours"] for s in sleep], "backgroundColor": "#6366f1", "stack": "s"},
                         {"label": "Light", "data": [s["light_sleep_hours"] for s in sleep], "backgroundColor": "#1e293b", "stack": "s"},
                     ]},
            "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
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

    # Weight (Body tab)
    weight = conn.execute("SELECT date, weight_kg FROM body_comp ORDER BY date").fetchall()
    if weight:
        charts.append({"id": "chart-weight", "config": json.dumps({
            "type": "line",
            "data": {"labels": [w["date"] for w in weight],
                     "datasets": [{"label": "Weight", "data": [w["weight_kg"] for w in weight],
                                   "borderColor": Z3, "backgroundColor": Z3 + "15", "fill": True, "borderWidth": 2, "pointRadius": 3}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Get event annotations for time-series charts (W5)
    event_annots = _get_event_annotations(conn)

    # Speed per BPM (Fitness tab — hero chart)
    eff = conn.execute("SELECT date, speed_per_bpm, speed_per_bpm_z2 FROM activities WHERE type='running' AND speed_per_bpm IS NOT NULL AND date >= date('now','-90 days') ORDER BY date").fetchall()
    if eff:
        charts.append({"id": "chart-efficiency", "config": json.dumps({
            "type": "line",
            "data": {"labels": [e["date"] for e in eff],
                     "datasets": [
                         {"label": "All runs", "data": [e["speed_per_bpm"] for e in eff], "borderColor": Z3 + "80", "borderWidth": 1.5, "pointRadius": 2, "fill": False},
                         {"label": "Z2 only", "data": [e["speed_per_bpm_z2"] for e in eff], "borderColor": ACCENT, "borderWidth": 2.5, "pointRadius": 4, "fill": False},
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

    # Zone distribution (Fitness tab)
    zone_weeks = conn.execute("SELECT week, z1_min, z2_min, z3_min, z4_min, z5_min FROM weekly_agg WHERE (z1_min+z2_min+z3_min+z4_min+z5_min) > 0 ORDER BY week DESC LIMIT 8").fetchall()
    if zone_weeks:
        zone_weeks = list(reversed(zone_weeks))
        charts.append({"id": "chart-zones", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [w["week"] for w in zone_weeks],
                     "datasets": [
                         {"label": "Z1+Z2", "data": [(w["z1_min"] or 0) + (w["z2_min"] or 0) for w in zone_weeks], "backgroundColor": Z12 + "80", "stack": "s"},
                         {"label": "Z3", "data": [w["z3_min"] or 0 for w in zone_weeks], "backgroundColor": Z3 + "80", "stack": "s"},
                         {"label": "Z4+Z5", "data": [(w["z4_min"] or 0) + (w["z5_min"] or 0) for w in zone_weeks], "backgroundColor": Z45 + "80", "stack": "s"},
                     ]},
            "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
                        "scales": {"x": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}, "title": {"display": True, "text": "minutes"}}}}
        })})

    # ACWR trend (Body tab)
    acwr_data = conn.execute("""
        SELECT week, acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week
    """).fetchall()
    if acwr_data:
        acwr_colors = [SAFE if 0.8 <= (a["acwr"] or 0) <= 1.3 else CAUTION if (a["acwr"] or 0) <= 1.5 else DANGER for a in acwr_data]
        charts.append({"id": "chart-acwr", "config": json.dumps({
            "type": "bar",
            "data": {"labels": [a["week"] for a in acwr_data],
                     "datasets": [{"label": "ACWR", "data": [a["acwr"] for a in acwr_data],
                                   "backgroundColor": acwr_colors, "borderRadius": 3}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                        "annotation": {"annotations": {
                            "safe_lo": {"type": "line", "yMin": 0.8, "yMax": 0.8, "borderColor": SAFE + "40", "borderDash": [4, 3],
                                        "label": {"content": "0.8", "display": True, "position": "start", "font": {"size": 8}}},
                            "safe_hi": {"type": "line", "yMin": 1.3, "yMax": 1.3, "borderColor": SAFE + "40", "borderDash": [4, 3],
                                        "label": {"content": "1.3 safe", "display": True, "position": "end", "font": {"size": 8}}},
                            "danger": {"type": "line", "yMin": 1.5, "yMax": 1.5, "borderColor": DANGER + "60", "borderDash": [6, 3],
                                       "label": {"content": "1.5 danger", "display": True, "position": "end", "font": {"size": 8}}},
                        }}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"min": 0, "max": 2.5, "grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Cadence trend (Fitness tab — W3)
    cadence = conn.execute("""
        SELECT date, avg_cadence FROM activities
        WHERE type='running' AND avg_cadence IS NOT NULL AND date >= date('now','-90 days')
        ORDER BY date
    """).fetchall()
    if cadence:
        charts.append({"id": "chart-cadence", "config": json.dumps({
            "type": "line",
            "data": {"labels": [c["date"] for c in cadence],
                     "datasets": [{"label": "Cadence (spm)", "data": [c["avg_cadence"] for c in cadence],
                                   "borderColor": Z12, "borderWidth": 2, "pointRadius": 3, "fill": False}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                        "annotation": {"annotations": {"threshold": {"type": "line", "yMin": 165, "yMax": 165,
                                       "borderColor": CAUTION + "60", "borderDash": [6, 3],
                                       "label": {"content": "Low threshold 165", "display": True, "position": "end", "font": {"size": 8}}}}}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # RPE predicted vs actual (Fitness tab — W4)
    rpe_data = conn.execute("""
        SELECT a.date, a.rpe as actual_rpe, a.hr_zone,
               CASE a.hr_zone
                   WHEN 'Z1' THEN 2 WHEN 'Z2' THEN 3 WHEN 'Z3' THEN 5
                   WHEN 'Z4' THEN 7 WHEN 'Z5' THEN 9 ELSE NULL
               END as predicted_rpe
        FROM activities a
        WHERE a.type='running' AND a.rpe IS NOT NULL AND a.hr_zone IS NOT NULL
        ORDER BY a.date
    """).fetchall()
    if len(rpe_data) >= 3:
        charts.append({"id": "chart-rpe", "config": json.dumps({
            "type": "line",
            "data": {"labels": [r["date"] for r in rpe_data],
                     "datasets": [
                         {"label": "Predicted (from HR)", "data": [r["predicted_rpe"] for r in rpe_data],
                          "borderColor": Z12, "borderWidth": 1.5, "borderDash": [4, 2], "pointRadius": 2, "fill": False},
                         {"label": "Actual RPE", "data": [r["actual_rpe"] for r in rpe_data],
                          "borderColor": Z45, "borderWidth": 2, "pointRadius": 4, "fill": False},
                     ]},
            "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
                        "scales": {"y": {"min": 1, "max": 10, "grid": {"color": "rgba(255,255,255,0.03)"},
                                         "title": {"display": True, "text": "RPE (gap = fatigue)"}},
                                   "x": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    return charts


# ── Definitions ──

def _definitions(conn):
    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    vo2_val = vo2["vo2max"] if vo2 else "?"
    acwr_row = conn.execute("SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
    acwr_val = f"{acwr_row['acwr']:.2f}" if acwr_row else "?"
    weight_row = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
    weight_val = f"{weight_row['weight_kg']:.1f}" if weight_row else "?"
    return {
        "speed_per_bpm": f"Speed per heartbeat: (meters/min) ÷ avg HR. Higher = more efficient. The Z2-filtered line (bold) shows pure aerobic fitness at controlled effort — the most honest fitness signal.",
        "vo2max": f"Maximum oxygen uptake (ml/kg/min). Current: {vo2_val}. For sub-4:00 marathon at ~75kg, you need ≥50. Declines ~3-5% per month of inactivity, recovers ~1/month with consistent training.",
        "training_load": "Garmin's EPOC-based measure of physiological stress per session. <strong style='color:var(--z12)'>< 150 = easy</strong>, <strong style='color:var(--z3)'>150-250 = moderate</strong>, <strong style='color:var(--z45)'>250-350 = hard</strong>, <strong style='color:var(--danger)'>> 350 = overload risk</strong>. A typical well-trained week sums to 400-800 across all sessions.",
        "readiness": "Garmin's composite 0-100 score combining sleep quality, recovery time, HRV status, stress, and recent training load. <strong style='color:var(--safe)'>≥75 = ready for quality sessions</strong>, <strong style='color:var(--caution)'>50-74 = easy day</strong>, <strong style='color:var(--danger)'>< 50 = rest</strong>.",
        "sleep": "Deep sleep: physical recovery + muscle repair. REM: cognitive recovery + motor consolidation. For runners: ≥1h deep + ≥1.5h REM is good. Total ≥7.5h supports adaptation. Post-hard-effort, deep sleep often collapses — a key recovery signal.",
        "stress_battery": "Body Battery: Garmin's energy reserve (0-100), charged by rest, drained by activity and stress. Stress: 0-100, from HRV analysis. When stress rises and battery drops simultaneously, your body is under load.",
        "weight": f"Current: {weight_val} kg. Each kg lost saves ~2-3 sec/km at the same effort. Over 42.2 km, 3 kg = ~7-10 min faster. Target weight through training volume (not dieting).",
        "zones": "HR zones by training TIME (minutes per week), not run count. Compared to your active training phase targets. Blue = Z1+Z2 (easy), amber = Z3 (moderate), orange = Z4+Z5 (hard). Phase 1 targets ~90% easy.",
        "volume": "Total running km per week. The darker segment shows the longest single run. For marathon training: long run should build gradually to 30-32 km, weekly volume to 50-60 km at peak.",
        "cadence": "Running cadence (steps per minute). Below 165 often indicates overstriding, which increases braking forces and injury risk. Target: 170-180 for most recreational runners. Tends to improve with fatigue resilience and form work.",
        "rpe": "Predicted RPE from HR zone (Z2→3, Z4→7) vs actual RPE from check-in. A widening gap where actual exceeds predicted signals accumulating fatigue — your body is working harder than your heart rate suggests.",
        "race_prediction": "Riegel formula: extrapolates from shorter race times using T2 = T1 × (D2/D1)^1.06. VDOT: from Daniels' tables using VO2max. Both are estimates — actual performance depends on training specificity, fueling, and conditions.",
        "acwr": f"Acute:Chronic Workload Ratio. Current: {acwr_val}. This week's load ÷ avg of previous 4 weeks. <strong style='color:var(--safe)'>0.8-1.3 = safe</strong>, <strong style='color:var(--caution)'>1.3-1.5 = caution</strong>, <strong style='color:var(--danger)'>> 1.5 = injury risk (spike)</strong>, < 0.6 = detraining. Critical for comeback training.",
    }


# ── Race Prediction ──

def _race_prediction(conn):
    races = conn.execute("SELECT date, name, distance_km, duration_min FROM activities WHERE run_type = 'race' ORDER BY date DESC LIMIT 3").fetchall()
    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    if not races and not vo2:
        return None

    from fit.analysis import predict_marathon_time
    race_data = [{"distance_km": r["distance_km"], "time_seconds": (r["duration_min"] or 0) * 60,
                  "name": r["name"], "date": r["date"]} for r in races if r["distance_km"] and r["duration_min"]]
    preds = predict_marathon_time(race_data, vo2max=vo2["vo2max"] if vo2 else None)

    parts = []
    for r in preds.get("riegel", []):
        t = r["predicted_seconds"]
        parts.append(f"<div><strong>Riegel ({r['from_race']}):</strong> {t // 3600}:{(t % 3600) // 60:02d} ({r['predicted_pace_sec_km'] // 60}:{r['predicted_pace_sec_km'] % 60:02d}/km)</div>")
    if preds.get("vdot"):
        t = preds["vdot"]["predicted_seconds"]
        parts.append(f"<div><strong>VDOT (VO2max {preds['vdot']['vo2max']}):</strong> {t // 3600}:{(t % 3600) // 60:02d}</div>")
    return "\n".join(parts) if parts else None


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


# ── Event Annotations (W5) ──

def _get_event_annotations(conn) -> dict:
    """Build Chart.js annotation config for key events."""
    annotations = {}

    # Races
    races = conn.execute("SELECT date, name FROM activities WHERE run_type = 'race' ORDER BY date").fetchall()
    for i, r in enumerate(races):
        annotations[f"race_{i}"] = {
            "type": "line", "xMin": r["date"], "xMax": r["date"],
            "borderColor": ACCENT + "80", "borderWidth": 1, "borderDash": [3, 3],
            "label": {"content": r["name"] or "Race", "display": True, "position": "start",
                      "font": {"size": 8}, "color": ACCENT},
        }

    # Phase transitions
    phases = conn.execute("SELECT start_date, name FROM training_phases WHERE status != 'revised' AND start_date IS NOT NULL ORDER BY start_date").fetchall()
    for i, p in enumerate(phases):
        annotations[f"phase_{i}"] = {
            "type": "line", "xMin": p["start_date"], "xMax": p["start_date"],
            "borderColor": SAFE + "60", "borderWidth": 1, "borderDash": [6, 3],
            "label": {"content": p["name"] or "", "display": True, "position": "start",
                      "font": {"size": 7}, "color": SAFE + "AA"},
        }

    # Training gaps (> 7 days without activity)
    dates = conn.execute("SELECT DISTINCT date FROM activities ORDER BY date").fetchall()
    date_list = [d["date"] for d in dates]
    for i in range(1, len(date_list)):
        d1 = date.fromisoformat(date_list[i - 1])
        d2 = date.fromisoformat(date_list[i])
        gap_days = (d2 - d1).days
        if gap_days > 7:
            mid = d1 + (d2 - d1) / 2
            annotations[f"gap_{i}"] = {
                "type": "box", "xMin": date_list[i - 1], "xMax": date_list[i],
                "backgroundColor": "rgba(239,68,68,0.05)", "borderWidth": 0,
                "label": {"content": f"{gap_days}d gap", "display": True, "position": "center",
                          "font": {"size": 8}, "color": DANGER + "80"},
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


# ── Helpers ──

def _subtitle(conn):
    h = conn.execute("SELECT COUNT(*) FROM daily_health").fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
    return f"{h}d · {a} activities · {c} check-ins"
