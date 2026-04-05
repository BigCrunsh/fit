"""Dashboard HTML generator — queries DB, builds Chart.js configs, renders Jinja2 template."""

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path(__file__).parent / "templates"
CHARTJS_PATH = Path(__file__).parent / "chartjs.min.js"

# Color constants (matching CSS vars)
SAFE = "#22c55e"
CAUTION = "#eab308"
DANGER = "#ef4444"
Z12_COLOR = "#38bdf8"
Z3_COLOR = "#f59e0b"
Z45_COLOR = "#f97316"
ACCENT = "#818cf8"


def generate_dashboard(conn: sqlite3.Connection, output_path: Path) -> None:
    """Generate the dashboard HTML file."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("dashboard.html")

    chartjs_code = CHARTJS_PATH.read_text() if CHARTJS_PATH.exists() else "// Chart.js not found"

    context = {
        "title": "fit — Dashboard",
        "subtitle": _build_subtitle(conn),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "chartjs_code": chartjs_code,
        "tabs": [
            {"id": "training", "label": "Training"},
            {"id": "body", "label": "Body"},
            {"id": "coach", "label": "Coach"},
        ],
        "status_cards": _build_status_cards(conn),
        "checkin": _build_checkin(conn),
        "run_log": _build_run_log(conn),
        "charts": _build_charts(conn),
        "coaching": _build_coaching(conn),
    }

    html = template.render(**context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html)
    logger.info("Dashboard written to %s (%d bytes)", output_path, len(html))


def _build_subtitle(conn: sqlite3.Connection) -> str:
    health = conn.execute("SELECT COUNT(*) FROM daily_health").fetchone()[0]
    activities = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    checkins = conn.execute("SELECT COUNT(*) FROM checkins").fetchone()[0]
    return f"{health}d · {activities} activities · {checkins} check-ins"


def _build_status_cards(conn: sqlite3.Connection) -> list[dict]:
    cards = []
    latest = conn.execute("SELECT * FROM daily_health ORDER BY date DESC LIMIT 1").fetchone()
    if not latest:
        return cards

    # Readiness
    r = latest["training_readiness"]
    color = SAFE if r and r >= 75 else CAUTION if r and r >= 50 else DANGER
    cards.append({"label": "Readiness", "value": r or "—", "unit": "", "color": color, "sub": ""})

    # RHR
    cards.append({"label": "RHR", "value": latest["resting_heart_rate"] or "—", "unit": "bpm",
                  "color": SAFE if latest["resting_heart_rate"] and latest["resting_heart_rate"] <= 58 else CAUTION, "sub": ""})

    # Sleep
    cards.append({"label": "Sleep", "value": f"{latest['sleep_duration_hours']:.1f}" if latest["sleep_duration_hours"] else "—",
                  "unit": "h", "color": SAFE, "sub": f"D{latest['deep_sleep_hours']:.1f}" if latest["deep_sleep_hours"] else ""})

    # HRV
    cards.append({"label": "HRV", "value": latest["hrv_last_night"] or "—", "unit": "ms",
                  "color": ACCENT, "sub": f"Wk {latest['hrv_weekly_avg']}" if latest["hrv_weekly_avg"] else ""})

    # VO2max
    vo2 = conn.execute("SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1").fetchone()
    cards.append({"label": "VO2max", "value": vo2["vo2max"] if vo2 else "—", "unit": "", "color": ACCENT, "sub": ""})

    # Weight
    weight = conn.execute("SELECT weight_kg FROM body_comp ORDER BY date DESC LIMIT 1").fetchone()
    cards.append({"label": "Weight", "value": f"{weight['weight_kg']:.1f}" if weight else "—",
                  "unit": "kg", "color": CAUTION, "sub": ""})

    # ACWR
    acwr = conn.execute("SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1").fetchone()
    if acwr and acwr["acwr"]:
        v = acwr["acwr"]
        color = SAFE if 0.8 <= v <= 1.3 else CAUTION if v <= 1.5 else DANGER
        cards.append({"label": "ACWR", "value": f"{v:.2f}", "unit": "", "color": color, "sub": "safe" if 0.8 <= v <= 1.3 else "caution"})

    return cards


def _build_checkin(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM checkins ORDER BY date DESC LIMIT 1").fetchone()
    if not row:
        return None
    items = []
    if row["hydration"]:
        items.append(f"💧 {row['hydration']}")
    if row["alcohol"] is not None:
        items.append(f"🍺 {row['alcohol']}")
    if row["legs"]:
        items.append(f"🦵 {row['legs']}")
    if row["notes"]:
        items.append(row["notes"])
    return {"date": row["date"], "fields": items}


def _build_run_log(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute("""
        SELECT date, name, distance_km, pace_sec_per_km, avg_hr, hr_zone,
               run_type, training_load
        FROM activities WHERE type = 'running'
        ORDER BY date DESC LIMIT 10
    """).fetchall()

    result = []
    for r in rows:
        pace = _format_pace(r["pace_sec_per_km"]) if r["pace_sec_per_km"] else "—"
        zone = r["hr_zone"] or "—"
        load = r["training_load"]

        zone_color = Z12_COLOR if zone in ("Z1", "Z2") else Z3_COLOR if zone == "Z3" else Z45_COLOR
        pace_color = SAFE if r["pace_sec_per_km"] and r["pace_sec_per_km"] < 330 else ACCENT
        load_color = SAFE if load and load < 150 else CAUTION if load and load < 250 else Z45_COLOR if load and load < 350 else DANGER

        result.append({
            "date": r["date"], "name": r["name"] or "—",
            "distance": f"{r['distance_km']:.1f}" if r["distance_km"] else "—",
            "pace": pace, "pace_color": pace_color,
            "hr": r["avg_hr"] or "—",
            "zone": zone, "zone_color": zone_color,
            "run_type": r["run_type"] or "—",
            "load": f"{load:.0f}" if load else "—", "load_color": load_color,
        })
    return result


def _build_charts(conn: sqlite3.Connection) -> list[dict]:
    charts = []

    # Weekly volume chart
    weeks = conn.execute("""
        SELECT week, run_km, longest_run_km FROM weekly_agg
        WHERE run_km > 0 ORDER BY week
    """).fetchall()
    if weeks:
        charts.append({
            "id": "chart-volume",
            "config": json.dumps({
                "type": "bar",
                "data": {
                    "labels": [w["week"] for w in weeks],
                    "datasets": [{
                        "label": "km/week",
                        "data": [w["run_km"] for w in weeks],
                        "backgroundColor": "rgba(56,189,248,0.5)",
                        "borderRadius": 4,
                        "barPercentage": 0.7,
                    }]
                },
                "options": {
                    "responsive": True,
                    "plugins": {"legend": {"display": False}},
                    "scales": {
                        "x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                        "y": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                    }
                }
            }),
        })

    # Training load per run
    runs = conn.execute("""
        SELECT date, name, training_load, hr_zone FROM activities
        WHERE type = 'running' AND training_load IS NOT NULL
        ORDER BY date
    """).fetchall()
    if runs:
        colors = []
        for r in runs:
            load = r["training_load"]
            if load < 150:
                colors.append("rgba(56,189,248,0.6)")
            elif load < 250:
                colors.append("rgba(245,158,11,0.6)")
            elif load < 350:
                colors.append("rgba(249,115,22,0.6)")
            else:
                colors.append("rgba(239,68,68,0.6)")
        charts.append({
            "id": "chart-load",
            "config": json.dumps({
                "type": "bar",
                "data": {
                    "labels": [r["date"] for r in runs],
                    "datasets": [{
                        "label": "Load",
                        "data": [r["training_load"] for r in runs],
                        "backgroundColor": colors,
                        "borderRadius": 3,
                        "barPercentage": 0.6,
                    }]
                },
                "options": {
                    "responsive": True,
                    "plugins": {"legend": {"display": False}},
                    "scales": {
                        "x": {"grid": {"color": "rgba(255,255,255,0.03)"}, "ticks": {"maxRotation": 45}},
                        "y": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                    }
                }
            }),
        })

    # Readiness + RHR + HRV (Body tab)
    health = conn.execute("""
        SELECT date, training_readiness, resting_heart_rate, hrv_last_night
        FROM daily_health WHERE date >= date('now', '-21 days')
        ORDER BY date
    """).fetchall()
    if health:
        readiness_colors = []
        for h in health:
            r = h["training_readiness"]
            if r and r >= 75:
                readiness_colors.append("rgba(34,197,94,0.5)")
            elif r and r >= 50:
                readiness_colors.append("rgba(234,179,8,0.5)")
            else:
                readiness_colors.append("rgba(239,68,68,0.5)")

        charts.append({
            "id": "chart-readiness",
            "config": json.dumps({
                "type": "bar",
                "data": {
                    "labels": [h["date"] for h in health],
                    "datasets": [
                        {
                            "label": "Readiness",
                            "data": [h["training_readiness"] for h in health],
                            "backgroundColor": readiness_colors,
                            "borderRadius": 3,
                            "yAxisID": "y",
                            "order": 2,
                        },
                        {
                            "label": "RHR",
                            "data": [h["resting_heart_rate"] for h in health],
                            "type": "line",
                            "borderColor": "#ef4444",
                            "borderWidth": 2,
                            "pointRadius": 2.5,
                            "yAxisID": "y1",
                            "order": 1,
                        },
                        {
                            "label": "HRV",
                            "data": [h["hrv_last_night"] for h in health],
                            "type": "line",
                            "borderColor": "#818cf8",
                            "borderWidth": 1.5,
                            "borderDash": [4, 2],
                            "pointRadius": 2,
                            "yAxisID": "y",
                            "order": 1,
                        },
                    ]
                },
                "options": {
                    "responsive": True,
                    "scales": {
                        "y": {"position": "left", "min": 0, "max": 100, "grid": {"color": "rgba(255,255,255,0.03)"}},
                        "y1": {"position": "right", "min": 45, "max": 75, "grid": {"drawOnChartArea": False}},
                        "x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                    }
                }
            }),
        })

    # Sleep stacked bars (Body tab)
    sleep = conn.execute("""
        SELECT date, deep_sleep_hours, rem_sleep_hours, light_sleep_hours
        FROM daily_health WHERE date >= date('now', '-21 days')
        ORDER BY date
    """).fetchall()
    if sleep:
        charts.append({
            "id": "chart-sleep",
            "config": json.dumps({
                "type": "bar",
                "data": {
                    "labels": [s["date"] for s in sleep],
                    "datasets": [
                        {"label": "Deep", "data": [s["deep_sleep_hours"] for s in sleep],
                         "backgroundColor": "#1e3a5f", "stack": "s"},
                        {"label": "REM", "data": [s["rem_sleep_hours"] for s in sleep],
                         "backgroundColor": "#6366f1", "stack": "s"},
                        {"label": "Light", "data": [s["light_sleep_hours"] for s in sleep],
                         "backgroundColor": "#1e293b", "stack": "s", "borderRadius": {"topLeft": 3, "topRight": 3}},
                    ]
                },
                "options": {
                    "responsive": True,
                    "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 12, "padding": 10}}},
                    "scales": {
                        "x": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}},
                        "y": {"stacked": True, "grid": {"color": "rgba(255,255,255,0.03)"}},
                    }
                }
            }),
        })

    return charts


def _build_coaching(conn: sqlite3.Connection) -> dict | None:
    reports_dir = Path(conn.execute("PRAGMA database_list").fetchone()[2]).parent / "reports"
    coaching_path = reports_dir / "coaching.json"
    if not coaching_path.exists():
        return None

    data = json.loads(coaching_path.read_text())
    generated_at = data.get("generated_at", "unknown")

    # Check staleness
    last_sync = conn.execute("SELECT MAX(date) FROM daily_health").fetchone()[0]
    report_date = data.get("report_date", "")
    stale = report_date < last_sync if last_sync and report_date else False

    type_styles = {
        "critical": {"bg": "rgba(239,68,68,0.06)", "border": "rgba(239,68,68,0.15)", "color": DANGER, "icon": "🚨"},
        "warning": {"bg": "rgba(249,115,22,0.06)", "border": "rgba(249,115,22,0.15)", "color": Z45_COLOR, "icon": "⚠️"},
        "positive": {"bg": "rgba(34,197,94,0.06)", "border": "rgba(34,197,94,0.15)", "color": SAFE, "icon": "✅"},
        "info": {"bg": "rgba(59,130,246,0.06)", "border": "rgba(59,130,246,0.15)", "color": "#3b82f6", "icon": "📊"},
        "target": {"bg": "rgba(167,139,250,0.06)", "border": "rgba(167,139,250,0.15)", "color": ACCENT, "icon": "🎯"},
    }

    insights = []
    for i in data.get("insights", []):
        style = type_styles.get(i.get("type", "info"), type_styles["info"])
        insights.append({**style, "title": i.get("title", ""), "body": i.get("body", "")})

    return {"generated_at": generated_at, "stale": stale, "insights": insights}


def _format_pace(sec_per_km: float) -> str:
    m = int(sec_per_km // 60)
    s = int(sec_per_km % 60)
    return f"{m}:{s:02d}"
