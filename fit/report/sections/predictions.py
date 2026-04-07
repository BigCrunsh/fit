"""Race prediction section — VDOT, Riegel extrapolation, pacing."""

import logging

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


def _prediction_summary(conn):
    """Compact prediction with confidence for the race card header.

    Shows range from multiple sources, not just VDOT point estimate.
    """
    try:
        from fit.analysis import _vdot_to_marathon_seconds
        from fit.goals import get_target_race

        target_race = get_target_race(conn)
        target_km = target_race["distance_km"] if target_race and target_race.get("distance_km") else 42.195

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

        # Riegel extrapolation to TARGET distance
        all_secs = []
        for r in races:
            if r["distance_km"] and r["result_time"]:
                d1 = r["distance_km"]
                t1 = _parse_time(r["result_time"])
                if d1 > 0 and t1 > 0 and d1 != target_km:
                    t2 = t1 * (target_km / d1) ** 1.06
                    all_secs.append(round(t2))

        # VDOT prediction scaled to target distance
        if vo2 and vo2["vo2max"] and vo2["vo2max"] > 30:
            marathon_secs = _vdot_to_marathon_seconds(vo2["vo2max"])
            if target_km != 42.195:
                vdot_secs = round(marathon_secs * (target_km / 42.195) ** 1.06)
            else:
                vdot_secs = round(marathon_secs)
            all_secs.append(vdot_secs)

        if not all_secs:
            return None

        lo = min(all_secs)
        hi = max(all_secs)

        def _fmt(s):
            return f"{s // 3600}:{(s % 3600) // 60:02d}"

        # Simple confidence based on data count
        level = "moderate" if len(all_secs) >= 5 else "low"
        level_label = {"high": "", "moderate": " (moderate confidence)", "low": " (low confidence)"}

        if hi - lo < 300:  # within 5 min — show single value
            return f"Prediction: {_fmt((lo + hi) // 2)}{level_label.get(level, '')}"
        else:
            return f"Prediction: {_fmt(lo)}–{_fmt(hi)}{level_label.get(level, '')}"
    except Exception:
        return None



def _race_prediction(conn):
    """Generate race prediction table — adapts to target race distance."""
    races = conn.execute("""
        SELECT rc.date, rc.name, rc.distance, rc.distance_km, rc.result_time
        FROM race_calendar rc
        WHERE rc.status = 'completed' AND rc.result_time IS NOT NULL
        ORDER BY rc.date DESC
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
                original_pace = t1 / d1
                race_data.append({
                    "from_race": r["name"], "from_date": r["date"],
                    "distance_km": d1, "predicted_seconds": round(t2),
                    "original_pace": f"{int(original_pace // 60)}:{int(original_pace % 60):02d}/km",
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

    def _delta_html(t):
        delta = t - target_secs
        delta_str = f"{'−' if delta < 0 else '+'}{abs(delta) // 60} min" if abs(delta) > 30 else "= target"
        color = "var(--safe)" if delta < 0 else "var(--caution)" if delta < 300 else "var(--danger)"
        return delta_str, color

    def _row_html(label, sublabel, t, original_pace=None):
        delta_str, color = _delta_html(t)
        pace_cell = f"<td style='font-size:10px;color:var(--text-dim)'>{_fmt_pace(t)}"
        if original_pace:
            pace_cell += f"<br><span style='font-size:8px;color:var(--text-faint)'>ran {original_pace}</span>"
        pace_cell += "</td>"
        return (f"<tr><td style='color:var(--text-muted);font-size:10px'>{label}<br>"
                f"<span style='font-size:9px'>{sublabel}</span></td>"
                f"<td style='font-family:var(--mono);font-size:16px;font-weight:600'>{_fmt_time(t)}</td>"
                f"{pace_cell}"
                f"<td style='font-size:10px;color:{color};font-weight:600'>{delta_str}</td></tr>")

    def _section_header(title):
        return (f"<tr><td colspan='4' style='padding:8px 4px 4px;font-size:9px;font-weight:700;"
                f"color:var(--text-dim);text-transform:uppercase;letter-spacing:0.08em;"
                f"border-bottom:1px solid rgba(255,255,255,0.04)'>{title}</td></tr>")

    # VO2max prediction (separate section)
    rows = []
    if vdot_pred:
        rows.append(_section_header("VO2max Estimate (Daniels)"))
        rows.append(_row_html("VO2max", str(vdot_pred["vo2max"]), vdot_pred["predicted_seconds"]))

    # Group races by distance category
    distance_groups = {}
    for r in race_data:
        d = r.get("distance_km") or 0
        if d > 18:
            group = "Half Marathon"
        elif d > 8:
            group = "10K"
        elif d > 3:
            group = "5K"
        else:
            group = "Other"
        distance_groups.setdefault(group, []).append(r)

    # Render each group (order: HM → 10K → 5K → Other)
    for group_name in ["Half Marathon", "10K", "5K", "Other"]:
        group_races = distance_groups.get(group_name, [])
        if not group_races:
            continue
        rows.append(_section_header(f"From {group_name} races ({len(group_races)})"))
        for r in group_races:  # already sorted by date DESC
            race_date = (r.get("from_date") or "")[:10]
            name = (r.get("from_race") or "")[:25]
            rows.append(_row_html(name, race_date, r["predicted_seconds"], r.get("original_pace")))

    if rows:
        parts.append("<table style='width:100%;border-collapse:collapse;margin:8px 0'>"
                     "<thead><tr style='border-bottom:1px solid rgba(255,255,255,0.06)'>"
                     "<th style='text-align:left;font-size:9px;color:var(--text-dim);padding:4px'>Source</th>"
                     "<th style='text-align:left;font-size:9px;color:var(--text-dim);padding:4px'>Time</th>"
                     "<th style='text-align:left;font-size:9px;color:var(--text-dim);padding:4px'>Pace (extrap / ran)</th>"
                     "<th style='text-align:left;font-size:9px;color:var(--text-dim);padding:4px'>vs Target</th>"
                     "</tr></thead><tbody>" + "".join(rows) + "</tbody></table>")

    parts.append("<div style='font-size:10px;color:var(--text-dim);margin-top:6px'>"
                 "Riegel extrapolates from race times. VDOT from Daniels' tables. "
                 "After a training gap, actual fitness is likely 5-10 min slower than peak predictions.</div>")

    return "\n".join(parts)


