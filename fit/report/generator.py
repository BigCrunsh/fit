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
    if row["hydration"]: fields.append(f"💧 {row['hydration']}")
    if row["alcohol"] is not None: fields.append(f"🍺 {row['alcohol']}")
    if row["legs"]: fields.append(f"🦵 {row['legs']}")
    if row["notes"]: fields.append(row["notes"])
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
            "options": {"responsive": True, "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12}}},
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
                                                         "annotation": {"annotations": {"sub4": {"type": "line", "yMin": 50, "yMax": 50, "borderColor": CAUTION + "60", "borderDash": [6, 3], "label": {"content": "Sub-4 ≥50", "display": True, "position": "end", "font": {"size": 8}}}}}},
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

    return charts


# ── Definitions ──

def _definitions(conn):
    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    vo2_val = vo2["vo2max"] if vo2 else "?"
    return {
        "speed_per_bpm": f"Speed per heartbeat: (meters/min) ÷ avg HR. Higher = more efficient. Your Z2-filtered trend shows pure aerobic fitness. Improving = getting faster at the same effort.",
        "vo2max": f"Maximum oxygen uptake (ml/kg/min). Your current: {vo2_val}. For sub-4:00 marathon at ~75kg, you need ≥50. Declines ~3-5% per month of inactivity, recovers ~1/month with consistent training.",
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


# ── Helpers ──

def _subtitle(conn):
    h = conn.execute("SELECT COUNT(*) FROM daily_health").fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    c = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
    return f"{h}d · {a} activities · {c} check-ins"
