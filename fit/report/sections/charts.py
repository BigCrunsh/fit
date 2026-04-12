"""Chart data generation for all dashboard tabs."""

import json
import logging
from datetime import date

from fit.analysis import RUNNING_TYPES_SQL

from fit.report.sections import SAFE, CAUTION, DANGER, Z1, Z2, Z3, Z4, Z5, ACCENT

logger = logging.getLogger(__name__)



def _all_charts(conn):
    charts = []

    # Volume (Training tab) — 12 weeks default, phase target as shaded band, rolling current bar
    from fit.analysis import compute_rolling_week
    weeks = conn.execute("SELECT week, run_km, longest_run_km FROM weekly_agg WHERE run_km > 0 ORDER BY week").fetchall()
    # Limit to last 12 weeks
    if len(weeks) > 12:
        weeks = weeks[-12:]
    if weeks:
        def _week_end_label(w):
            try:
                from datetime import datetime
                return datetime.strptime(
                    w + "-7", "%G-W%V-%u"
                ).strftime("%b %-d")
            except Exception:
                return w
        labels = [_week_end_label(w["week"]) for w in weeks]
        data = [w["run_km"] for w in weeks]
        bg_colors = ["rgba(56,189,248,0.5)"] * len(weeks)

        # Add rolling 7-day bar as "current" if current ISO week isn't in the data
        rolling = compute_rolling_week(conn)
        today = date.today()
        iso = today.isocalendar()
        current_week = f"{iso[0]}-W{iso[1]:02d}"
        if current_week not in labels and rolling["run_km"] > 0:
            labels.append("Last 7d")
            data.append(rolling["run_km"])
            bg_colors.append("rgba(56,189,248,0.8)")  # brighter for rolling

        # Phase target as shaded band (box annotation, 40+ hex opacity)
        phase_vol = conn.execute("SELECT weekly_km_min, weekly_km_max FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
        vol_annots = {}
        if phase_vol and phase_vol["weekly_km_min"]:
            vol_annots["target_band"] = {
                "type": "box",
                "yMin": phase_vol["weekly_km_min"],
                "yMax": phase_vol["weekly_km_max"],
                "backgroundColor": SAFE + "40",
                "borderWidth": 0,
                "label": {
                    "content": f"target {phase_vol['weekly_km_min']:.0f}-{phase_vol['weekly_km_max']:.0f}km",
                    "display": True, "position": {"x": "end", "y": "start"},
                    "font": {"size": 8}, "color": SAFE + "90",
                },
            }

        # Gap annotations: shaded regions for training breaks >14 days
        from fit.narratives import generate_volume_story
        vol_story = generate_volume_story(conn)
        if vol_story and vol_story.get("gaps"):
            for i, gap in enumerate(vol_story["gaps"]):
                # Find labels that bracket this gap
                vol_annots[f"gap_{i}"] = {
                    "type": "box",
                    "xMin": gap["start"][:10],
                    "xMax": gap["end"][:10],
                    "backgroundColor": "rgba(255,255,255,0.05)",
                    "borderWidth": 0,
                    "label": {
                        "content": f"{gap['days']}d break",
                        "display": True, "position": "center",
                        "font": {"size": 7}, "color": "rgba(255,255,255,0.3)",
                    },
                }

        charts.append({"id": "chart-volume", "config": json.dumps({
            "type": "bar",
            "data": {"labels": labels,
                     "datasets": [{"label": "km/week", "data": data,
                                   "backgroundColor": bg_colors, "borderRadius": 4}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                                                         "annotation": {"annotations": vol_annots} if vol_annots else {}},
                        "scales": {"x": {"grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Readiness (Body tab) — standalone bar chart, no competing lines
    health = conn.execute("SELECT date, training_readiness, resting_heart_rate, hrv_last_night FROM daily_health WHERE date >= date('now','-30 days') ORDER BY date").fetchall()
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
                                     "backgroundColor": SAFE + "20", "borderWidth": 0,
                                     "label": {"content": "Ready >=75", "display": True, "position": "start", "font": {"size": 7}, "color": SAFE + "60"}},
                            "rest": {"type": "box", "yMin": 0, "yMax": 50,
                                     "backgroundColor": DANGER + "18", "borderWidth": 0,
                                     "label": {"content": "Rest <50", "display": True, "position": "start", "font": {"size": 7}, "color": DANGER + "60"}},
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
    sleep = conn.execute("SELECT date, deep_sleep_hours, rem_sleep_hours, light_sleep_hours FROM daily_health WHERE date >= date('now','-30 days') ORDER BY date").fetchall()
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
        FROM daily_health WHERE date >= date('now','-30 days') AND (avg_stress_level IS NOT NULL OR body_battery_high IS NOT NULL)
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

    # Weight (Body tab) — last 6 months by default (the actionable trend)
    # Older data creates visual gaps and scale jumps that obscure the trend
    weight = conn.execute(
        "SELECT date, weight_kg, body_fat_pct, muscle_mass_kg FROM body_comp WHERE date >= date('now', '-180 days') ORDER BY date"
    ).fetchall()
    # Fallback to all data if <5 records in last 6 months
    if len(weight) < 5:
        weight = conn.execute("SELECT date, weight_kg, body_fat_pct, muscle_mass_kg FROM body_comp ORDER BY date").fetchall()
    if weight:
        weight_target = conn.execute("SELECT target_value FROM goals WHERE type = 'metric' AND name LIKE '%eight%' AND active = 1 LIMIT 1").fetchone()
        weight_annots = {}  # today/race markers added via JS
        if weight_target and weight_target["target_value"]:
            tv = weight_target["target_value"]
            weight_annots["target"] = {
                "type": "box", "yMin": tv - 0.5, "yMax": tv + 0.5,
                "backgroundColor": SAFE + "28", "borderColor": SAFE + "44",
                "label": {"content": "Race weight", "display": True, "position": "start",
                          "color": SAFE, "font": {"size": 10}, "backgroundColor": "transparent"},
            }
        weight_labels = [w["date"] for w in weight]
        weight_data = [w["weight_kg"] for w in weight]
        bf_data = [w["body_fat_pct"] for w in weight]
        muscle_data = [w["muscle_mass_kg"] for w in weight]

        datasets = [{"label": "Weight (kg)", "data": weight_data,
                      "borderColor": "rgba(148,163,184,0.6)", "borderWidth": 2,
                      "pointRadius": 4, "pointBackgroundColor": "rgba(148,163,184,0.8)",
                      "tension": 0.3, "fill": False, "yAxisID": "y", "spanGaps": False}]
        has_bf = any(v is not None for v in bf_data)
        has_muscle = any(v is not None for v in muscle_data)
        has_secondary = has_bf or has_muscle
        scales = {"x": {"type": "time", "time": {"unit": "month", "displayFormats": {"month": "MMM ''yy"}, "tooltipFormat": "yyyy-MM-dd"}, "grid": {"display": False}},
                  "y": {"grid": {"color": "rgba(255,255,255,0.03)"}, "position": "left", "title": {"display": True, "text": "kg"}}}
        if has_muscle:
            datasets.append({"label": "Muscle (kg)", "data": muscle_data, "borderColor": Z2 + "80",
                              "borderWidth": 1.5, "pointRadius": 3, "fill": False, "yAxisID": "y", "spanGaps": True,
                              "borderDash": [4, 2]})
        if has_bf:
            datasets.append({"label": "Body Fat %", "data": bf_data, "borderColor": DANGER + "60",
                              "borderWidth": 1.5, "pointRadius": 2, "fill": False, "yAxisID": "y1", "spanGaps": True})
            scales["y1"] = {"grid": {"drawOnChartArea": False}, "position": "right",
                            "title": {"display": True, "text": "Body Fat (%)"}, "min": 5, "max": 30}
        charts.append({"id": "chart-weight", "config": json.dumps({
            "type": "line",
            "data": {"labels": weight_labels, "datasets": datasets},
            "options": {"responsive": True, "plugins": {"legend": {"display": has_secondary, "position": "bottom", "labels": {"boxWidth": 12}},
                                                         "annotation": {"annotations": weight_annots}},
                        "scales": scales}
        })})

    # Aerobic Efficiency — Z2 speed/bpm preferred, fallback to all-runs speed/bpm
    eff_z2 = conn.execute(f"SELECT date, speed_per_bpm_z2 FROM activities WHERE type IN {RUNNING_TYPES_SQL} AND speed_per_bpm_z2 IS NOT NULL ORDER BY date").fetchall()
    if eff_z2:
        eff_label = "speed/bpm (Z2)"
        eff_dates = [e["date"] for e in eff_z2]
        eff_values = [round(e["speed_per_bpm_z2"], 4) for e in eff_z2]
    else:
        eff_all = conn.execute(f"SELECT date, speed_per_bpm FROM activities WHERE type IN {RUNNING_TYPES_SQL} AND speed_per_bpm IS NOT NULL ORDER BY date").fetchall()
        eff_label = "speed/bpm (all runs)"
        eff_dates = [e["date"] for e in eff_all]
        eff_values = [round(e["speed_per_bpm"], 4) for e in eff_all]
    if eff_values:
        charts.append({"id": "chart-efficiency", "config": json.dumps({
            "type": "line",
            "data": {"labels": eff_dates,
                     "datasets": [
                         {"label": eff_label, "data": eff_values,
                          "borderColor": ACCENT + "cc", "borderWidth": 2, "pointRadius": 3, "tension": 0.3,
                          "fill": {"target": "origin", "above": ACCENT + "0f"}},
                     ]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False}},
                        "scales": {"x": {"grid": {"display": False}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # VO2max + VDOT Trend — 3 datasets: Garmin VO2max (gray dashed), Race VDOT (scatter dots), Effective VDOT (blue line)
    # Plus green target VDOT annotation line
    vo2 = conn.execute("SELECT date, vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date").fetchall()
    if vo2:
        # Monthly Garmin VO2max (gray dashed line)
        vo2_monthly = conn.execute("""
            SELECT substr(date, 1, 7) as month, ROUND(AVG(vo2max), 1) as avg_vo2
            FROM activities WHERE vo2max IS NOT NULL GROUP BY month ORDER BY month
        """).fetchall()

        # Race VDOT points (computed from race_calendar result_time + distance_km)
        race_rows = conn.execute("""
            SELECT rc.date, rc.distance_km, rc.result_time FROM race_calendar rc
            WHERE rc.result_time IS NOT NULL AND rc.distance_km IS NOT NULL
            ORDER BY rc.date
        """).fetchall()
        race_vdots = []
        try:
            from fit.fitness import compute_vdot_from_race
            for rr in race_rows:
                _tp = rr["result_time"].split(":")
                if len(_tp) == 3:
                    _secs = int(_tp[0]) * 3600 + int(_tp[1]) * 60 + int(_tp[2])
                elif len(_tp) == 2:
                    _secs = int(_tp[0]) * 60 + int(_tp[1])
                else:
                    continue
                _vdot = round(compute_vdot_from_race(rr["distance_km"], _secs), 1)
                race_vdots.append({"date": rr["date"], "vdot": _vdot})
        except Exception:
            pass

        # Merge all months from Garmin VO2max AND race data, sorted chronologically
        garmin_by_month = {v["month"]: v["avg_vo2"] for v in vo2_monthly}
        race_by_month = {r["date"][:7]: r["vdot"] for r in race_vdots}

        all_months = sorted(set(list(garmin_by_month.keys()) + list(race_by_month.keys())))
        # Convert YYYY-MM to YYYY-MM-15 for time axis (mid-month for visual centering)
        labels = [m + "-15" for m in all_months]
        garmin_data = [garmin_by_month.get(m, None) for m in all_months]
        race_data = [race_by_month.get(m, None) for m in all_months]

        # Effective VDOT = blend of Garmin + race data
        effective_data = []
        for m in all_months:
            rv = race_by_month.get(m)
            gv = garmin_by_month.get(m)
            if rv and gv:
                effective_data.append(round((rv + gv) / 2, 1))
            elif rv:
                effective_data.append(rv)
            elif gv:
                effective_data.append(gv)
            else:
                effective_data.append(None)

        datasets = [
            {"label": "Garmin VO2max", "data": garmin_data,
             "borderColor": "rgba(148,163,184,0.6)", "borderWidth": 2, "pointRadius": 3,
             "tension": 0.3, "borderDash": [4, 2], "fill": False, "spanGaps": True},
            {"label": "Race VDOT", "data": race_data,
             "borderColor": ACCENT + "e6", "borderWidth": 2, "pointRadius": 6,
             "pointBackgroundColor": ACCENT, "tension": 0, "spanGaps": False, "fill": False,
             "showLine": False},
            {"label": "Effective VDOT", "data": effective_data,
             "borderColor": Z2 + "cc", "borderWidth": 2, "pointRadius": 3,
             "tension": 0.3, "fill": False, "spanGaps": True},
        ]

        # Target VDOT annotation (green line) — today/race markers added via JS
        vo2_annots = {}
        try:
            from fit.goals import get_target_race as _gtr
            _target = _gtr(conn)
            if _target and _target.get("target_time"):
                from fit.fitness import compute_vdot_from_race
                _tt = _target["target_time"]
                _tp = _tt.split(":")
                _secs = int(_tp[0]) * 3600 + int(_tp[1]) * 60 + (int(_tp[2]) if len(_tp) > 2 else 0)
                _dist = _target.get("distance_km", 42.195)
                _target_vdot = round(compute_vdot_from_race(_dist, _secs), 1)
                vo2_annots["target"] = {
                    "type": "box", "yMin": _target_vdot - 0.5, "yMax": _target_vdot + 0.5,
                    "backgroundColor": SAFE + "28", "borderColor": SAFE + "44",
                    "label": {"content": f"Target VDOT {_target_vdot}", "display": True,
                              "position": "start", "color": SAFE, "font": {"size": 10},
                              "backgroundColor": "transparent"},
                }
        except Exception:
            pass

        charts.append({"id": "chart-vo2", "config": json.dumps({
            "type": "line",
            "data": {"labels": labels, "datasets": datasets},
            "options": {"responsive": True,
                        "plugins": {"legend": {"labels": {"boxWidth": 10, "padding": 12}},
                                    "annotation": {"annotations": vo2_annots}},
                        "scales": {"x": {"grid": {"display": False}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # Zone distribution (Profile tab) — percentages, stacked to 100%
    zone_weeks = conn.execute("SELECT week, z1_min, z2_min, z3_min, z4_min, z5_min FROM weekly_agg WHERE (z1_min+z2_min+z3_min+z4_min+z5_min) > 0 ORDER BY week DESC LIMIT 8").fetchall()
    if zone_weeks:
        zone_weeks = list(reversed(zone_weeks))
        # Convert to percentages
        z1_pct, z2_pct, z3_pct, z4_pct, z5_pct = [], [], [], [], []
        for w in zone_weeks:
            total = (w["z1_min"] or 0) + (w["z2_min"] or 0) + (w["z3_min"] or 0) + (w["z4_min"] or 0) + (w["z5_min"] or 0)
            if total > 0:
                z1_pct.append(round((w["z1_min"] or 0) / total * 100, 1))
                z2_pct.append(round((w["z2_min"] or 0) / total * 100, 1))
                z3_pct.append(round((w["z3_min"] or 0) / total * 100, 1))
                z4_pct.append(round((w["z4_min"] or 0) / total * 100, 1))
                z5_pct.append(round((w["z5_min"] or 0) / total * 100, 1))
            else:
                z1_pct.append(0)
                z2_pct.append(0)
                z3_pct.append(0)
                z4_pct.append(0)
                z5_pct.append(0)
        # Get active phase targets for annotation
        zone_annots = {}
        phase_rows = conn.execute(
            "SELECT name, start_date, end_date, z12_pct_target, z45_pct_target FROM training_phases WHERE z12_pct_target IS NOT NULL ORDER BY start_date"
        ).fetchall()
        for i, pr in enumerate(phase_rows):
            z12 = pr["z12_pct_target"]
            z45 = pr["z45_pct_target"] or 0
            # Z1+Z2 target band (blue, from bottom up)
            zone_annots[f"z12_band_{i}"] = {
                "type": "box", "yMin": 0, "yMax": z12,
                "xMin": pr["start_date"], "xMax": pr["end_date"],
                "backgroundColor": Z2 + "28", "borderColor": Z2 + "44",
            }
            # Z3 target band (yellow, middle zone)
            z3_implied = 100 - z12 - z45
            if z3_implied > 0:
                zone_annots[f"z3_band_{i}"] = {
                    "type": "box", "yMin": z12, "yMax": z12 + z3_implied,
                    "xMin": pr["start_date"], "xMax": pr["end_date"],
                    "backgroundColor": Z3 + "28", "borderColor": Z3 + "44",
                }
            # Z4+Z5 target band (red, from top down)
            if z45 > 0:
                zone_annots[f"z45_band_{i}"] = {
                    "type": "box", "yMin": 100 - z45, "yMax": 100,
                    "xMin": pr["start_date"], "xMax": pr["end_date"],
                    "backgroundColor": DANGER + "28", "borderColor": DANGER + "44",
                }

        # Convert ISO week labels to Monday dates for time-axis compatibility
        def _week_to_date(w):
            """Convert '2026-W15' to '2026-04-06' (Monday of that week)."""
            from datetime import datetime
            try:
                return datetime.strptime(w + "-1", "%G-W%V-%u").strftime("%Y-%m-%d")
            except Exception:
                return w
        zone_labels = [_week_to_date(w["week"]) for w in zone_weeks]

        charts.append({"id": "chart-zones", "config": json.dumps({
            "type": "bar",
            "data": {"labels": zone_labels,
                     "datasets": [
                         {"label": "Z1", "data": z1_pct, "backgroundColor": Z1 + "b3"},
                         {"label": "Z2", "data": z2_pct, "backgroundColor": Z2 + "b3"},
                         {"label": "Z3", "data": z3_pct, "backgroundColor": Z3 + "b3"},
                         {"label": "Z4", "data": z4_pct, "backgroundColor": Z4 + "b3"},
                         {"label": "Z5", "data": z5_pct, "backgroundColor": Z5 + "b3"},
                     ]},
            "options": {"responsive": True, "plugins": {"legend": {"labels": {"boxWidth": 10, "padding": 8}},
                                                         "annotation": {"annotations": zone_annots}},
                        "scales": {"x": {"stacked": True, "type": "time", "offset": True,
                                         "time": {"unit": "week", "displayFormats": {"week": "MMM d"}, "tooltipFormat": "yyyy-MM-dd"},
                                         "grid": {"display": False}},
                                   "y": {"stacked": True, "max": 100, "grid": {"color": "rgba(255,255,255,0.03)"},
                                         "ticks": {"callback": "__PCT_CB__"}}}}
        }).replace('"__PCT_CB__"', 'function(v){return v+"%"}')})

    # Cardiac Drift charts (Profile tab)
    # 1. Per-km chart: individual runs (thin) + 4-week average (thick), dual-axis pace + HR
    # 2. Drift-over-time chart: drift % per run as time series
    from collections import defaultdict
    drift_runs = conn.execute("""
        SELECT a.id, a.date, a.name, COUNT(s.split_num) as n_splits
        FROM activities a
        JOIN activity_splits s ON s.activity_id = a.id
        WHERE a.type IN ('running','track_running','trail_running')
          AND a.date >= date('now', '-28 days')
        GROUP BY a.id HAVING n_splits >= 5
        ORDER BY a.date
    """).fetchall()
    if drift_runs:
        # Collect per-run split data + per-km averages
        pace_by_km = defaultdict(list)
        hr_by_km = defaultdict(list)
        max_splits = 0
        run_splits = []  # list of {date, name, pace: [...], hr: [...]}
        drift_pcts = []  # for drift-over-time chart

        for run in drift_runs:
            splits = conn.execute(
                "SELECT split_num, pace_sec_per_km, avg_hr FROM activity_splits WHERE activity_id = ? ORDER BY split_num",
                (run["id"],)
            ).fetchall()
            run_pace = {}
            run_hr = {}
            hr_vals = []
            for s in splits:
                km = s["split_num"]
                if s["pace_sec_per_km"]:
                    pace_by_km[km].append(s["pace_sec_per_km"])
                    run_pace[km] = round(s["pace_sec_per_km"] / 60, 2)
                if s["avg_hr"]:
                    hr_by_km[km].append(s["avg_hr"])
                    run_hr[km] = round(s["avg_hr"], 0)
                    hr_vals.append(s["avg_hr"])
                max_splits = max(max_splits, km)
            run_splits.append({"date": run["date"], "name": run["name"] or run["date"],
                               "pace": run_pace, "hr": run_hr, "n": max(run_pace.keys()) if run_pace else 0})

            # Compute drift % for this run: (second-half avg HR / first-half avg HR - 1) × 100
            if len(hr_vals) >= 6:
                mid = len(hr_vals) // 2
                first_half = hr_vals[:mid]
                second_half = hr_vals[mid:]
                if first_half and second_half:
                    first_avg = sum(first_half) / len(first_half)
                    second_avg = sum(second_half) / len(second_half)
                    if first_avg > 0:
                        drift_pct = round((second_avg / first_avg - 1) * 100, 1)
                        drift_pcts.append({"date": run["date"], "drift": drift_pct})

        if max_splits >= 5:
            split_labels = [f"{i}km" for i in range(1, max_splits + 1)]

            # Average lines (thick)
            avg_pace = [round(sum(pace_by_km[i]) / len(pace_by_km[i]) / 60, 2)
                        if pace_by_km.get(i) else None for i in range(1, max_splits + 1)]
            avg_hr = [round(sum(hr_by_km[i]) / len(hr_by_km[i]), 0)
                      if hr_by_km.get(i) else None for i in range(1, max_splits + 1)]

            # Individual run lines (thin, faint)
            datasets = []
            for idx, rs in enumerate(run_splits):
                short_name = rs["date"][-5:]  # MM-DD
                # Pace line for this run
                pace_vals = [rs["pace"].get(i) for i in range(1, max_splits + 1)]
                datasets.append({
                    "label": f"Pace {short_name}", "data": pace_vals,
                    "borderColor": Z2 + "30", "borderWidth": 1, "pointRadius": 0,
                    "tension": 0.3, "yAxisID": "y", "fill": False, "spanGaps": True,
                })
                # HR line for this run
                hr_vals_run = [rs["hr"].get(i) for i in range(1, max_splits + 1)]
                datasets.append({
                    "label": f"HR {short_name}", "data": hr_vals_run,
                    "borderColor": DANGER + "25", "borderWidth": 1, "pointRadius": 0,
                    "tension": 0.3, "yAxisID": "y1", "fill": False, "spanGaps": True,
                })

            # Average lines on top (thick, bold)
            datasets.append({"label": "Avg Pace", "data": avg_pace,
                             "borderColor": Z2 + "cc", "borderWidth": 2.5, "pointRadius": 2,
                             "tension": 0.3, "yAxisID": "y", "fill": False})
            datasets.append({"label": "Avg HR", "data": avg_hr,
                             "borderColor": DANGER + "b3", "borderWidth": 2.5, "pointRadius": 2,
                             "tension": 0.3, "yAxisID": "y1", "fill": False})

            # Drift onset on the average
            drift_onset = None
            valid_first_half = [h for h in avg_hr[:max_splits // 2] if h is not None]
            if valid_first_half:
                first_half_avg = sum(valid_first_half) / len(valid_first_half)
                for i in range(max_splits // 2, max_splits):
                    if avg_hr[i] and avg_hr[i] > first_half_avg + 5:
                        drift_onset = i
                        break
            drift_annots = {}
            if drift_onset is not None:
                drift_annots["drift"] = {
                    "type": "line", "xMin": drift_onset, "xMax": drift_onset,
                    "borderColor": CAUTION + "80", "borderDash": [4, 3], "borderWidth": 1,
                    "label": {"display": True, "content": "Drift onset", "position": "start",
                              "color": CAUTION, "font": {"size": 9}, "backgroundColor": "transparent",
                              "yAdjust": -10},
                }

            n_runs = len(drift_runs)
            charts.append({"id": "chart-drift", "config": json.dumps({
                "type": "line",
                "data": {"labels": split_labels, "datasets": datasets},
                "options": {"responsive": True,
                            "plugins": {"legend": {"display": True,
                                                    "labels": {"boxWidth": 10, "padding": 12,
                                                               "filter": "__DRIFT_LEGEND_FILTER__"}},
                                        "annotation": {"annotations": drift_annots}},
                            "scales": {
                                "y": {"position": "left", "reverse": True,
                                      "title": {"display": True, "text": "Pace", "color": "#64748b", "font": {"size": 10}},
                                      "grid": {"color": "rgba(255,255,255,0.03)"}},
                                "y1": {"position": "right",
                                       "title": {"display": True, "text": "HR", "color": "#64748b", "font": {"size": 10}},
                                       "grid": {"display": False}},
                                "x": {"grid": {"display": False}, "ticks": {"maxTicksLimit": 10}}}}
            }).replace('"__DRIFT_LEGEND_FILTER__"',
                       'function(item){return item.text.startsWith("Avg")}'),
                "n_runs": n_runs})

    # Cardiac Drift Over Time — drift onset km per run as time series
    # Compute drift onset for each run with splits (re-query all history for full timeline)
    def _compute_drift_onset(hr_vals):
        """Return km index where drift onset occurs (first split in second half where HR > first-half avg + 5), or None."""
        n = len(hr_vals)
        if n < 6:
            return None
        mid = n // 2
        first_half = [h for h in hr_vals[:mid] if h is not None]
        if not first_half:
            return None
        first_avg = sum(first_half) / len(first_half)
        for i in range(mid, n):
            if hr_vals[i] is not None and hr_vals[i] > first_avg + 5:
                return i + 1  # 1-indexed km
        return n + 1  # No drift detected — onset beyond run distance (good)

    drift_onset_data = []
    all_drift_runs = conn.execute("""
        SELECT a.id, a.date, a.distance_km FROM activities a
        JOIN activity_splits s ON s.activity_id = a.id
        WHERE a.type IN ('running','track_running','trail_running')
        GROUP BY a.id HAVING COUNT(s.split_num) >= 6
        ORDER BY a.date
    """).fetchall()
    for run in all_drift_runs:
        hr_vals = [s["avg_hr"] for s in conn.execute(
            "SELECT avg_hr FROM activity_splits WHERE activity_id = ? ORDER BY split_num",
            (run["id"],)
        ).fetchall()]
        onset = _compute_drift_onset(hr_vals)
        if onset is not None:
            drift_onset_data.append({"date": run["date"], "onset_km": onset,
                                     "dist": round(run["distance_km"] or 0, 1)})
    if drift_onset_data:
        max_onset = max(d["onset_km"] for d in drift_onset_data)
        charts.append({"id": "chart-drift-trend", "config": json.dumps({
            "type": "scatter",
            "data": {"datasets": [{
                "label": "Drift Onset (km)",
                "data": [{"x": d["date"], "y": d["onset_km"]} for d in drift_onset_data],
                "borderColor": DANGER + "b3", "backgroundColor": DANGER + "60",
                "pointRadius": 5, "showLine": True, "borderWidth": 2, "tension": 0.3,
            }]},
            "options": {"responsive": True,
                        "plugins": {"legend": {"display": False},
                                    "tooltip": {"callbacks": {"__DRIFT_ONSET_TT__": True}},
                                    "annotation": {"annotations": {
                                        "good": {"type": "box", "yMin": 15, "yMax": max(max_onset + 2, 20),
                                                 "backgroundColor": SAFE + "28", "borderColor": SAFE + "44",
                                                 "label": {"content": "Good (>15km)", "display": True,
                                                           "position": "start", "color": SAFE,
                                                           "font": {"size": 10}, "backgroundColor": "transparent"}},
                                    }}},
                        "scales": {"y": {"title": {"display": True, "text": "Drift onset (km)",
                                                   "color": "#64748b", "font": {"size": 10}},
                                         "min": 0,
                                         "grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "x": {"type": "time", "grid": {"display": False}}}}
        }).replace('"__DRIFT_ONSET_TT__": true',
                   '"label": function(ctx){return "Drift onset: km "+ctx.parsed.y}')})

    # Pace Consistency (CV%) — line chart with purple fill (Profile tab)
    pace_cv = conn.execute(f"""
        SELECT a.date, a.id,
               (SELECT AVG(s.pace_sec_per_km) FROM activity_splits s WHERE s.activity_id = a.id) as avg_pace,
               (SELECT COUNT(*) FROM activity_splits s WHERE s.activity_id = a.id) as n_splits
        FROM activities a
        WHERE a.type IN {RUNNING_TYPES_SQL}
          AND a.id IN (SELECT DISTINCT activity_id FROM activity_splits)
        ORDER BY a.date
    """).fetchall()
    if pace_cv and len(pace_cv) >= 2:
        # Compute CV for each run that has splits
        cv_labels, cv_data = [], []
        for row in pace_cv:
            if row["n_splits"] and row["n_splits"] >= 3 and row["avg_pace"]:
                splits = conn.execute(
                    "SELECT pace_sec_per_km FROM activity_splits WHERE activity_id = ? AND pace_sec_per_km IS NOT NULL",
                    (row["id"],)
                ).fetchall()
                if len(splits) >= 3:
                    paces = [s["pace_sec_per_km"] for s in splits]
                    mean_p = sum(paces) / len(paces)
                    if mean_p > 0:
                        stdev_p = (sum((p - mean_p) ** 2 for p in paces) / len(paces)) ** 0.5
                        cv = round(stdev_p / mean_p * 100, 1)
                        cv_labels.append(row["date"])
                        cv_data.append(cv)
        if len(cv_labels) >= 2:
            PURPLE = "#c084fc"
            charts.append({"id": "chart-pacecv", "config": json.dumps({
                "type": "line",
                "data": {"labels": cv_labels,
                         "datasets": [{"label": "Pace CV %", "data": cv_data,
                                       "borderColor": PURPLE + "b3", "borderWidth": 2, "pointRadius": 3, "tension": 0.3,
                                       "fill": {"target": "origin", "above": PURPLE + "0d"}}]},
                "options": {"responsive": True, "plugins": {"legend": {"display": False}},
                            "scales": {"y": {"grid": {"color": "rgba(255,255,255,0.03)"},
                                             "ticks": {"callback": "__PCVCB__"}},
                                       "x": {"grid": {"display": False}}}}
            }).replace('"__PCVCB__"', 'function(v){return v+"%"}')})

    # Effort Gap — Garmin TE vs Check-in RPE (Profile tab)
    # Join activities with checkins to get RPE from check-in table (activities.rpe is rarely populated)
    effort_data = conn.execute(f"""
        SELECT a.date, a.aerobic_te,
               c.rpe as checkin_rpe
        FROM activities a
        LEFT JOIN checkins c ON a.date = c.date
        WHERE a.type IN {RUNNING_TYPES_SQL} AND a.aerobic_te IS NOT NULL
        ORDER BY a.date
    """).fetchall()
    if effort_data and len(effort_data) >= 3:
        te_values = [e["aerobic_te"] for e in effort_data]
        # Normalize check-in RPE from 1-10 to 1-5 scale to match TE scale
        rpe_values = [round(e["checkin_rpe"] / 2, 1) if e["checkin_rpe"] is not None else None for e in effort_data]
        has_rpe = any(v is not None for v in rpe_values)

        # Compute 5-point moving average trend lines
        def _moving_avg(data, window=5):
            result = []
            for i in range(len(data)):
                vals = [data[j] for j in range(max(0, i - window + 1), i + 1) if data[j] is not None]
                result.append(round(sum(vals) / len(vals), 2) if vals else None)
            return result

        te_trend = _moving_avg(te_values)

        datasets = [
            {"label": "Garmin TE", "data": te_values,
             "borderColor": "rgba(148,163,184,0.3)", "borderWidth": 1, "pointRadius": 2, "tension": 0.3, "fill": False},
            {"label": "TE trend", "data": te_trend,
             "borderColor": "rgba(148,163,184,0.8)", "borderWidth": 2, "pointRadius": 0, "tension": 0.4, "fill": False},
        ]
        if has_rpe:
            rpe_trend = _moving_avg(rpe_values)
            datasets.append(
                {"label": "Check-in RPE", "data": rpe_values,
                 "borderColor": Z4 + "40", "borderWidth": 1, "pointRadius": 3, "tension": 0.3,
                 "fill": False, "spanGaps": False}
            )
            datasets.append(
                {"label": "RPE trend", "data": rpe_trend,
                 "borderColor": Z4 + "cc", "borderWidth": 2, "pointRadius": 0, "tension": 0.4,
                 "fill": False, "spanGaps": True}
            )
        # Find actual max to set y-axis with headroom
        all_vals = [v for v in te_values if v is not None] + [v for v in rpe_values if v is not None]
        y_max = max(6, round(max(all_vals) + 1)) if all_vals else 6
        charts.append({"id": "chart-effort-gap", "config": json.dumps({
            "type": "line",
            "data": {"labels": [e["date"] for e in effort_data], "datasets": datasets},
            "options": {"responsive": True,
                        "plugins": {"legend": {"labels": {"boxWidth": 10, "padding": 12}}},
                        "scales": {"y": {"min": 0, "max": y_max, "grid": {"color": "rgba(255,255,255,0.03)"}},
                                   "x": {"grid": {"display": False}, "ticks": {"maxRotation": 45}}}}
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
                          "backgroundColor": SAFE + "20", "borderWidth": 0,
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
    type_weeks = conn.execute(f"""
        SELECT strftime('%Y-W', date, 'weekday 0', '-6 days') ||
               substr('0' || (cast(strftime('%W', date) as integer)), -2) as week,
               run_type, COUNT(*) as n
        FROM activities WHERE type IN {RUNNING_TYPES_SQL} AND run_type IS NOT NULL
        GROUP BY week, run_type ORDER BY week
    """).fetchall()
    if type_weeks:
        weeks_set = sorted({r["week"] for r in type_weeks})[-12:]  # last 12 weeks
        type_names = ["easy", "long", "tempo", "intervals", "recovery", "race"]
        # Distinct colors: blue family for easy, warm for hard, purple for race
        # Long runs are aerobic base — same blue family as easy/recovery
        type_colors = {
            "easy": Z2,               # blue-400
            "recovery": Z1 + "80",    # blue-300 faded
            "long": "#3b82f6",        # blue-500 (darker — distinct but same family)
            "tempo": Z3,              # warm yellow
            "intervals": Z4,          # orange
            "race": ACCENT,           # purple
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
    cadence = conn.execute(f"""
        SELECT date, avg_cadence FROM activities
        WHERE type IN {RUNNING_TYPES_SQL} AND avg_cadence IS NOT NULL AND date >= date('now','-90 days')
        ORDER BY date
    """).fetchall()
    if cadence:
        PURPLE = "#c084fc"
        cadence_annots = {
            "target_band": {
                "type": "box", "yMin": 170, "yMax": 180,
                "backgroundColor": SAFE + "28", "borderColor": SAFE + "44",
                "label": {"content": "Target 170-180", "display": True, "position": "start",
                          "color": SAFE, "font": {"size": 10}, "backgroundColor": "transparent"},
            }
        }
        charts.append({"id": "chart-cadence", "config": json.dumps({
            "type": "line",
            "data": {"labels": [c["date"] for c in cadence],
                     "datasets": [{"label": "Cadence (spm)", "data": [c["avg_cadence"] for c in cadence],
                                   "borderColor": PURPLE + "b3", "borderWidth": 2, "pointRadius": 3, "tension": 0.3, "fill": False}]},
            "options": {"responsive": True, "plugins": {"legend": {"display": False},
                                                         "annotation": {"annotations": cadence_annots}},
                        "scales": {"x": {"grid": {"display": False}},
                                   "y": {"grid": {"color": "rgba(255,255,255,0.03)"}}}}
        })})

    # RPE chart (Fitness tab) — Garmin effort (from aerobic_te) vs actual RPE
    # aerobic_te is 1-5 Garmin scale, map to RPE 1-10: RPE ≈ aerobic_te * 2
    rpe_data = conn.execute(f"""
        SELECT a.date, a.rpe as actual_rpe, a.aerobic_te,
               ROUND(a.aerobic_te * 2, 1) as garmin_rpe
        FROM activities a
        WHERE a.type IN {RUNNING_TYPES_SQL} AND a.aerobic_te IS NOT NULL
        
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
        first_z2 = conn.execute(f"""
            SELECT date FROM activities
            WHERE type IN {RUNNING_TYPES_SQL}
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


