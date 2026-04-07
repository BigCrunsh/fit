"""Chart data generation for all dashboard tabs."""

import json
import logging
from datetime import date

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
        colors = [Z2 + "99" if (r["training_load"] or 0) < 150 else Z3 + "99" if r["training_load"] < 250 else Z4 + "99" if r["training_load"] < 350 else DANGER + "99" for r in runs]
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
        # Insert nulls in gaps >30 days to break the line
        weight_labels = []
        weight_data = []
        bf_raw = []
        prev_date = None
        for w in weight:
            if prev_date:
                gap = (date.fromisoformat(w["date"]) - date.fromisoformat(prev_date)).days
                if gap > 30:
                    # Insert a null point to break the line
                    weight_labels.append("")
                    weight_data.append(None)
                    bf_raw.append(None)
            weight_labels.append(w["date"])
            weight_data.append(w["weight_kg"])
            bf_raw.append(w["body_fat_pct"])
            prev_date = w["date"]

        datasets = [{"label": "Weight", "data": weight_data,
                      "borderColor": Z3, "backgroundColor": Z3 + "15", "fill": True,
                      "borderWidth": 2, "pointRadius": 3, "yAxisID": "y", "spanGaps": False}]
        # Body fat second y-axis if data exists
        bf_data = bf_raw
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
            "data": {"labels": weight_labels, "datasets": datasets},
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
                         {"label": "All runs", "data": [e["speed_per_bpm"] for e in eff], "borderColor": Z3 + "99", "borderWidth": 1.5, "pointRadius": 3, "pointBackgroundColor": Z3 + "80", "fill": False},
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
                         {"label": f"Z1 Recovery{phase_note}", "data": [w["z1_min"] or 0 for w in zone_weeks], "backgroundColor": Z1 + "80", "stack": "s"},
                         {"label": "Z2 Easy", "data": [w["z2_min"] or 0 for w in zone_weeks], "backgroundColor": Z2 + "80", "stack": "s"},
                         {"label": "Z3 Moderate", "data": [w["z3_min"] or 0 for w in zone_weeks], "backgroundColor": Z3 + "80", "stack": "s"},
                         {"label": "Z4 Hard", "data": [w["z4_min"] or 0 for w in zone_weeks], "backgroundColor": Z4 + "80", "stack": "s"},
                         {"label": "Z5 Very Hard", "data": [w["z5_min"] or 0 for w in zone_weeks], "backgroundColor": Z5 + "80", "stack": "s"},
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
        # Merge spike annotations (top 3 only) with safe zone/danger line
        acwr_annots = {
            "safe_zone": {"type": "box", "yMin": 0.8, "yMax": 1.3,
                          "backgroundColor": SAFE + "10", "borderWidth": 0,
                          "label": {"content": "Safe zone 0.8-1.3", "display": True, "position": "end",
                                    "font": {"size": 8}, "color": SAFE + "60"}},
            "danger": {"type": "line", "yMin": 1.5, "yMax": 1.5, "borderColor": DANGER + "60", "borderDash": [6, 3],
                       "label": {"content": "1.5 danger", "display": True, "position": "end", "font": {"size": 8}}},
        }
        acwr_annots.update(_get_acwr_annotations(conn))
        charts.append({"id": "chart-acwr", "config": json.dumps({
            "type": "line",
            "data": {"labels": [a["week"] for a in acwr_data],
                     "datasets": [{"label": "ACWR", "data": [a["acwr"] for a in acwr_data],
                                   "borderColor": ACCENT, "borderWidth": 2, "pointRadius": 4,
                                   "pointBackgroundColor": point_colors, "pointBorderColor": point_colors,
                                   "fill": False}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                        "annotation": {"annotations": acwr_annots}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"min": 0, "max": 3.0, "grid": {"color": "rgba(255,255,255,0.03)"},
                                         "title": {"display": True, "text": "ACWR (capped at 3.0)"}}}}
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
        # Distinct colors: blue family for easy, warm for hard, purple for race
        type_colors = {
            "easy": "#60a5fa",         # bright blue
            "recovery": "#93c5fd80",   # light blue (faded)
            "long": "#34d399",         # emerald green (distinct from easy)
            "tempo": "#fbbf24",        # amber/yellow
            "intervals": "#f97316",    # orange
            "race": "#c084fc",         # purple (clearly different from orange)
        }
        datasets = []
        for t in type_names:
            data = []
            for w in weeks_set:
                count = sum(r["n"] for r in type_weeks if r["week"] == w and r["run_type"] == t)
                data.append(count)
            if any(d > 0 for d in data):
                datasets.append({"label": t, "data": data, "backgroundColor": type_colors.get(t, Z2), "stack": "s"})
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
                                   "borderColor": Z2, "borderWidth": 2, "pointRadius": 3, "fill": False}]},
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
             "borderColor": Z2, "borderWidth": 1.5, "borderDash": [4, 2], "pointRadius": 2, "fill": False},
        ]
        # Add actual RPE line if any check-in RPE data exists
        actual_rpes = [r["actual_rpe"] for r in rpe_data]
        if any(v is not None for v in actual_rpes):
            datasets.append({"label": "Your RPE (checkin)", "data": actual_rpes,
                             "borderColor": Z4, "borderWidth": 2, "pointRadius": 4, "fill": False,
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
                    # Color by zone compliance, not just distance
                    if m.get("intensity_override"):
                        day_data[d]["status"] = "override"  # planned easy, ran hard
                    elif m.get("zone_match", True):
                        day_data[d]["status"] = "matched"  # right zone
                    else:
                        day_data[d]["status"] = "zone_mismatch"  # wrong zone
                    day_data[d]["zone_info"] = f"HR {m.get('actual_hr', '?')} {m.get('actual_zone', '?')}"
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
                        colors.append(SAFE + "80")        # green = right zone
                    elif v["status"] == "override":
                        colors.append(DANGER + "80")      # red = planned easy, ran hard
                    elif v["status"] == "zone_mismatch":
                        colors.append(CAUTION + "80")     # yellow = wrong zone
                    elif v["status"] == "missed":
                        colors.append("#64748b80")        # gray = not done yet
                    elif v["status"] == "unplanned":
                        colors.append(Z2 + "80")         # blue = extra run
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

    # First Z2 run (milestone annotation — only on training charts)
    try:
        first_z2 = conn.execute("""
            SELECT date FROM activities
            WHERE type IN ('running','track_running','trail_running')
            AND hr_zone IN ('Z1', 'Z2') AND date >= date('now', '-30 days')
            ORDER BY date ASC LIMIT 1
        """).fetchone()
        if first_z2:
            annotations["first_z2"] = {
                "type": "line", "xMin": first_z2["date"], "xMax": first_z2["date"],
                "borderColor": SAFE + "60", "borderWidth": 1.5,
                "label": {"content": "First Z2 ✓", "display": True,
                          "position": "end", "font": {"size": 7}, "color": SAFE + "80"},
            }
    except Exception:
        pass

    return annotations


def _get_acwr_annotations(conn) -> dict:
    """ACWR spike annotations — only for the ACWR chart, not all charts.

    Limits to top 3 most extreme spikes to avoid clutter.
    """
    annotations = {}
    try:
        acwr_spikes = conn.execute("""
            SELECT week, acwr FROM weekly_agg
            WHERE acwr IS NOT NULL AND acwr > 1.5
            ORDER BY acwr DESC LIMIT 3
        """).fetchall()
        for i, spike in enumerate(acwr_spikes):
            week_str = spike["week"]
            year = int(week_str[:4])
            week_num = int(week_str.split("W")[1])
            try:
                spike_date = date.fromisocalendar(year, week_num, 1).isoformat()
                annotations[f"acwr_spike_{i}"] = {
                    "type": "line", "xMin": spike_date, "xMax": spike_date,
                    "borderColor": DANGER + "60", "borderWidth": 1.5,
                    "label": {"content": f"ACWR {spike['acwr']:.1f}", "display": True,
                              "position": "start", "font": {"size": 7}, "color": DANGER + "80"},
                }
            except ValueError:
                pass
    except Exception:
        pass
    return annotations


