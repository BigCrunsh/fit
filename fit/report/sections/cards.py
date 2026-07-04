"""Dashboard cards, panels, and small section generators."""

import json
import logging
from datetime import date
from pathlib import Path

from fit.analysis import RUNNING_TYPES_SQL, Zone
from fit.report.headline import generate_headline
from fit.narratives import (
    generate_race_countdown,
    generate_body_summary,
)

from fit.report.sections import Z1, Z2, Z3, Z4, Z5

logger = logging.getLogger(__name__)



def _headline(conn):
    from fit.training_load import compute_rolling_acwr
    latest = conn.execute("SELECT training_readiness FROM daily_health ORDER BY date DESC LIMIT 1").fetchone()
    acwr_val = compute_rolling_acwr(conn)   # rolling-7d acute (the documented hybrid; matches coaching/CLI/alerts)
    phase = conn.execute("SELECT * FROM training_phases WHERE status = 'active' LIMIT 1").fetchone()
    return generate_headline(
        readiness=latest["training_readiness"] if latest else None,
        acwr=acwr_val,
        phase=dict(phase) if phase else None,
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
    """Compact race forecast for the race card header.

    Single source = the calibrated VDOT anchor (anchor_race_time), NOT Garmin
    VO2max via the retired table. Returns None when there is no usable anchor.
    """
    try:
        from fit.fitness import anchor_race_time
        from fit.calibration import get_calibration_anchor
        from fit.goals import get_target_race

        target = get_target_race(conn)
        target_km = (target.get("distance_km") if target else None) or 42.195

        headline = anchor_race_time(conn, target_km)
        note = ""
        if headline:
            anchor = get_calibration_anchor(conn, "vdot")
            note = " (stale — re-test)" if (anchor and anchor.stale) else ""
        else:
            # No calibrated anchor → conservative (slowest) Riegel extrapolation
            # from actual races. Never the retired Garmin-VO2max table.
            from fit.analysis import riegel_fallback_secs
            headline = riegel_fallback_secs(conn, target_km)
            note = " (race estimate)" if headline else ""
        if not headline:
            return None
        return f"Prediction: {headline // 3600}:{(headline % 3600) // 60:02d}{note}"
    except Exception:
        return None



_DENSE_THRESHOLD = 3  # ≥ this many distinct readings → render as scatter chart


def _vdot_comparison(conn):
    """Anchor-VDOT vs Garmin-VO2max comparison badge under the VDOT chart.

    The anchor VDOT is the SINGLE standardized value from
    get_calibration_anchor('vdot') — the human-confirmed sticky value, or the
    windowed-max policy estimate from race observations. The source effort
    shown is the best in-window observation that drives the estimate. Garmin's
    wrist-HR VO2max is shown only as a (more optimistic) reference. Marathon
    equivalents use vdot_to_race_time — the same Daniels inverse the VDOT
    estimate uses (NOT the retired conservative table). None when no data.
    """
    from fit.calibration import get_calibration_anchor
    from fit.fitness import vdot_to_race_time

    def _fmt_time(secs):
        secs = int(secs)
        h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

    def _fmt_marathon(secs):
        secs = int(secs)
        return f"{secs // 3600}:{(secs % 3600) // 60:02d}"

    def _marathon(vdot):
        s = vdot_to_race_time(vdot, 42.195)
        return _fmt_marathon(s) if s else None

    anchor = get_calibration_anchor(conn, "vdot")

    garmin_row = conn.execute(
        "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    garmin = float(garmin_row["vo2max"]) if garmin_row and garmin_row["vo2max"] else None

    if anchor is None and not garmin:
        return None

    # Anchor payload — the standardized value + the effort that drives it.
    anchor_payload = None
    anchor_vdot = anchor.value if anchor else None
    if anchor_vdot is not None:
        # Source effort = the top in-window observation (joins to its activity
        # for distance/time). Falls back to the confirmed row's own date.
        src = None
        sug = anchor.suggestion
        if sug and sug.get("inputs"):
            src = sug["inputs"][0]
        src_date = (src or {}).get("date") or (anchor.inputs or [{}])[0].get("date")
        act = None
        if src and src.get("source_activity_id"):
            act = conn.execute(
                "SELECT name, distance_km, duration_min FROM activities WHERE id = ?",
                (src["source_activity_id"],),
            ).fetchone()
        days_ago = (date.today() - date.fromisoformat(src_date)).days if src_date else None
        anchor_payload = {
            "vdot": anchor_vdot,
            "date": src_date,
            "days_ago": days_ago,
            "distance_km": round(act["distance_km"], 1) if act and act["distance_km"] else None,
            "result_time": _fmt_time(act["duration_min"] * 60) if act and act["duration_min"] else None,
            "name": (act["name"] if act and act["name"] else "Confirmed VDOT"),
            "source": "confirmed" if anchor.method in ("manual", "confirmed") else "race",
            "confidence": anchor.confidence,
            "stale": anchor.stale,
        }

    anchor_marathon = _marathon(anchor_vdot) if anchor_vdot is not None else None
    garmin_marathon = _marathon(garmin) if garmin else None

    interpretation = None
    if anchor_vdot is not None and garmin:
        gap = garmin - anchor_vdot
        if gap >= 5:
            interpretation = (
                f"Garmin is {gap:.0f} VDOT above your race-anchored fitness — the "
                f"wrist-HR estimate is significantly more optimistic than what you've "
                f"actually run. Trust the anchor VDOT.")
        elif gap >= 2:
            interpretation = (
                f"Garmin reads {gap:.1f} VDOT above your anchor — modest gap (HR-strap "
                f"drift or course conditions). The anchor is the more reliable number.")
        elif gap <= -2:
            interpretation = (
                f"Anchor VDOT is {abs(gap):.1f} above Garmin's estimate — unusual; easy-"
                f"effort HR may be running high. Anchor is still primary.")
        else:
            interpretation = "Anchor and Garmin agree closely — confidence is high."
    if anchor_payload and anchor_payload.get("stale"):
        note = "Anchor is getting old — race a 5–10 km or run a threshold test to refresh it."
        interpretation = f"{interpretation} {note}" if interpretation else note

    return {
        "race": anchor_payload,   # template key kept stable
        "race_marathon": anchor_marathon,
        "garmin_vo2": garmin,
        "garmin_marathon": garmin_marathon,
        "interpretation": interpretation,
        "peak": None,
    }


def _calibration_history(conn):
    """Per-metric calibration history for the Profile tab.

    Returns a list of dicts per metric:
      {metric, label, rows, missing, threshold_days, is_dense, active}
    - `rows`: deduped (same date+value+method collapsed), oldest first.
      Each row carries value, date, days_ago, method, confidence, flags,
      classification (parsed from `notes` for drift_test rows: 'direct',
      'lower_bound', 'upper_bound'; None otherwise), is_active, stale.
    - `is_dense`: True when there are >= _DENSE_THRESHOLD distinct readings
      — the dashboard renders these as a scatter chart. Sparse metrics
      render as a stat card (no chart) since 1-2 dots aren't informative.
    - `active`: the active row (or None) lifted to the top level so the
      stat-card view doesn't need to scan rows.
    """
    import json as _json
    import re
    from fit.calibration import STALENESS_THRESHOLDS, get_active_calibration

    metric_labels = {
        "vdot": "VDOT (race-anchored)",
        "lthr": "LTHR (Lactate Threshold)",
        "max_hr": "MaxHR (Peak HR)",
        "aet": "AeT (Aerobic Threshold)",
        "vo2max": "VO2max (Garmin)",
        "weight": "Weight",
    }

    # One SELECT for all 5 metrics; group in Python.
    all_rows = conn.execute(
        "SELECT id, metric, value, method, confidence, date, "
        "source_activity_id, notes, flags FROM calibration ORDER BY metric, date ASC"
    ).fetchall()
    by_metric: dict[str, list[dict]] = {m: [] for m in metric_labels}
    for r in all_rows:
        if r["metric"] not in by_metric:
            continue
        d = dict(r)
        try:
            d["flags"] = _json.loads(d["flags"] or "[]")
        except (ValueError, TypeError):
            d["flags"] = []
        by_metric[r["metric"]].append(d)

    # Dedupe: collapse rows with identical (date, value, method) into one.
    # Keeps the LATEST (highest-id) representative so confidence/flags
    # reflect the most recent write — guards against the calibration table
    # accumulating dupes from re-imports.
    def _dedupe(rows: list[dict]) -> list[dict]:
        seen: dict[tuple, dict] = {}
        for r in rows:
            key = (r["date"], r["value"], r["method"])
            seen[key] = r  # later writes overwrite earlier ones
        return sorted(seen.values(), key=lambda r: r["date"])

    # Drift-test classification appears in the notes field as e.g.
    # "drift 6.84% (direct_estimate) from ..."
    classification_re = re.compile(r"\((direct_estimate|upper_bound|lower_bound)\)")

    today = date.today()
    out = []
    for metric, label in metric_labels.items():
        history = _dedupe(by_metric[metric])
        if not history:
            out.append({"metric": metric, "label": label, "rows": [],
                        "missing": True, "is_dense": False, "active": None})
            continue

        active = get_active_calibration(conn, metric)
        active_id = active["id"] if active else None
        threshold = STALENESS_THRESHOLDS.get(metric)
        threshold_days = threshold.days if threshold else None

        rendered = []
        for r in history:
            try:
                days_ago = (today - date.fromisoformat(r["date"])).days
            except (ValueError, TypeError):
                days_ago = None
            # Per-row staleness is only meaningful for the active row.
            # Historical rows are records, not states.
            is_active = r["id"] == active_id
            stale = (is_active and threshold_days is not None and days_ago is not None
                     and days_ago > threshold_days)
            classification = None
            if r.get("notes"):
                m = classification_re.search(r["notes"])
                if m:
                    classification = m.group(1).replace("_estimate", "")
            rendered.append({
                "value": r["value"], "date": r["date"], "days_ago": days_ago,
                "method": r["method"],
                "confidence": r["confidence"] or "medium",
                "flags": r["flags"],
                "source_activity_id": r.get("source_activity_id"),
                "notes": r.get("notes"),
                "classification": classification,
                "is_active": is_active,
                "stale": stale,
            })

        active_row = next((r for r in rendered if r["is_active"]), rendered[-1])
        out.append({
            "metric": metric, "label": label, "rows": rendered,
            "missing": False, "threshold_days": threshold_days,
            "is_dense": len(rendered) >= _DENSE_THRESHOLD,
            "active": active_row,
        })
    return out


# Severity levels are mainly defined by alerts.ALERT_SEVERITY; mirrored here
# for non-alert attention items (which don't go through the alert rule path).
_SEVERITY_FOR_CALIBRATION = {"lthr": "warning", "max_hr": "warning", "weight": "info",
                              "vo2max": "info", "aet": "info"}

# Stale-data rules: (source_name, min_days, severity, headline_fn, command, detail, source_fn).
# `headline_fn(days)` and `source_fn(days)` produce the user-visible text.
_DATA_HEALTH_STALE_RULES = [
    ("weight", 14, "warning",
     lambda d: f"Weight last logged {d}d ago",
     "fit import-health ~/Downloads/Export.zip",
     "Re-export from the Apple Health app on iPhone, then import.",
     lambda d: f"body_comp table: last weight row {d}d ago."),
    ("garmin_health", 0, "warning",
     lambda d: f"Garmin health {d}d behind",
     "fit sync",
     None,
     lambda d: f"data_health: last garmin_health row {d}d ago."),
    ("garmin_activities", 0, "warning",
     lambda d: f"Garmin activities {d}d behind",
     "fit sync",
     None,
     lambda d: f"data_health: last garmin_activities row {d}d ago."),
]


def _attention_items(conn):
    """Aggregate pending user actions for the Overview tab's Attention panel.

    Each item carries four user-visible fields:

      message  — short headline (imperative voice, what's wrong)
      command  — one copy-pasteable shell line (the most likely fix)
      detail   — context / alternative actions (rendered as a caption)
      source   — where the info came from (small, helps the user reason
                 about whether the prompt is genuinely actionable)

    Items dedupe by tag and sort critical → warning → info; the panel
    hides entirely when the list is empty.
    """
    from fit.data_health import check_data_sources
    from fit.calibration import get_calibration_status

    items: list[dict] = []
    seen: set[str] = set()

    def _add(*, severity, message, tag, command=None, detail=None, source=None):
        if tag in seen:
            return
        seen.add(tag)
        items.append({"severity": severity, "message": message, "tag": tag,
                      "command": command, "detail": detail, "source": source})

    # Calibration: missing LTHR is the only "missing → action" case worth nudging.
    # Stale calibrations dispatch through the same code path regardless of metric.
    for c in get_calibration_status(conn):
        if c["missing"] and c["metric"] == "lthr":
            _add(severity="warning",
                 message="Calibrate LTHR — anchors your training zones.",
                 tag="cal_missing_lthr",
                 command="fit calibrate lthr",
                 detail="Or wait for a 10K+ race; sync auto-extracts from the race result.",
                 source="No row in the calibration table for metric=lthr.")
        elif c["stale"] and not c["missing"]:
            days = (date.today() - date.fromisoformat(c["date"])).days if c.get("date") else None
            _add(severity=_SEVERITY_FOR_CALIBRATION.get(c["metric"], "info"),
                 message=f"{c['metric'].upper()} last calibrated {days}d ago",
                 tag=f"cal_stale_{c['metric']}",
                 command=f"fit calibrate {c['metric']}",
                 detail=c.get("retest_prompt"),
                 source=f"calibration row dated {c['date']} · staleness threshold {c.get('threshold_days')}d.")

    # Calibration suggestions awaiting confirm — anchors never auto-flip, so a
    # policy suggestion that differs from the confirmed value is surfaced here.
    try:
        from fit.calibration import evaluate_suggestions
        for p in evaluate_suggestions(conn):
            _add(severity="info",
                 message=f"{p['metric'].upper()} suggestion: {p['value']:g} (active {p['active']})",
                 tag=f"cal_suggest_{p['metric']}",
                 command=f"fit calibrate {p['metric']}",
                 detail=f"Accept to update the anchor, or dismiss. {p.get('reason') or ''}".strip(),
                 source="get_calibration_anchor suggestion differs from the confirmed value.")
    except Exception as e:
        logger.debug("calibration suggestion attention item skipped: %s", e)

    # Data freshness — table-driven dispatch.
    sources_by_name = {s["source"]: s for s in check_data_sources(conn)}
    for src in sources_by_name.values():
        if src["status"] == "missing":
            _add(severity="info",
                 message=f"{src['source'].replace('_', ' ').title()} not flowing",
                 tag=f"missing_{src['source']}",
                 detail=src.get("instruction") or f"Enable {src['source']}",
                 source=f"data_health: 0 readings for {src['source']} in the last 14 days.")
    for name, min_days, sev, headline, cmd, detail, source_fn in _DATA_HEALTH_STALE_RULES:
        src = sources_by_name.get(name)
        if not src or src["status"] != "stale":
            continue
        days = src.get("days_ago")
        if days is None or days < min_days:
            continue
        _add(severity=sev, message=headline(days),
             tag=f"stale_{name}", command=cmd, detail=detail, source=source_fn(days))

    # No fitness anchor at all → VDOT falls back to Garmin alone; prompt a time trial.
    # We deliberately do NOT flag "Garmin reads higher than your anchor": Garmin's wrist
    # VO2max is optimistic by ~5-10 by design, so that gap is structural, not actionable
    # (and the Physiology tile already shows Garmin as a labeled reference). Only the
    # genuine "no performance data to anchor on" case is worth a nudge.
    try:
        from fit.fitness import get_fitness_anchors

        anchors = get_fitness_anchors(conn, days=365)
        garmin_row = conn.execute(
            "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL "
            "ORDER BY date DESC LIMIT 1"
        ).fetchone()
        garmin_vo2 = (float(garmin_row["vo2max"])
                      if garmin_row and garmin_row["vo2max"] else None)

        if not anchors and garmin_vo2:
            _add(
                severity="info",
                message="No fitness anchor — VDOT relies on Garmin alone",
                tag="vdot_no_anchor",
                detail=(
                    "No 5–25km running activity in the last year meets the criteria "
                    "(avg HR ≥ LTHR, consistent pacing). Schedule a 5K or 10K time "
                    "trial at race effort to anchor your VDOT. Until then, marathon "
                    "prediction relies on Garmin's wrist-HR estimate alone."
                ),
                source="fit.fitness.get_fitness_anchors returned 0 qualifying activities.",
            )
    except Exception as e:
        logger.debug("vdot_no_anchor check failed: %s", e)

    # Completed races missing an official result_time. The watch time
    # (garmin_time) covers predictions in the meantime, but the official chip
    # time is more accurate for race-VDOT — flag so the athlete enters it.
    try:
        missing_times = conn.execute("""
            SELECT id, date, name FROM race_calendar
            WHERE status = 'completed' AND activity_id IS NOT NULL
              AND (result_time IS NULL OR result_time = '')
            ORDER BY date DESC
        """).fetchall()
        if missing_times:
            latest = missing_times[0]
            extra = f" (+{len(missing_times) - 1} more)" if len(missing_times) > 1 else ""
            _add(
                severity="info",
                message=f"{len(missing_times)} race(s) missing an official time",
                tag="race_missing_result_time",
                command=f"fit races set-result {latest['id']} <H:MM:SS>",
                detail=(
                    f"Most recent: {latest['name']} ({latest['date']}){extra}. "
                    "Race predictions currently fall back to the watch-recorded time; "
                    "enter the official chip time for sharper race-VDOT."
                ),
                source="race_calendar rows: status=completed, matched activity, result_time IS NULL.",
            )
    except Exception as e:
        logger.debug("race_missing_result_time check failed: %s", e)

    # Option A — a recent half-marathon implies an LTHR materially different
    # from the (human-confirmed) active value. Suggest confirming; never
    # auto-apply. Gated to HM+ distance: it's the cleanest LTHR signal and
    # avoids non-max efforts (e.g. a steady 12km logged as a race) dragging
    # the suggestion down.
    try:
        from fit.calibration import (get_active_calibration as _gac,
                                      extract_lthr_from_race, CalibrationMethod, TrustTier)
        active_lthr = _gac(conn, "lthr")
        # A device-measured LTHR (Garmin auto-detected LT) is the trusted anchor —
        # it outranks any race-derived estimate (precedence: confirmed > device >
        # policy), so a race-implied LTHR nudge is noise against it. Skip when the
        # active value is device-sourced; it re-enables if the device stops feeding it.
        if active_lthr and CalibrationMethod.resolve(active_lthr.get("method")).trust_tier == TrustTier.DEVICE:
            active_lthr = None
        hm = conn.execute(f"""
            SELECT a.date, a.name, a.distance_km, a.avg_hr
            FROM race_calendar rc JOIN activities a ON a.id = rc.activity_id
            WHERE rc.status = 'completed' AND a.type IN {RUNNING_TYPES_SQL}
              AND a.distance_km >= 20 AND a.avg_hr IS NOT NULL
            ORDER BY a.date DESC LIMIT 1
        """).fetchone()
        if active_lthr and hm:
            est = extract_lthr_from_race({
                "type": "running", "run_type": "race",
                "distance_km": hm["distance_km"], "avg_hr": hm["avg_hr"],
            })
            if est and abs(est - active_lthr["value"]) >= 3:
                age = None
                if active_lthr.get("date"):
                    age = (date.today() - date.fromisoformat(active_lthr["date"])).days
                _add(
                    severity="info",
                    message=f"Recent HM suggests LTHR ≈{est} (calibrated {active_lthr['value']:.0f})",
                    tag="lthr_suggestion",
                    command=f"fit calibrate lthr {est}",
                    detail=(
                        f"{hm['name']} ({hm['date']}, {hm['distance_km']:g}km @ avg HR "
                        f"{hm['avg_hr']}) implies LTHR ≈{est}, vs your calibrated "
                        f"{active_lthr['value']:.0f}"
                        + (f" from {age}d ago" if age else "")
                        + ". LTHR is human-confirmed — adopting it shifts every zone, "
                        "so run the command to accept, or do a 30-min time trial."
                    ),
                    source="extract_lthr_from_race on the most recent ≥20km race vs the active LTHR.",
                )
    except Exception as e:
        logger.debug("lthr_suggestion check failed: %s", e)

    # Coaching review staleness.
    try:
        db_path = conn.execute("PRAGMA database_list").fetchone()[2]
        coaching_path = Path(db_path).parent / "reports" / "coaching.json"
        if coaching_path.exists():
            data = json.loads(coaching_path.read_text())
            rd = data.get("report_date")
            if rd:
                age = (date.today() - date.fromisoformat(rd)).days
                if age > 7:
                    _add(severity="info",
                         message=f"Coaching review is {age}d old",
                         tag="coaching_stale",
                         command="fit coach",
                         detail="Run `fit coach` to refresh insights, then `fit report`.",
                         source=f"coaching.json: report_date {rd}.")
    except Exception:
        pass  # missing/malformed coaching.json shouldn't block the panel

    sev_order = {"critical": 0, "warning": 1, "info": 2}
    items.sort(key=lambda i: sev_order.get(i["severity"], 99))
    return items


def _prediction_confidence(conn):
    """Race-prediction confidence — fresh anchors give a sharper forecast.

    Maps reason-count → level: 0 = high, 1 = medium, 2+ = low. Same
    semantics as the prior branchy version with consistent reason wording.
    """
    from fit.calibration import is_stale as cal_is_stale, get_active_calibration

    lthr_stale = get_active_calibration(conn, "lthr") is None or cal_is_stale(conn, "lthr")
    vo2_stale = get_active_calibration(conn, "vo2max") is None or cal_is_stale(conn, "vo2max")
    race_count = conn.execute(
        "SELECT COUNT(*) FROM race_calendar WHERE result_time IS NOT NULL "
        "AND date >= date('now', '-365 days')"
    ).fetchone()[0]

    reasons = []
    if lthr_stale:
        reasons.append("LTHR stale")
    if vo2_stale:
        reasons.append("VO2max stale")
    if race_count == 0:
        reasons.append("no recent race data")
    elif race_count == 1:
        reasons.append("only 1 recent race")

    level = "high" if not reasons else "medium" if len(reasons) == 1 else "low"
    return {"level": level, "reason": ", ".join(reasons)}


def _vdot_entry(conn):
    """The aerobic anchor tile = the performance-anchored VDOT (`_effective_vdot` —
    the same figure the Aerobic dimension and pace zones read), NOT Garmin's wrist
    VO2max, which reads ~5-10 points high and is shown only as a diagnostic reference.
    SSOT: the card must lead with the number everything downstream derives from."""
    from fit.fitness import _effective_vdot, _get_garmin_vo2max

    ev = _effective_vdot(conn)
    garmin = _get_garmin_vo2max(conn)
    if ev is None:
        return {
            "key": "vdot", "label": "VDOT", "unit": "", "value": None,
            "description": "Performance-anchored aerobic index (Daniels) — runs your pace zones.",
            "date": None, "days_ago": None, "trend": None, "is_primary": False,
            "reference": None, "reference_title": None,
            "missing_action": {
                "message": "Confirm a race-effort VDOT to anchor your aerobic capacity.",
                "link_anchor": "prof-vo2max",
            },
        }
    return {
        "key": "vdot", "label": "VDOT", "unit": "", "value": round(ev),
        "description": "Performance-anchored aerobic index (Daniels) — runs your pace zones.",
        "date": None, "days_ago": None, "trend": None, "is_primary": False,
        "reference": f"Garmin VO2max {round(garmin)}" if garmin is not None else None,
        "reference_title": ("Garmin's wrist VO2max reads ~5-10 points high; the race-anchored "
                            "VDOT is what drives your pace zones and predictions."),
        "missing_action": None,
    }


def _physiology(conn):
    """Build the "Your Physiology" card data for the Overview tab.

    Returns a list of 4 anchor dicts (LTHR, MaxHR, AeT, VDOT), each with:
      - key: short identifier
      - label: display name
      - value: current value or None
      - unit: 'bpm' / '' etc.
      - description: one-line concept blurb
      - date: ISO date of last calibration (or None)
      - days_ago: int (or None)
      - trend: 'stable' | '+N bpm in M weeks' | None
      - is_primary: bool (anchor that drives current zones)
      - missing_action: dict {message, link_anchor} when not yet calibrated

    Order: primary first, then by physiological hierarchy (LTHR, MaxHR, AeT,
    VDOT). When AeT is implemented (aet-anchored-zones) it should slide
    into the primary slot above LTHR.
    """
    from fit.calibration import get_active_calibration
    from fit.config import get_config

    config = get_config()
    zone_model = config.get("profile", {}).get("zone_model")
    today = date.today()

    def _entry(metric, label, unit, desc, missing_msg=None, missing_link=None):
        cal = get_active_calibration(conn, metric)
        if not cal:
            return {
                "key": metric, "label": label, "unit": unit,
                "value": None, "description": desc,
                "date": None, "days_ago": None, "trend": None,
                "is_primary": False, "reference": None, "reference_title": None,
                "missing_action": {
                    "message": missing_msg or f"Calibrate via `fit calibrate {metric} <value>`",
                    "link_anchor": missing_link,
                } if missing_msg else None,
            }
        cal_date = date.fromisoformat(cal["date"]) if cal.get("date") else None
        days_ago = (today - cal_date).days if cal_date else None

        # Trend computation: compare current value to prior calibration rows
        # for the same metric over the last ~180 days. "Stable" if all
        # readings within ±2 bpm of current; otherwise show signed delta.
        prior = conn.execute("""
            SELECT value, date FROM calibration
            WHERE metric = ? AND date >= date('now', '-180 days') AND active = 0
            ORDER BY date DESC LIMIT 5
        """, (metric,)).fetchall()
        trend = None
        if prior:
            current_val = cal["value"]
            tol = 2.0 if metric in ("max_hr", "lthr", "aet") else 0.5
            within_tol = all(abs(current_val - p["value"]) <= tol for p in prior)
            if within_tol:
                trend = "stable"
            else:
                # signed delta vs the oldest reading in window
                oldest = prior[-1]
                delta = current_val - oldest["value"]
                older_date = date.fromisoformat(oldest["date"])
                weeks = max(1, (cal_date - older_date).days // 7) if cal_date else 1
                sign = "+" if delta >= 0 else ""
                trend = f"{sign}{delta:.0f} {unit or 'bpm'} in {weeks}w"

        return {
            "key": metric, "label": label, "unit": unit,
            "value": cal["value"], "description": desc,
            "date": cal["date"], "days_ago": days_ago,
            "trend": trend, "is_primary": False,
            "reference": None, "reference_title": None,
            "missing_action": None,
        }

    entries = [
        _entry(
            "lthr", "LTHR", "bpm",
            "Lactate threshold. Sustainable hard-effort ceiling — anchors your training zones.",
        ),
        _entry(
            "max_hr", "MaxHR", "bpm",
            "Peak HR observed. Hardware ceiling. Auto-updates from race data.",
        ),
        _entry(
            "aet", "AeT", "bpm",
            "Aerobic threshold. The boundary that matters most for marathon endurance.",
            missing_msg="Run a 15+ km steady-pace effort to derive AeT from HR drift.",
            missing_link="aet-instructions",
        ),
        _vdot_entry(conn),
    ]

    # Mark primary anchor per the active zone model. The default (`lthr`) puts
    # LTHR first; an explicit zone_model=max_hr override moves the primary tag.
    primary_key = "max_hr" if zone_model == "max_hr" else "lthr"
    for e in entries:
        if e["key"] == primary_key and e["value"] is not None:
            e["is_primary"] = True
            break

    return entries


def _pace_zones(conn):
    """Daniels training paces (E/M/T/I/R) derived from active VDOT calibration.

    Each pace returned as a min:sec/km string range (e.g. "5:24" or
    "6:09-6:24" for the easy range). Returns dict with `available` flag and,
    when False, a hint pointing at the calibration that's missing.
    """
    from fit.analysis import compute_daniels_paces
    from fit.calibration import get_calibration_anchor

    # Paces come from the SINGLE standardized VDOT anchor every consumer reads
    # (get_calibration_anchor) — the human-confirmed sticky value, or the
    # windowed-max policy estimate when none is confirmed. This is the same
    # number the VDOT Trend section and the forecast use, so the dashboard tells
    # one consistent story. (Daniels off Garmin's optimistic VO2max would
    # prescribe paces far too fast — see the anchor's reference-method exclusion.)
    anchor = get_calibration_anchor(conn, "vdot")
    if anchor is None:
        return {"available": False, "missing": "No qualifying effort yet — run a 5–10 km at ≥ LTHR to anchor your paces."}
    vdot = anchor.value
    vdot_source = "garmin" if anchor.method == "device_vo2max" else "anchor"

    paces = compute_daniels_paces(vo2max=vdot)
    if not paces:
        return {"available": False, "missing": "VDOT value out of derivation range."}

    def _fmt(s):
        m, sec = divmod(int(round(s)), 60)
        return f"{m}:{sec:02d}"

    def _row(name, lo, hi):
        return {"lo": _fmt(lo), "hi": _fmt(hi), "range": _fmt(lo) if lo == hi else f"{_fmt(lo)}-{_fmt(hi)}"}

    return {
        "available": True,
        "vo2max": vdot,
        "vdot_source": vdot_source,
        "rows": [
            {"key": "E", "label": "Easy", "desc": "Conversational. The bulk of weekly volume.", **_row("E", paces["E"]["lo"], paces["E"]["hi"])},
            {"key": "M", "label": "Marathon", "desc": "Goal race pace. Sustainable for ~3-4 h.", **_row("M", paces["M"]["lo"], paces["M"]["hi"])},
            {"key": "T", "label": "Threshold", "desc": "~1-hour all-out (tempo). At LTHR.", **_row("T", paces["T"]["lo"], paces["T"]["hi"])},
            {"key": "I", "label": "Interval", "desc": "3-5 min at vVO2max. Critical-power zone.", **_row("I", paces["I"]["lo"], paces["I"]["hi"])},
            {"key": "R", "label": "Repetition", "desc": "30s-2min reps. Above vVO2max, neuromuscular.", **_row("R", paces["R"]["lo"], paces["R"]["hi"])},
        ],
    }


def _concepts():
    """Glossary entries for the Overview tab's collapsible Concepts section.

    Static text — values stay generic so the glossary doesn't grow stale.
    Per-metric live values still appear in the chart-level `def-toggle`
    popovers (contextual quick-reference).
    """
    return [
        {"term": "MaxHR", "body": "Peak observed heart rate. Hardware ceiling. Drops ~1 bpm/year with age."},
        {"term": "LTHR", "body": "Lactate threshold HR. The sustainable hard-effort ceiling, derivable from a 30-min time trial or any 10K+ race result."},
        {"term": "AeT", "body": "Aerobic threshold. Upper edge of fat-oxidation territory. The Z2 ceiling for marathon base building. Measured via HR-drift on a steady-pace long run."},
        {"term": "VO2max", "body": "Maximum oxygen uptake (ml/kg/min). Aerobic capacity ceiling. Garmin estimates from outdoor running data; race results give a more reliable VDOT."},
        {"term": "VDOT", "body": "Daniels' running-equivalent VO2max. Translates race results to predicted times at any distance."},
        {"term": "ACWR", "body": "Acute:Chronic Workload Ratio. This week's load / 4-week avg. 0.8–1.3 safe, >1.5 injury-risk spike."},
        {"term": "Monotony", "body": "Foster's mean(load) / stdev(load). >2.0 = same effort every day, recovery-starved."},
        {"term": "Strain", "body": "weekly_load × monotony. Combines volume and variation into one fatigue number."},
        {"term": "Cardiac drift", "body": "HR rising at constant pace. Caused by glycogen depletion, core temp, plasma loss. Drift onset km is a resilience signal."},
        {"term": "Z2 ceiling", "body": "Upper bound of true easy aerobic. Under %LTHR (Friel): 89% × LTHR. Under %MaxHR: 70% × MaxHR."},
        {"term": "Effort class", "body": "5-level classification (Recovery/Easy/Moderate/Hard/Very Hard) derived from the primary HR zone."},
        {"term": "Run type", "body": "Auto-classified per activity: easy / long / tempo / intervals / progression / recovery / race. Race tag comes from race_calendar matching."},
    ]


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
        "respiration": "Breaths per minute. The <strong>sleep average</strong> (solid line) is the illness/overtraining early-warning signal: <strong style='color:var(--caution)'>≥2 brpm above your personal baseline for 2+ nights</strong> fires an alert — it typically moves 1-2 days before you feel sick. The waking average (dashed) is reference. The shaded band is your normal zone (28-day baseline median + threshold); trends against your own baseline matter, not absolute values.",
        "weight": f"Current: {weight_val} kg. Each kg lost saves ~2-3 sec/km at the same effort. Over 42.2 km, 3 kg = ~7-10 min faster. Target weight through training volume (not dieting).",
        "zones": "HR zones by training TIME (minutes per week), not run count. Compared to your active training phase targets. Blue = Z1+Z2 (easy), amber = Z3 (moderate), orange = Z4+Z5 (hard). Phase 1 targets ~90% easy.",
        "volume": "Total running km per week. The darker segment shows the longest single run. For marathon training: long run should build gradually to 30-32 km, weekly volume to 50-60 km at peak.",
        "cadence": f"Your 30d avg cadence: {avg_cadence_val} spm. Below 165 often indicates overstriding. Target: 170-180. Tends to improve with fatigue resilience and form work.",
        "cardiac_drift": "<strong>Cardiac drift</strong> = HR rising while pace stays constant, caused by glycogen depletion, core temp rise, and plasma volume loss. <strong>Top chart:</strong> per-km pace + HR for steady aerobic runs (≥8 km — tempo/intervals/progression/race excluded, since they decouple early by design), averaged across recent long runs (thin = individual runs, thick = average); the x-axis is real cumulative km. <strong>Drift onset</strong> = the first km where the HR : grade-adjusted-pace ratio exceeds the first-half baseline by 5%. <strong>Bottom chart:</strong> drift onset per run over time. Onset is a <em>one-sided lower bound</em> — a no-drift run (▲) only shows durability is <em>at least</em> that far (we can't see past the run); an observed onset (●) is where HR decoupled, and a short/hot/tired run only pushes it earlier. The dashed line + amber band are the resilience estimate: a recency- and length-weighted best-demonstrated onset that shrinks toward a prior when data is thin or stale, with a <em>Bayesian-bootstrap 90% interval</em> (wide when few runs feed it; the upper bound also carries the unobserved km past your longest run). Higher is better; onset after km 15 (green) = strong aerobic base.",
        "race_prediction": "The race-day forecast from the Bayesian durability model: a <strong>median</strong> finish time, a <strong>90% interval</strong>, and <strong>P(goal)</strong>. <strong>Extrapolation penalty</strong>: the interval widens the further the race is past your longest run — honesty about unproven distance. <strong>Maximal-HR input</strong>: it assumes a race run at your duration-appropriate maximal effort (LTHR-relative), not an easy pace — and the interval also carries how unsure we are of that assumed effort (the fade slope β and threshold-duration T₀), which grows the further the race is from your threshold duration. <strong>Interval ≠ race-day spread</strong>: the band is parameter uncertainty (how well the model knows your fitness and effort), not the variance of race-day outcomes. <strong>P(goal)</strong> is a fitness-sufficiency ceiling — the probability your fitness is enough for the goal, not a bet on the day. Degrades to the calibrated-VDOT anchor estimate when the model isn't fit.",
        "acwr": f"Acute:Chronic Workload Ratio. Current: {acwr_val}. This week's load ÷ avg of previous 4 weeks. <strong style='color:var(--safe)'>0.8-1.3 = safe</strong>, <strong style='color:var(--caution)'>1.3-1.5 = caution</strong>, <strong style='color:var(--danger)'>> 1.5 = injury risk (spike)</strong>, < 0.6 = detraining. Critical for comeback training.",
        "pacecv": "Coefficient of Variation of pace within a run — how even your pacing is. Lower = more consistent. <strong style='color:var(--safe)'>< 5% = very even</strong>, <strong style='color:var(--caution)'>5-10% = moderate variation</strong>, <strong style='color:var(--danger)'>> 10% = erratic pacing</strong>. Even pacing is a key predictor of marathon success. Interval sessions naturally have higher CV.",
        "effort_gap": "Garmin Training Effect (TE) measures physiological load from sensor data. Your RPE (logged in Garmin Connect) is your subjective effort score (scaled to match). When RPE consistently exceeds TE, you're accumulating fatigue the watch can't see — consider extra recovery. When TE exceeds RPE, you're adapting well.",
    }



def _coaching(conn):
    db_path = conn.execute("PRAGMA database_list").fetchone()[2]
    coaching_path = Path(db_path).parent / "reports" / "coaching.json"
    if not coaching_path.exists():
        return None

    from datetime import timedelta
    data = json.loads(coaching_path.read_text())
    # Stale = coaching notes older than 7 days (weekly cadence, not sync-based)
    report_date_str = data.get("report_date", "")
    if report_date_str:
        try:
            report_dt = date.fromisoformat(report_date_str)
            stale = report_dt < (date.today() - timedelta(days=7))
        except ValueError:
            stale = True
    else:
        stale = True

    # Per-type icons. Background, border, and title color all come from the
    # CSS .insight-<type> classes in design_system.css — the same source of
    # truth used by the Overview tab's compact card, so colors stay consistent
    # across tabs.
    icons = {
        "critical": "🚨",
        "warning": "⚠️",
        "positive": "✅",
        "info": "📊",
        "target": "🎯",
    }
    insights = [
        {
            "type": i.get("type", "info"),
            "icon": icons.get(i.get("type", "info"), icons["info"]),
            "title": i.get("title", ""),
            "body": i.get("body", ""),
        }
        for i in data.get("insights", [])
    ]

    # Days since the coaching pipeline last ran — surfaced as a stale badge.
    age_days = None
    if report_date_str:
        try:
            age_days = (date.today() - date.fromisoformat(report_date_str)).days
        except ValueError:
            pass

    return {
        "generated_at": data.get("generated_at", ""),
        "report_date": report_date_str,
        "stale": stale,
        "age_days": age_days,
        "insights": insights,
    }


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
                from fit.analysis import predict_race_time

                def _parse_time(t):
                    parts = t.split(":")
                    if len(parts) == 3:
                        return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    elif len(parts) == 2:
                        return int(parts[0]) * 60 + int(parts[1])
                    return 0

                def _fmt_time(s):
                    return f"{s // 3600}:{(s % 3600) // 60:02d}"

                # Single source of truth for the headline. Prefer the durability-model
                # MEDIAN (so the hero stat matches the model block below — no two
                # conflicting numbers). Else the calibrated-VDOT anchor + method-spread
                # margin (conservative). Never the retired table.
                target_km = race.get("distance_km") or 42.195
                target_secs = _parse_time(result["target_time"]) if result.get("target_time") else None

                center_secs = None
                margin_secs = 0
                try:
                    from fit.marathon.predict import forecast as _model_forecast
                    _fc = _model_forecast(conn, goal_seconds=target_secs)  # cached shared load
                    if _fc:
                        center_secs = _fc["median"]          # margin 0 → hero == model block
                        result["confidence_level"] = "model"
                except Exception:
                    pass

                if center_secs is None:
                    from fit.fitness import anchor_race_time
                    center_secs = anchor_race_time(conn, target_km)
                    vo2 = conn.execute(
                        "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
                    ).fetchone()
                    races_db = conn.execute("""
                        SELECT distance_km, result_time FROM race_calendar
                        WHERE status = 'completed' AND result_time IS NOT NULL
                        ORDER BY date DESC LIMIT 5
                    """).fetchall()
                    race_data = [
                        {"distance_km": r["distance_km"], "time_seconds": _parse_time(r["result_time"])}
                        for r in races_db if r["distance_km"] and r["result_time"]
                    ]
                    preds = predict_race_time(conn=conn, races=race_data,
                                              vo2max=vo2["vo2max"] if vo2 else None)
                    all_secs = []
                    if preds.get("riegel"):
                        all_secs.extend(p["predicted_seconds"] for p in preds["riegel"])
                    if preds.get("vdot") and preds["vdot"].get("predicted_seconds"):
                        all_secs.append(preds["vdot"]["predicted_seconds"])
                    if len(all_secs) >= 2:
                        margin_secs = (max(all_secs) - min(all_secs)) / 2
                    else:
                        margin_secs = preds.get("confidence", {}).get("margin_seconds", 480)
                    result["confidence_level"] = preds.get("confidence", {}).get("level", "low")

                if center_secs:
                    conservative_secs = center_secs + margin_secs
                    result["prediction_mid"] = _fmt_time(round(conservative_secs))
                    if target_secs and target_secs > 0:
                        result["gap_minutes"] = round((conservative_secs - target_secs) / 60)

                # Trend badge: forecast change over the last ~8 weeks, from the model
                # (first vs last weekly median). No table — no badge if the model isn't fit.
                from datetime import date as _date, timedelta as _td
                wk_dates = [(_date.today() - _td(days=7 * i)).isoformat() for i in range(8, -1, -1)]
                mt = _model_week_trend(conn, wk_dates)
                if mt:
                    vals = [mt[d][0] for d in wk_dates if d in mt]
                    if len(vals) >= 2:
                        delta_min = round((vals[-1] - vals[0]) / 60)
                        if delta_min != 0:
                            result["trend_badge"] = f"{'+' if delta_min > 0 else ''}{delta_min} min / 8 wk"
            except Exception:
                pass  # prediction enrichment is best-effort

        return result
    except Exception:
        return None


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


# ── Helpers ──

def _subtitle(conn):
    h = conn.execute("SELECT COUNT(*) FROM daily_health").fetchone()[0]
    a = conn.execute("SELECT COUNT(*) FROM activities").fetchone()[0]
    # Training age: weeks since first activity
    first = conn.execute("SELECT MIN(date) FROM activities").fetchone()[0]
    weeks = ""
    if first:
        days_tracking = (date.today() - date.fromisoformat(first)).days
        weeks = f" · week {days_tracking // 7} of tracking"
    return f"{h}d · {a} activities{weeks}"





def _body_summary(conn):
    """One-line narrative for the Body tab."""
    try:
        return generate_body_summary(conn)
    except Exception:
        return None


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


def _weight_target(conn):
    """The active weight goal's target_value (kg), or None — the single canonical query.

    `goals` has no `metric` column; a weight goal is a `type='metric'` row whose name
    contains "weight" (the only weight-goal shape the app inserts). The older
    `WHERE metric='weight'` queries silently returned nothing (swallowed by try/except).
    """
    row = conn.execute(
        "SELECT target_value FROM goals WHERE type = 'metric' AND name LIKE '%eight%' "
        "AND active = 1 LIMIT 1"
    ).fetchone()
    return row["target_value"] if row else None


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
        target = _weight_target(conn)
        return {
            "current": round(current, 1),
            "target": target,
            "change": change,
            "change_span": change_span,
            "history": history,
        }
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


def _next_workouts_base(conn, limit=3):
    """Shared loader for upcoming planned workouts — one place for the query, the
    Garmin/Runna name-cleaning, and the date labels. `_next_workouts` (Overview) uses
    these fields directly; `_next_workouts_enriched` (Training) decorates them with the
    expected zone + HR range. Each row carries the raw `target_zone` for the latter."""
    import re
    try:
        rows = conn.execute("""
            SELECT date, workout_name, workout_type, target_distance_km, target_zone
            FROM planned_workouts
            WHERE date >= date('now') AND status = 'active'
            ORDER BY date LIMIT ?
        """, (limit,)).fetchall()
    except Exception:
        return []
    today = date.today()
    out = []
    for r in rows:
        d = date.fromisoformat(r["date"])
        name = r["workout_name"] or r["workout_type"] or "Run"
        prefix_match = re.match(r'^(?:.*?W\s*\d+\s*\w+\.\s*)', name)  # "Berlin - W 1 So. " / "W 1 Fr. "
        if prefix_match:
            name = name[prefix_match.end():]
        name = re.sub(r'\s*\(\d+[,.]?\d*\s*km\)\s*$', '', name)       # redundant "(7,5 km)" suffix
        if len(name) > 40:
            name = name[:37].rsplit(' ', 1)[0] + "..."
        out.append({
            "name": name,
            "type": r["workout_type"] or "easy",
            "distance_km": r["target_distance_km"] or "?",
            "date_label": d.strftime("%a %b %-d"),
            "days": max(0, (d - today).days),
            "target_zone": r["target_zone"],
        })
    return out


def _next_workouts(conn):
    """Next 3 planned workouts for the Overview tab (no HR enrichment)."""
    out = _next_workouts_base(conn)
    for w in out:
        w.pop("target_zone", None)
    return out


def _overview_objectives(conn):
    """Objectives summary for Overview tab — always from weekly_agg, not derived_objectives."""
    try:
        # Volume / long-run / Z2 come from the rolling 7-day window — the single
        # source shared with the Training tab, CLI status and coaching (CLAUDE.md:
        # "Rolling 7-day window, not ISO weeks"). Only the streak stays ISO-week.
        from fit.analysis import compute_rolling_week
        latest = conn.execute(
            "SELECT consecutive_weeks_3plus FROM weekly_agg ORDER BY week DESC LIMIT 1"
        ).fetchone()
        if not latest:
            return None
        rolling = compute_rolling_week(conn)

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

        vol = rolling.get("run_km") or 0
        long_r = rolling.get("longest_run_km") or 0
        streak = latest["consecutive_weeks_3plus"] or 0

        # Z2 compliance from the same rolling 7-day window (SSOT with Training/coaching).
        z2 = round(rolling["z12_pct"]) if rolling.get("z12_pct") is not None else 0

        vol_pct = _pct(vol, targets["weekly_volume"])
        long_pct = _pct(long_r, targets["long_run"])
        z2_pct = _pct(z2, targets["z2_time"])
        streak_pct = _pct(streak, targets["consistency"])

        return [
            {"label": "Weekly Volume", "value": f"{vol:.0f}", "sub": f"of {targets['weekly_volume']:.0f} km" if targets["weekly_volume"] else "km",
             "pct": vol_pct, "color": _color(vol_pct), "history": history.get("weekly_volume", []), "spark_id": "spark-obj-vol"},
            {"label": "Long Run", "value": f"{long_r:.0f}", "sub": f"of {targets['long_run']:.0f} km" if targets["long_run"] else "km",
             "pct": long_pct, "color": _color(long_pct), "history": history.get("long_run", []), "spark_id": "spark-obj-long"},
            {"label": "Z2 Time", "value": f"{z2:.0f}%", "sub": f"target {targets['z2_time']:.0f}% · 7-day",
             "pct": z2_pct, "color": _color(z2_pct), "history": history.get("z2_time", []), "spark_id": "spark-obj-z2"},
            {"label": "Consistency", "value": f"{streak:.0f}", "sub": f"of {targets['consistency']:.0f} wks",
             "pct": streak_pct, "color": _color(streak_pct), "history": history.get("consistency", []), "spark_id": "spark-obj-streak"},
        ]
    except Exception:
        return None


# Status grammar shared by the Overview hub strip (icon + colour; never colour alone).
_HUB_STATUS_ICON = {"safe": "✓", "caution": "!", "danger": "✗", "neutral": "·"}
_HUB_SEV = {"danger": 2, "caution": 1, "safe": 0, "neutral": -1}
# Limiter lever per domain: (tab, section anchor, concrete lever phrasing).
_HUB_LEVER = {
    "Fitness": ("training", "train-objectives", "build weekly volume toward the phase target"),
    "Recovery": ("readiness", "readiness-acwr", "ease back — your load is spiking; add recovery"),
    "Physiology": ("profile", "prof-vo2max", "sharpen race-pace work to close the VDOT gap"),
}


# Default VDOT-point cutoffs (the values agreed for the Physiology card); overridable.
HUB_VDOT_WATCH, HUB_VDOT_OFF = 1.0, 3.0


def _hub_volume_status(vol, km_min, km_max):
    """Weekly volume vs the active phase's [min, max] km range → (status, gap-fraction). Only
    UNDER the min is the goal-limiting case (not enough training to build fitness): caution, or
    danger past a full range-width under. At or ABOVE the min the volume need is met → safe — the
    overload risk of running ABOVE the max is a load-spike signal carried by the Recovery card
    (ACWR), NOT a Fitness 'build more volume' limiter (direction-aware, mirroring _hub_acwr_status:
    the Fitness lever only ever says 'build', so an over-volume week must not select it)."""
    if not vol or km_min is None or km_max is None:
        return "neutral", 0.0
    if vol >= km_min:
        return "safe", 0.0
    under = km_min - vol
    width = max(km_max - km_min, 1.0)
    return ("danger" if under > width else "caution"), (under / km_min if km_min else 0.0)


def _hub_vdot_status(eff, req, watch=HUB_VDOT_WATCH, off=HUB_VDOT_OFF):
    """Effective VDOT vs goal-required → (status, gap-fraction). `watch`/`off` are the agreed
    VDOT-point cutoffs (≤watch on-track · watch–off watch · >off off-track), passed in."""
    if eff is None or req is None or not req:
        return "neutral", 0.0
    d = req - eff
    return ("safe" if d <= watch else "caution" if d <= off else "danger"), max(0.0, d) / req


def _hub_acwr_status(acwr, safe_range, danger_hi):
    """ACWR for the Recovery card = load-**spike** (overload/injury) risk only. In or *below*
    the safe band → safe: a low ACWR is freshness, not a recovery deficit — the under-training
    it implies surfaces on the Fitness card (volume), so it isn't double-flagged here (that was
    the backwards 'ease back' on a low ACWR). Above the band → caution; above the config danger
    threshold → danger. Bands come from config (`acwr_safe_range`, `acwr_danger_threshold`)."""
    if acwr is None or not safe_range:
        return "neutral", 0.0
    lo, hi = safe_range
    if acwr <= hi:                                   # in band or below → recovery is fine
        return "safe", 0.0
    status = "danger" if (danger_hi and acwr > danger_hi) else "caution"
    return status, (acwr - hi) / max(hi - lo, 0.01)


def _hub_pick_limiter(cards):
    """The single highlighted limiter: worst status (danger>caution) among the gap-bearing
    domains, tie-broken by the larger gap. None when nothing is below target. Every below-target
    domain still shows in the strip — this is only the highlight."""
    cand = [c for c in cards if c["label"] in _HUB_LEVER and c["status"] in ("caution", "danger")]
    if not cand:
        return None
    top = max(cand, key=lambda c: (_HUB_SEV[c["status"]], c["gap"]))
    tab, anchor, lever = _HUB_LEVER[top["label"]]
    return {"label": top["label"], "lever": lever, "status": top["status"], "tab": tab, "anchor": anchor}


def _hub_next_action(attention, limiter):
    """The single next action by precedence — **safety > consistency/performance**: a critical
    (safety) attention item wins; otherwise the limiter's lever is the headline action; a
    non-critical attention item (e.g. a stale-calibration nudge) does NOT outrank the limiter
    — it only fills in when there's no limiter."""
    crit = next((a for a in (attention or []) if a.get("severity") == "critical"), None)
    if crit:
        return {"text": crit.get("message"), "severity": "critical", "tab": "overview"}
    if limiter:
        return {"text": limiter["lever"], "severity": "info",
                "tab": limiter["tab"], "anchor": limiter.get("anchor")}
    if attention:
        a = attention[0]
        return {"text": a.get("message"), "severity": a.get("severity"), "tab": "overview"}
    return None


def _overview_hub(conn):
    """Overview synthesis hub (dashboard-information-architecture): the goal verdict + the
    single highlighted limiter + a four-card status strip. Reuses the same values the detail
    tabs show (no new computation), so a card can't disagree with its tab. Degrades to a
    neutral/empty state when there's no goal / unfit model / thin data.

    Status per domain: `safe`/`caution`/`danger` against a *defensible* reference (phase
    volume target, the ACWR safe band, goal-required VDOT) — else `neutral` (no false colour).
    The limiter is the worst-status domain (danger > caution), tie-broken by gap — the one to
    act on first; every below-target domain still shows in the strip (nothing hidden).
    """
    try:
        from fit.analysis import compute_rolling_week
        from fit.fitness import get_fitness_profile
        from fit.goals import get_target_race

        rolling = compute_rolling_week(conn) or {}

        # Goal-required VDOT — the existing derived target (reuse derive_objectives).
        req_vdot = None
        target = get_target_race(conn)
        if target:
            try:
                from fit.fitness import derive_objectives
                for o in derive_objectives(conn, target["id"]):
                    if (o.get("name") or "").lower().startswith("vdot"):
                        req_vdot = o.get("target_value")
            except Exception:
                pass

        eff_vdot = (get_fitness_profile(conn) or {}).get("effective_vdot")

        # References from config + the active phase — not hardcoded.
        from fit.config import get_config
        acfg = (get_config() or {}).get("analysis", {})
        safe_range = acfg.get("acwr_safe_range", [0.8, 1.3])
        danger_hi = acfg.get("acwr_danger_threshold", 1.5)
        phase = conn.execute(
            "SELECT weekly_km_min, weekly_km_max FROM training_phases WHERE status='active' LIMIT 1"
        ).fetchone()
        km_min = phase["weekly_km_min"] if phase else None
        km_max = phase["weekly_km_max"] if phase else None

        # Per-domain status vs its defensible reference (pure helpers — unit-tested).
        vol = rolling.get("run_km")
        fit_status, fit_gap = _hub_volume_status(vol, km_min, km_max)
        phys_status, phys_gap = _hub_vdot_status(eff_vdot, req_vdot)
        row = conn.execute(
            "SELECT acwr FROM weekly_agg WHERE acwr IS NOT NULL ORDER BY week DESC LIMIT 1"
        ).fetchone()
        acwr = row["acwr"] if row else None
        rec_status, rec_gap = _hub_acwr_status(acwr, safe_range, danger_hi)

        # Coach: top coaching note (narrative — neutral/info, not a limiter candidate).
        coach = _coaching(conn) or {}
        notes = coach.get("insights") or []
        top_note = notes[0]["title"] if notes and notes[0].get("title") else None

        def _card(label, value, status, gap, tab, anchor):
            return {"label": label, "value": value, "status": status,
                    "icon": _HUB_STATUS_ICON[status], "gap": gap, "tab": tab, "anchor": anchor}

        cards = [
            _card("Fitness", f"{vol:.0f} km/wk" if vol else "—", fit_status, fit_gap, "training", "train-objectives"),
            _card("Recovery", f"ACWR {acwr:.2f}" if acwr is not None else "—", rec_status, rec_gap, "readiness", "readiness-acwr"),
            _card("Physiology", f"VDOT {eff_vdot:.0f}" if eff_vdot else "—", phys_status, phys_gap, "profile", "prof-vo2max"),
            _card("Coach", top_note or "—", "neutral", 0.0, "coach", "coach-insights"),
        ]

        limiter = _hub_pick_limiter(cards)

        # Verdict — the one forecast (most-likely + range + P(goal) + the limiter as the lever).
        from fit.report.sections.predictions import _marathon_forecast
        fc = _marathon_forecast(conn) or {}
        verdict = None
        if fc.get("available") and fc.get("median"):
            parts = [f"≈{fc['median']}"]
            if fc.get("interval"):
                parts.append(f"likely {fc['interval']}")
            if fc.get("p_ceiling_pct") is not None:
                parts.append(f"P(goal) {fc['p_ceiling_pct']}%")
            reading = " · ".join(parts)
            if limiter:
                reading += f" — limited by {limiter['label'].lower()}: {limiter['lever']}"
            elif fc.get("source") == "model":
                reading += " — on track"
            verdict = {"time": fc["median"], "interval": fc.get("interval"),
                       "p_goal": fc.get("p_ceiling_pct"), "reading": reading,
                       "source": fc.get("source"), "tab": "profile", "anchor": "prof-prediction"}

        # Next action by precedence: critical (safety) > the limiter's lever > a remaining item.
        next_action = _hub_next_action(_attention_items(conn) or [], limiter)

        if not verdict and all(c["status"] == "neutral" for c in cards):
            return {"empty": True, "cards": cards,
                    "prompt": "Set a goal race and log a few runs to light up the Overview."}

        return {"empty": False, "verdict": verdict, "limiter": limiter,
                "next_action": next_action, "cards": cards}
    except Exception as e:
        logger.debug("overview hub unavailable: %s", e)
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


def _model_week_trend(conn, week_starts):
    """Per-week durability-model marathon-equiv (median, lo, hi) in MINUTES — Panel B of
    the marathon_v2 chart. Returns None when the model isn't available (→ table fallback,
    being retired). Loads the cached posterior once, then predicts at each week's chronic
    load (maximal effort)."""
    try:
        from datetime import date as _date
        import numpy as _np
        import pandas as _pd
        from fit.marathon.predict import (
            predict as _predict, effort_h_for_distance, effort_schedule, forecast_context,
        )
        from fit.marathon.features import CHRONIC_REF, CHRONIC_SCALE
        from fit.training_load import DAILY_LOAD_SQL, chronic_load_before
    except ImportError:
        return None
    ctx = forecast_context(conn)        # shared load (posterior + efforts + prior)
    if ctx is None:
        return None
    post, ds, prior = ctx.idata, ctx.ds, ctx.prior
    gap = max(0.0, float(_np.log(ds.goal / ds.d_max)))
    sched = effort_schedule(ds)         # duration-keyed maximal h is c-dependent → resolve once, apply per week
    # Load daily loads ONCE (chronic_load_before is pure) — not a full-table read per week.
    dl = _pd.read_sql_query(DAILY_LOAD_SQL, conn, parse_dates=["date"])
    day_ord = dl["date"].map(_pd.Timestamp.toordinal).to_numpy() if not dl.empty else _np.array([])
    day_load = dl["load"].fillna(0.0).to_numpy() if not dl.empty else _np.array([])
    out = {}
    for ws in week_starts:
        try:
            ref = _date.fromisoformat(ws).toordinal()
        except ValueError:
            continue
        c = (chronic_load_before(ref, day_ord, day_load) - CHRONIC_REF) / CHRONIC_SCALE
        # Per-draw effort uncertainty widens each week's band (median stays on the point h); σ_T0 is
        # held at today's value (sched resolved once), matching trend_series and the point path.
        h, h_draws = effort_h_for_distance(post, ds, ds.goal, c=c, extrapolation_scale=prior["scale"],
                                           nu=prior["nu"], schedule=sched, draws=True)
        r = _predict(post, x=0.0, c=c, h=h, h_draws=h_draws, gap=gap,
                     extrapolation_scale=prior["scale"], nu=prior["nu"])
        out[ws] = (r["median"] / 60.0, r["lo"] / 60.0, r["hi"] / 60.0)
    return out or None


def _prediction_trend_data(conn):
    """Generate prediction trend chart data for the Overview race card.

    Returns JSON-serializable dict with: labels, pred, upper, lower,
    checkpoints, phases, target_min, today.
    """
    try:
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
        # Panel B: marathon-equiv median at each week's chronic load — model only (the
        # weekly-VO2max→table path is retired, D1 Phase 2). No model fit → no trend chart.
        model_trend = _model_week_trend(conn, [w["week_start"] for w in weeks])
        if model_trend is None:
            return None
        for w in weeks:
            labels.append(w["week_start"])
            mt = model_trend.get(w["week_start"])
            pred.append(round(mt[0], 1) if mt else None)

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

        # Confidence band: per-point 90% credible interval (asymmetric) from the model.
        upper, lower = [], []
        for lbl, p in zip(labels, pred):
            mt = model_trend.get(lbl)
            if mt and p is not None:
                lower.append(round(mt[1], 1))
                upper.append(round(mt[2], 1))
            else:
                upper.append(None)
                lower.append(None)

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
                from fit.analysis import RIEGEL_EXPONENT
                needed_secs = 0
                if target_secs > 0:
                    needed_secs = target_secs * (r_km / target_km) ** RIEGEL_EXPONENT

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
                    marathon_equiv = time_secs * (target_km / r_km) ** RIEGEL_EXPONENT
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

        # What can current fitness produce? Prefer the durability-model median so this
        # matches the Overview headline + Panel A (one forecast across the dashboard);
        # the VDOT-anchor time is the fallback. effective_vdot still shows as the engine.
        pred_secs = None
        try:
            from fit.marathon.predict import forecast as _model_forecast
            _fc = _model_forecast(conn, goal_seconds=target_secs)  # cached shared load
            if _fc:
                pred_secs = _fc["median"]
                result["prediction_source"] = "model"
                result["p_sub_goal"] = _fc.get("p_ceiling")  # so the verdict can cite goal odds
        except Exception:
            pred_secs = None
        if pred_secs is None and effective_vdot:
            pred_secs = vdot_to_race_time(effective_vdot, distance_km)
        if pred_secs:
            h = int(pred_secs // 3600)
            m = int((pred_secs % 3600) // 60)
            s = int(pred_secs % 60)
            result["predicted_time"] = f"{h}:{m:02d}:{s:02d}"
            result["gap_minutes"] = round((pred_secs - target_secs) / 60)

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

        # When the headline is the model, the verdict must agree with the model gap
        # (not the VDOT-engine gap) so "ready" never sits next to a "4 min short" time.
        if result.get("prediction_source") == "model" and result.get("gap_minutes") is not None:
            gm = result["gap_minutes"]
            if gm <= 0:
                result["verdict"] = "ready"
            elif gm <= 2:
                result["verdict"] = "almost"
            elif days_left and days_left > 90:
                result["verdict"] = "on_track"   # a few min to close with months left
            elif gm <= 8:
                result["verdict"] = "tight"
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
            result["resilience_band"] = resilience.get("band")
            result["resilience_confidence"] = (resilience.get("confidence") or {}).get("level")
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
            ("aerobic", "VDOT", "var(--z2)", True,
             "Aerobic engine — your race-derived VDOT (Daniels). Sets the ceiling on race pace."),
            ("threshold", "spd/bpm", "var(--z3)", True,
             "Sustainable hard pace — how long you can hold ~1h all-out. Marathon pace lives here."),
            ("economy", "spd/bpm", "var(--accent)", True,
             "Cost of running — speed per heartbeat at Z2. Higher = you cruise easy paces with less effort."),
            ("resilience", "km", "var(--purple)", True,
             "Aerobic durability — how late in a long run HR starts to drift up. Predicts late-marathon survival."),
        ]
        # Bar scale: the goal line sits at 100%, and we show margin out to
        # DISPLAY_MAX so being *above* the requirement is visible (not capped).
        DISPLAY_MAX = 130
        for name, unit, color, higher_better, sowhat in dim_config:
            dim = profile.get(name, {})
            current = dim.get("current_value")
            required = targets.get(name)
            gap = pct = pct_uncapped = pct_bar = None
            over_goal = None
            if current is not None and required is not None and required > 0:
                gap = round(required - current, 2)
                pct_uncapped = round(current / required * 100)   # NOT capped
                pct = min(pct_uncapped, 100)                      # legacy field
                pct_bar = round(min(pct_uncapped, DISPLAY_MAX) / DISPLAY_MAX * 100, 1)
                over_goal = pct_uncapped >= 100

            dims.append({
                "name": name.capitalize(),
                "current": current,
                "required": required,
                "gap": gap,
                "pct": pct,
                "pct_uncapped": pct_uncapped,   # % of goal, uncapped (margin visible)
                "pct_bar": pct_bar,             # width of the track to fill (0..100)
                "over_goal": over_goal,         # at/above the goal line
                "is_limiter": False,            # set below
                "unit": unit,
                "color": color,
                "trend": dim.get("trend"),
                "rate_per_month": dim.get("rate_per_month"),
                "history": dim.get("history", []),
                "message": dim.get("message"),
                "sowhat": sowhat,
            })

        # Aerobic is now the calibrated VDOT anchor (single source with the forecast). Note the
        # Garmin VO2max gap for context — Garmin reads high and is reference-only (chart-vo2).
        _vdot = profile.get("effective_vdot")
        _gvo2 = profile.get("garmin_vo2max")
        if _vdot and _gvo2 and (_gvo2 - _vdot) >= 5:
            for d in dims:
                if d["name"] == "Aerobic":
                    d["caveat"] = (f"Your calibrated VDOT; Garmin VO₂max reads ~+{_gvo2 - _vdot:.0f} "
                                   f"({_gvo2:.0f}) and is reference-only (see Anchor vs Garmin).")

        # Limiter = the dimension furthest below the goal (lowest % of required).
        # A marathon is paced by the weakest relevant capacity, so flag it.
        scored = [d for d in dims if d["pct_uncapped"] is not None]
        if scored:
            min(scored, key=lambda d: d["pct_uncapped"])["is_limiter"] = True
        # The goal-line position on the track (constant), for the template.
        for d in dims:
            d["goal_pos_pct"] = round(100 / DISPLAY_MAX * 100, 1)   # ≈76.9

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

        weight_target = _weight_target(conn)

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


def _profile_takeaways(conn):
    """One-line, data-driven verdict per Profile section ('▸ takeaway').

    The dashboard standardizes every section as title → one-line read →
    visual → takeaway. This builder produces the takeaway text. Every value
    is derived from the SAME builder/query that feeds the section's visual —
    no invented numbers. A section is omitted from the returned dict when its
    data is missing, so the template renders the takeaway line only when there
    is something true to say.
    """
    out = {}

    def _safe(key, fn):
        try:
            v = fn()
            if v:
                out[key] = v
        except Exception as e:  # one bad section must not blank the rest
            logger.debug("takeaway %s failed: %s", key, e)

    # ── Snapshot: what can I run today ───────────────────────────────
    def _today():
        tc = _todays_capability(conn)
        if not tc:
            return None
        parts = []
        if tc.get("z2_pace"):
            t = f"~{tc['z2_pace']}/km sits easy"
            if tc.get("threshold_trend") == "improving":
                t += " and is getting quicker"
            parts.append(t)
        if tc.get("distance_ceiling"):
            parts.append(f"durable to ~{tc['distance_ceiling']} km before HR decouples")
        if not parts:
            return None
        return "Train inside this today — " + "; ".join(parts) + "."

    # ── Snapshot: the four dimensions → name the limiter ─────────────
    def _dimensions():
        dims = _fitness_gap_analysis(conn)
        if not dims:
            return None
        scored = [d for d in dims if d.get("pct") is not None]
        if not scored:
            return None
        weakest = min(scored, key=lambda d: d["pct"])
        if weakest["pct"] >= 100:
            return "All four dimensions are at or above what the goal race needs — hold the build."
        gap_txt = ""
        if weakest.get("current") is not None and weakest.get("required") is not None:
            gap_txt = f" ({weakest['current']} vs {weakest['required']} needed)"
        return (f"Current limiter: {weakest['name']}{gap_txt} at {weakest['pct']}% of "
                f"target — the dimension with the most to gain.")

    # ── Headline: the forecast ───────────────────────────────────────
    def _prediction():
        rc = _race_countdown(conn)
        if not rc or not rc.get("prediction_mid") or not rc.get("target_time"):
            return None
        base = f"Current fitness projects ~{rc['prediction_mid']} vs your {rc['target_time']} target"
        gap = rc.get("gap_minutes")
        if gap is not None:
            if gap <= 0:
                base += f" — {abs(gap)} min to spare"
            else:
                base += f" — {gap} min short"
        if rc.get("trend_badge"):
            base += f" ({rc['trend_badge']})"
        return base + "."

    # ── Engine: VDOT anchor vs Garmin ────────────────────────────────
    def _vdot():
        vc = _vdot_comparison(conn)
        if not vc:
            return None
        anchor = vc.get("race")
        if anchor and vc.get("garmin_vo2"):
            gap = vc["garmin_vo2"] - anchor["vdot"]
            if abs(gap) < 2:
                return (f"Anchor VDOT {anchor['vdot']} and Garmin {vc['garmin_vo2']:g} "
                        f"agree closely — confidence is high.")
            return (f"Trust the anchor: VDOT {anchor['vdot']} from your latest race-effort run; "
                    f"Garmin reads {vc['garmin_vo2']:g} ({gap:+.0f}), the wrist-HR estimate.")
        if anchor:
            return f"Anchor VDOT {anchor['vdot']} from your latest qualifying effort drives the prediction."
        return None

    # ── Engine: aerobic efficiency (economy dimension) ───────────────
    def _efficiency():
        dims = _fitness_gap_analysis(conn) or []
        eco = next((d for d in dims if d["name"].lower() == "economy"), None)
        if not eco or eco.get("current") is None:
            return None
        trend = eco.get("trend")
        if trend == "improving":
            verdict = "trending up — you're covering ground for fewer heartbeats"
        elif trend == "declining":
            verdict = "drifting down — watch fatigue or heat masking economy"
        else:
            verdict = "holding steady"
        rate = ""
        if eco.get("rate_per_month"):
            rate = f" ({eco['rate_per_month']:+.3f}/mo)"
        return f"{eco['current']:.2f} m/min·bpm at Z2{rate} — {verdict}."

    # ── Engine: long-run resilience (cardiac drift onset) ────────────
    def _drift():
        sd = _split_data(conn)
        onset = (sd or {}).get("drift", {}).get("drift_onset_km") if sd else None
        if onset is None:
            dims = _fitness_gap_analysis(conn) or []
            res = next((d for d in dims if d["name"].lower() == "resilience"), None)
            onset = res.get("current") if res else None
        if onset is None:
            return None
        if onset >= 15:
            verdict = "strong aerobic base — late-marathon durability looks solid"
        elif onset >= 10:
            verdict = "decent base; pushing the onset later is the long-run goal"
        else:
            verdict = "an early rise — prioritise easy long-run volume to push it later"
        return f"HR holds flat to ~{onset} km before drifting — {verdict}."

    # ── Engine: zone distribution vs phase target ────────────────────
    def _zones():
        from fit.analysis import compute_rolling_week
        rolling = compute_rolling_week(conn) or {}
        z12 = rolling.get("z12_pct")
        ph = conn.execute(
            "SELECT name, z12_pct_target FROM training_phases "
            "WHERE status = 'active' LIMIT 1"
        ).fetchone()
        if z12 is None or not ph or not ph["z12_pct_target"]:
            return None
        tgt = ph["z12_pct_target"]
        if z12 >= tgt:
            verdict = f"on target for the {ph['name']} phase ({tgt:.0f}% easy)"
        elif z12 >= tgt - 10:
            verdict = f"just under the {tgt:.0f}% {ph['name']}-phase target"
        else:
            verdict = f"well under the {tgt:.0f}% {ph['name']}-phase target — add easy volume"
        return f"{z12:.0f}% of training time easy this week — {verdict}."

    # ── How to train it: pace zones reference ────────────────────────
    def _pace_zones_t():
        pz = _pace_zones(conn)
        if not pz or not pz.get("available"):
            return None
        if pz.get("vdot_source") == "garmin":
            return (f"Paces from Garmin VDOT {pz['vo2max']:g} — no qualifying effort yet; "
                    f"run a 5–10 km at ≥ LTHR to anchor them to real fitness.")
        return (f"Workout paces anchored to your performance VDOT {pz['vo2max']:g} — the same "
                f"number the VDOT trend trusts. Recalibrate by racing a recent effort.")

    # ── Form: cadence trend ──────────────────────────────────────────
    def _cadence():
        rows = conn.execute(
            f"SELECT date, avg_cadence FROM activities "
            f"WHERE type IN {RUNNING_TYPES_SQL} AND avg_cadence IS NOT NULL "
            f"AND date >= date('now','-90 days') ORDER BY date"
        ).fetchall()
        if len(rows) < 3:
            return None
        latest = rows[-1]["avg_cadence"]
        first = rows[0]["avg_cadence"]
        delta = latest - first
        if delta >= 2:
            verdict = "drifting up over 90 days — usually a sign of improving economy"
        elif delta <= -2:
            verdict = "drifting down over 90 days — check for overstriding when tired"
        else:
            verdict = "steady over 90 days"
        return f"Latest {latest:.0f} spm — {verdict}."

    # ── Form: pace consistency (CV%) ─────────────────────────────────
    def _pacecv():
        rows = conn.execute(
            "SELECT a.id, a.date FROM activities a "
            f"WHERE a.type IN {RUNNING_TYPES_SQL} "
            "AND a.id IN (SELECT DISTINCT activity_id FROM activity_splits) "
            "ORDER BY a.date DESC LIMIT 1"
        ).fetchall()
        if not rows:
            return None
        paces = [r["pace_sec_per_km"] for r in conn.execute(
            "SELECT pace_sec_per_km FROM activity_splits "
            "WHERE activity_id = ? AND pace_sec_per_km IS NOT NULL", (rows[0]["id"],)
        ).fetchall()]
        if len(paces) < 3:
            return None
        mean_p = sum(paces) / len(paces)
        if mean_p <= 0:
            return None
        cv = (sum((p - mean_p) ** 2 for p in paces) / len(paces)) ** 0.5 / mean_p * 100
        if cv < 5:
            verdict = "tight, well-controlled splits"
        elif cv < 8:
            verdict = "moderate variation — terrain or effort drift"
        else:
            verdict = "uneven splits — work on even pacing"
        return f"Last run's split CV {cv:.1f}% — {verdict}."

    # ── Form: weight + body composition ──────────────────────────────
    def _weight():
        bc = _body_comp_data(conn)
        if not bc or bc.get("weight") is None:
            return None
        base = f"{bc['weight']} kg"
        if bc.get("weight_change") is not None and bc.get("weight_change_span"):
            base += f" ({bc['weight_change']:+.1f} kg /{bc['weight_change_span']})"
        if bc.get("weight_target"):
            diff = bc["weight"] - bc["weight_target"]
            if abs(diff) < 0.5:
                base += f" — at your {bc['weight_target']} kg target"
            elif diff > 0:
                base += f" — {diff:.1f} kg above the {bc['weight_target']} kg target"
            else:
                base += f" — {abs(diff):.1f} kg under the {bc['weight_target']} kg target"
        return base + "."

    # ── Diagnostics: effort gap (felt-harder-than-watch) ─────────────
    def _effort_gap():
        rows = conn.execute(
            f"SELECT aerobic_te, rpe FROM activities "
            f"WHERE type IN {RUNNING_TYPES_SQL} AND aerobic_te IS NOT NULL AND rpe IS NOT NULL "
            f"ORDER BY date DESC LIMIT 6"
        ).fetchall()
        if not rows:
            return None
        consecutive = 0
        for r in rows:  # most-recent first
            if r["rpe"] / 2 > r["aerobic_te"]:
                consecutive += 1
            else:
                break
        if consecutive >= 3:
            return (f"{consecutive} recent runs in a row felt harder than the watch logged — "
                    f"check sleep, recovery and load before the next hard session.")
        if consecutive >= 1:
            return f"Last {consecutive} run(s) felt a touch harder than the watch — normal, keep an eye on it."
        return "Effort and the watch's read are aligned — no hidden-fatigue signal."

    # ── Diagnostics: calibration anchor ──────────────────────────────
    def _calibration():
        from fit.calibration import get_active_calibration
        lthr = get_active_calibration(conn, "lthr")
        if not lthr or not lthr.get("value"):
            return None
        days = None
        if lthr.get("date"):
            try:
                days = (date.today() - date.fromisoformat(lthr["date"])).days
            except Exception:
                days = None
        age = f" (set {days}d ago)" if days is not None else ""
        stale = " — getting old, re-test from a recent race" if (days or 0) > 180 else ""
        return f"Zones anchored to LTHR {lthr['value']:g}{age}{stale}."

    _safe("today", _today)
    _safe("dimensions", _dimensions)
    _safe("prediction", _prediction)
    _safe("vdot", _vdot)
    _safe("efficiency", _efficiency)
    _safe("drift", _drift)
    _safe("zones", _zones)
    _safe("pace_zones", _pace_zones_t)
    _safe("cadence", _cadence)
    _safe("pacecv", _pacecv)
    _safe("weight", _weight)
    _safe("effort_gap", _effort_gap)
    _safe("calibration", _calibration)
    return out


def _weekly_plan_adherence(conn):
    """Plan adherence for last 4 ISO weeks.

    Returns list of week dicts, each with:
        week: ISO week string
        compliance_pct: matched / total_planned * 100
        completed: number matched
        planned: total planned
        missed: count of missed workouts
        color: green/amber/red based on thresholds
    """
    from datetime import timedelta
    from fit.plan import compute_plan_adherence

    today = date.today()
    result = []

    for offset in range(4):
        ref = today - timedelta(weeks=offset)
        ref_iso = ref.isocalendar()
        week_str = f"{ref_iso[0]}-W{ref_iso[1]:02d}"
        is_current = (offset == 0)
        try:
            adherence = compute_plan_adherence(conn, week_str=week_str)
            if not adherence or not adherence.get("planned"):
                continue
            pct = adherence.get("weekly_compliance_pct", 0) or 0
            planned_count = len(adherence["planned"])
            matched_count = len(adherence.get("matches", []))
            missed_count = len(adherence.get("missed", []))

            if pct >= 70:
                color = "green"
            elif pct >= 50:
                color = "amber"
            else:
                color = "red"

            label = "Current" if is_current else week_str
            result.append({
                "week": label,
                "compliance_pct": round(pct),
                "completed": matched_count,
                "planned": planned_count,
                "missed": missed_count,
                "color": color,
            })
        except Exception:
            continue

    return result


def _last_7_days_runs(conn):
    """Per-run detail cards for the last 7 days.

    Returns list of run dicts, each with:
        date, name, run_type, distance_km, duration_min, pace, avg_hr, hr_zone,
        effort_class, training_load, plan_comparison, splits, adaptation_signals, srpe
    """
    from datetime import timedelta
    from fit.analysis import compute_hr_zones
    from fit.calibration import get_active_calibration
    from fit.config import get_config

    today = date.today()
    window_start = (today - timedelta(days=6)).isoformat()

    config = get_config()
    lthr_cal = get_active_calibration(conn, "lthr")
    lthr = int(lthr_cal["value"]) if lthr_cal else None
    # Per-split zone classification must use the SAME max_hr that enriched
    # the parent activity — otherwise splits and activity disagree on zone
    # after a calibration change.
    max_hr_cal = get_active_calibration(conn, "max_hr")
    max_hr = int(max_hr_cal["value"]) if max_hr_cal else config["profile"].get("max_hr")

    runs = conn.execute(f"""
        SELECT id, date, name, run_type, distance_km, duration_min,
               pace_sec_per_km, avg_hr, hr_zone, effort_class, training_load,
               srpe, splits_status, rpe, feel, compliance_score
        FROM activities
        WHERE type IN {RUNNING_TYPES_SQL} AND date BETWEEN ? AND ?
        ORDER BY date DESC, id DESC
    """, (window_start, today.isoformat())).fetchall()

    _FEEL_LABELS = {1: "Bad", 2: "Poor", 3: "Neutral", 4: "Good", 5: "Great"}

    result = []
    for r in runs:
        run = {
            "date": r["date"],
            "name": _clean_run_name(r["name"]) if r["name"] else "Run",
            "run_type": r["run_type"] or "",
            "distance_km": round(r["distance_km"], 1) if r["distance_km"] else 0,
            "duration_min": round(r["duration_min"], 1) if r["duration_min"] else 0,
            "pace": _format_pace(r["pace_sec_per_km"]),
            "avg_hr": r["avg_hr"],
            "hr_zone": r["hr_zone"] or "",
            "effort_class": r["effort_class"] or "",
            "training_load": round(r["training_load"]) if r["training_load"] else None,
            "rpe": r["rpe"] if r["rpe"] is not None else None,
            "feel": r["feel"] if r["feel"] is not None else None,
            "feel_label": _FEEL_LABELS.get(r["feel"]) if r["feel"] is not None else None,
            "compliance_score": r["compliance_score"] if r["compliance_score"] is not None else None,
            "plan_comparison": None,
            "splits": [],
            "adaptation_signals": None,
            "srpe": None,
        }

        # Plan comparison — match activity to planned workout
        # Resolution priority:
        #   1. Garmin ID link (garmin_workout_id == activity id)
        #   2. Race activity → show race_calendar info instead of plan
        #   3. Type match (workout_type == run_type), only if unique
        #   4. Single plan for single unmatched activity
        #   5. Ambiguous → leave unmatched
        day_plans = conn.execute("""
            SELECT workout_name, workout_type, target_distance_km, garmin_workout_id
            FROM planned_workouts WHERE date = ? AND status != 'skipped'
        """, (r["date"],)).fetchall()
        planned = None
        match_method = None
        activity_id = str(r["id"])
        run_type = r["run_type"] or ""

        # 1. Direct Garmin ID link
        for p in day_plans:
            if p["garmin_workout_id"] and str(p["garmin_workout_id"]) == activity_id:
                planned = p
                match_method = "Garmin workout link"
                break

        # 2. Race activity → show race info from race_calendar
        if not planned and run_type == "race":
            race = conn.execute("""
                SELECT name, target_time, result_time, garmin_time, distance
                FROM race_calendar WHERE activity_id = ?
            """, (activity_id,)).fetchone()
            if race:
                race_result = race["result_time"] or race["garmin_time"]
                target = race["target_time"]
                if race_result and target:
                    verdict = "race"
                else:
                    verdict = "race"
                run["plan_comparison"] = {
                    "planned_name": race["name"],
                    "planned_type": "race",
                    "target_km": None,
                    "verdict": verdict,
                    "match_method": "race calendar",
                    "race_result": race_result,
                    "race_target": target,
                }
                # Skip remaining plan matching for race activities
                planned = "race_handled"

        # 3. Type match (only if unique)
        if not planned:
            type_matches = [p for p in day_plans if (p["workout_type"] or "") == run_type]
            if len(type_matches) == 1:
                planned = type_matches[0]
                match_method = "type match"

        # 4. Single plan for the day
        if not planned and len(day_plans) == 1:
            planned = day_plans[0]
            match_method = "only plan"

        if planned and planned != "race_handled":
            plan_type = planned["workout_type"] or ""
            verdict = "on target"
            _z = Zone.parse_or_none(r["hr_zone"])
            if plan_type in ("easy", "recovery") and _z is not None and _z >= Zone.Z3:
                verdict = "too fast"
            elif plan_type in ("tempo", "intervals") and _z in {Zone.Z1, Zone.Z2}:
                verdict = "too slow"
            run["plan_comparison"] = {
                "planned_name": planned["workout_name"],
                "planned_type": plan_type,
                "target_km": planned["target_distance_km"],
                "verdict": verdict,
                "match_method": match_method,
            }
        elif planned != "race_handled":
            has_any_plan = conn.execute(
                "SELECT 1 FROM planned_workouts LIMIT 1"
            ).fetchone()
            if has_any_plan:
                run["plan_comparison"] = {
                    "planned_name": "Unplanned run",
                    "planned_type": "",
                    "target_km": None,
                    "verdict": "unplanned",
                }

        # Splits (task 5.3)
        if r["splits_status"] == "done":
            splits = conn.execute("""
                SELECT split_num, distance_km, time_sec, pace_sec_per_km,
                       avg_hr, avg_cadence, elevation_gain_m,
                       intensity_type, wkt_step_index
                FROM activity_splits WHERE activity_id = ? ORDER BY split_num
            """, (r["id"],)).fetchall()
            run["splits"] = [
                {
                    "km": s["split_num"],
                    "distance_km": s["distance_km"],
                    "time_sec": s["time_sec"],
                    "pace": _format_pace(s["pace_sec_per_km"]),
                    "pace_secs": s["pace_sec_per_km"],
                    "hr": s["avg_hr"],
                    "cadence": s["avg_cadence"],
                    "elevation": s["elevation_gain_m"],
                    "zone": compute_hr_zones(
                        int(s["avg_hr"]) if s["avg_hr"] else None,
                        config, lthr=lthr, max_hr=max_hr,
                    )["hr_zone"] or "",
                    "intensity_type": s["intensity_type"],
                    "wkt_step_index": s["wkt_step_index"],
                }
                for s in splits
            ]

            # Cardiac drift from splits
            try:
                from fit.fit_file import compute_cardiac_drift
                split_dicts = [dict(s) for s in splits]
                drift = compute_cardiac_drift(split_dicts)
                if drift and drift["status"] == "detected":
                    run["cardiac_drift"] = {
                        "pct": round(drift["drift_pct"], 1),
                        "onset_km": drift["drift_onset_km"],
                    }
            except Exception:
                pass

        # sRPE context (task 5.6)
        if r["srpe"]:
            # Compare sRPE to training_load
            if r["training_load"] and r["training_load"] > 0:
                ratio = r["srpe"] / r["training_load"]
                if ratio > 1.3:
                    feel = "felt harder than HR suggests"
                elif ratio < 0.7:
                    feel = "felt easier than HR suggests"
                else:
                    feel = None
            else:
                feel = None
            run["srpe"] = {"value": round(r["srpe"], 1), "feel": feel}

        result.append(run)

    # Adaptation signals (task 5.5): 4-week rolling avg pace by run_type
    for run in result:
        if not run["run_type"]:
            continue
        try:
            avg_row = conn.execute(f"""
                SELECT AVG(pace_sec_per_km) as avg_pace, AVG(speed_per_bpm) as avg_spb,
                       COUNT(*) as n
                FROM activities
                WHERE type IN {RUNNING_TYPES_SQL} AND run_type = ?
                AND date BETWEEN date(?, '-28 days') AND date(?, '-1 day')
            """, (run["run_type"], run["date"], run["date"])).fetchone()
            if avg_row and avg_row["n"] and avg_row["n"] >= 2:
                signals = {}
                raw = conn.execute(
                    "SELECT pace_sec_per_km, speed_per_bpm FROM activities WHERE date = ? AND type IN {types} LIMIT 1".format(types=RUNNING_TYPES_SQL),
                    (run["date"],),
                ).fetchone()
                if avg_row["avg_pace"] and raw and raw["pace_sec_per_km"]:
                    pace_diff = raw["pace_sec_per_km"] - avg_row["avg_pace"]
                    if abs(pace_diff) >= 5:
                        signals["pace_vs_avg"] = round(pace_diff, 0)
                if avg_row["avg_spb"] and raw and raw["speed_per_bpm"]:
                    spb_diff = raw["speed_per_bpm"] - avg_row["avg_spb"]
                    if abs(spb_diff) >= 0.005:
                        signals["spb_vs_avg"] = round(spb_diff, 3)
                if signals:
                    run["adaptation_signals"] = signals
        except Exception:
            pass

    # Weather context per run
    for run in result:
        run["weather"] = None
        try:
            w = conn.execute("""
                SELECT temp_c as temp, humidity_pct as humidity,
                       wind_speed_kmh as wind, precipitation_mm as precipitation,
                       conditions
                FROM weather WHERE date = ?
            """, (run["date"],)).fetchone()
            if w:
                run["weather"] = {
                    "temp": w["temp"],
                    "humidity": w["humidity"],
                    "wind": w["wind"],
                    "precipitation": w["precipitation"],
                    "conditions": w["conditions"],
                }
        except Exception:
            pass

    # sRPE noise suppression: if all runs have the same feel direction, suppress
    feels = [r["srpe"]["feel"] for r in result if r.get("srpe") and r["srpe"].get("feel")]
    if len(feels) >= 2 and len(set(feels)) == 1:
        for run in result:
            if run.get("srpe"):
                run["srpe"]["feel"] = None

    # Build split chart configs for per-run Chart.js rendering
    import json
    for i, run in enumerate(result):
        run["split_chart"] = None
        if run["splits"] and len(run["splits"]) >= 2:
            zone_color_map = {"Z1": Z1, "Z2": Z2, "Z3": Z3, "Z4": Z4, "Z5": Z5}
            # Detect structured workout: multiple distinct wkt_step_index values
            step_indices = {s.get("wkt_step_index") for s in run["splits"]
                           if s.get("wkt_step_index") is not None}
            has_structure = len(step_indices) > 1

            if has_structure:
                # Group laps by (intensity_type, wkt_step_index) runs
                segments = _group_splits_by_step(run["splits"])
                # Expand segments into distance-proportional bins
                # so warmup 2.4km is 6× wider than a 400m interval
                grey = "rgba(148,163,184,0.5)"
                dists = [seg["distance_km"] for seg in segments]
                min_dist = min(d for d in dists if d > 0.05) if dists else 0.4
                bin_size = min_dist  # smallest segment = 1 bin

                split_labels = []
                pace_data = []
                hr_data = []
                elev_data = []
                bar_colors = []
                seg_ranges = []  # [{start, end, color, label}] for plugin
                phase_legend = {}  # label -> color for legend
                bin_idx = 0
                for seg in segments:
                    n_bins = max(1, round(seg["distance_km"] / bin_size))
                    color = zone_color_map.get(seg["zone"], grey) + "cc"
                    # Track unique phase types for legend
                    phase_key = seg["label"]
                    if phase_key not in phase_legend:
                        phase_legend[phase_key] = color
                    seg_ranges.append({
                        "s": bin_idx, "e": bin_idx + n_bins - 1,
                        "c": color, "v": seg["avg_pace"],
                    })
                    elev_per_bin = (seg["total_elev"] or 0) / n_bins
                    mid = n_bins // 2  # center the label
                    for b in range(n_bins):
                        # No x-axis labels for structured — zone strip
                        # provides the labels inside the colored bands
                        split_labels.append("")
                        # Pace + HR: single dot at segment midpoint only
                        pace_data.append(seg["avg_pace"] if b == mid else None)
                        hr_data.append(seg["avg_hr"] if b == mid else None)
                        elev_data.append(round(elev_per_bin, 1))
                        bar_colors.append(color)
                    bin_idx += n_bins
            else:
                # Per-km view (long runs, unstructured)
                grey = "rgba(148,163,184,0.5)"
                split_labels = [str(s["km"]) for s in run["splits"]]
                pace_data = [s["pace_secs"] for s in run["splits"]]
                hr_data = [s["hr"] for s in run["splits"]]
                elev_data = [s.get("elevation") or 0 for s in run["splits"]]
                bar_colors = [
                    zone_color_map.get(s["zone"], grey) + "cc"
                    for s in run["splits"]
                ]
                # One segment per km for the custom plugin
                seg_ranges = [
                    {"s": idx, "e": idx,
                     "c": zone_color_map.get(s["zone"], grey) + "cc",
                     "v": s["pace_secs"]}
                    for idx, s in enumerate(run["splits"])
                ]

            # Y-axis range: exclude REST/walking segments (huge pace outliers)
            if has_structure:
                active_paces = [
                    seg["avg_pace"] for seg in segments
                    if seg["avg_pace"] and seg.get("intensity") != "REST"
                ]
            else:
                active_paces = [p for p in pace_data if p]
            if not active_paces:
                active_paces = [p for p in pace_data if p]
            pace_range = max(active_paces) - min(active_paces) if active_paces else 0
            padding = max(30, pace_range * 0.5)
            y_min = min(active_paces) - padding if active_paces else None
            y_max = max(active_paces) + padding if active_paces else None
            # Cap REST bars to y_max so they don't blow up the scale
            if y_max:
                pace_data = [min(p, y_max) if p else p for p in pace_data]
                for sr in seg_ranges:
                    sr["v"] = min(sr["v"], y_max) if sr["v"] else sr["v"]

            # Build phase legend entries (deduplicated)
            # Colors resolved in JS from CSS variables (--z1..--z5)
            phase_legend_items = []
            seen_labels = set()
            if has_structure:
                legend_names = {
                    "WARMUP": "WU = Warm-up", "COOLDOWN": "CD = Cool-down",
                    "REST": "Rest", "RECOVERY": "J = Jog recovery",
                    "ACTIVE": "R = Rep",
                }
                for seg in segments:
                    lbl = legend_names.get(seg["intensity"], seg["intensity"])
                    if lbl not in seen_labels:
                        seen_labels.add(lbl)
                        phase_legend_items.append({
                            "zone": seg["zone"], "label": lbl,
                        })
            else:
                zone_names = {
                    "Z1": "Z1 Recovery", "Z2": "Z2 Easy",
                    "Z3": "Z3 Moderate", "Z4": "Z4 Hard",
                    "Z5": "Z5 Very Hard",
                }
                for s in run["splits"]:
                    z = s.get("zone", "")
                    if z and z not in seen_labels:
                        seen_labels.add(z)
                        phase_legend_items.append({
                            "zone": z, "label": zone_names.get(z, z),
                        })

            # Compute HR range with padding
            hr_vals = [h for h in hr_data if h]
            hr_min = min(hr_vals) - 5 if hr_vals else 100
            hr_max = max(hr_vals) + 5 if hr_vals else 200

            # Compute elevation range
            elev_vals = [e for e in elev_data if e]
            elev_max = max(elev_vals) * 1.3 if elev_vals else 10

            # Zone strip segments: [{s, e, zone, label}] for plugin
            zone_segments = []
            if has_structure:
                # One band per workout segment (preserve segment boundaries)
                bin_idx = 0
                for seg in segments:
                    n_bins = max(1, round(seg["distance_km"] / bin_size))
                    zone_segments.append({
                        "s": bin_idx, "e": bin_idx + n_bins - 1,
                        "zone": seg["zone"],
                        "label": seg["short_label"],
                    })
                    bin_idx += n_bins
            else:
                # Per-km: merge consecutive same-zone km into one band
                for idx, s in enumerate(run["splits"]):
                    z = s.get("zone", "")
                    if (zone_segments and
                            zone_segments[-1]["zone"] == z):
                        zone_segments[-1]["e"] = idx
                    else:
                        zone_segments.append({
                            "s": idx, "e": idx,
                            "zone": z, "label": z,
                        })

            run["split_chart"] = json.dumps({
                "type": "line",
                "data": {
                    "labels": split_labels,
                    "datasets": [
                        {
                            "label": "Pace",
                            "data": pace_data,
                            "borderColor": "#818cf8",
                            "backgroundColor": "#818cf8",
                            "borderWidth": 2,
                            "pointRadius": 3 if has_structure else 2,
                            "pointBackgroundColor": "#818cf8",
                            "spanGaps": True,
                            "fill": False,
                            "yAxisID": "y",
                            "order": 1,
                        },
                        {
                            "label": "HR",
                            "data": hr_data,
                            "borderColor": "#f87171",
                            "backgroundColor": "#f87171",
                            "borderWidth": 2,
                            "pointRadius": 3 if has_structure else 2,
                            "pointBackgroundColor": "#f87171",
                            "spanGaps": True,
                            "fill": False,
                            "yAxisID": "y1",
                            "order": 2,
                        },
                    ],
                },
                "_zone_segments": zone_segments,
                "_phase_legend": phase_legend_items,
                "options": {
                    "responsive": True,
                    "maintainAspectRatio": False,
                    "layout": {},
                    "plugins": {
                        "legend": {"display": False},
                        "tooltip": {},
                    },
                    "scales": {
                        "x": {"grid": {"display": False},
                               "ticks": {"display": not has_structure,
                                         "font": {"size": 7},
                                         "color": "#64748b",
                                         "maxRotation": 0, "autoSkip": False,
                                         "__skip_empty": True}},
                        "y": {"position": "left",
                               "grid": {"color": "rgba(255,255,255,0.05)"},
                               "ticks": {"font": {"size": 8}, "color": "#818cf880"},
                               "title": {"display": True, "text": "Pace (min/km)",
                                          "font": {"size": 8},
                                          "color": "#818cf880"},
                               "min": y_min, "max": y_max},
                        "y1": {"position": "right",
                                "grid": {"drawOnChartArea": False},
                                "ticks": {"font": {"size": 8}, "color": "#f8717180"},
                                "title": {"display": True, "text": "HR (bpm)",
                                           "font": {"size": 8},
                                           "color": "#f8717180"},
                                "min": hr_min, "max": hr_max},
                    },
                },
            })

            # Separate elevation chart
            run["split_elev_chart"] = json.dumps({
                "type": "line",
                "data": {
                    "labels": split_labels,
                    "datasets": [{
                        "label": "Elevation",
                        "data": elev_data,
                        "borderColor": "rgba(148,163,184,0.5)",
                        "backgroundColor": "rgba(148,163,184,0.15)",
                        "borderWidth": 1.5,
                        "pointRadius": 0,
                        "fill": True,
                        "tension": 0.3,
                    }],
                },
                "options": {
                    "responsive": True,
                    "maintainAspectRatio": False,
                    "plugins": {"legend": {"display": False},
                                "tooltip": {"callbacks": {}}},
                    "scales": {
                        "x": {"display": False},
                        "y": {"position": "left",
                               "grid": {"color": "rgba(255,255,255,0.03)"},
                               "ticks": {"font": {"size": 7},
                                         "color": "rgba(148,163,184,0.4)"},
                               "title": {"display": True, "text": "m",
                                          "font": {"size": 7},
                                          "color": "rgba(148,163,184,0.4)"},
                               "min": 0,
                               "max": elev_max},
                        # Dummy right axis to match main chart width
                        "y1": {"position": "right",
                                "grid": {"drawOnChartArea": False},
                                "ticks": {"display": True,
                                          "font": {"size": 8},
                                          "color": "transparent"},
                                "title": {"display": True, "text": " ",
                                           "font": {"size": 8},
                                           "color": "transparent"}},
                    },
                },
            })

    return result


def _group_splits_by_step(splits):
    """Group per-lap splits into workout segments by (intensity_type, wkt_step_index).

    Consecutive laps with the same step are merged. Returns list of segment dicts:
        label, avg_pace, avg_hr, total_elev, intensity, distance_km

    For interval workouts (alternating step indices), each lap stays separate
    with rep numbering (R1, R2... for work, J1, J2... for jog recovery).
    """
    intensity_labels = {
        "WARMUP": "WU", "COOLDOWN": "CD", "REST": "Rest", "ACTIVE": "",
    }
    segments = []
    current = None
    for s in splits:
        key = (s.get("intensity_type"), s.get("wkt_step_index"))
        if current and current["key"] == key:
            current["laps"].append(s)
        else:
            if current:
                segments.append(current)
            current = {"key": key, "laps": [s]}
    if current:
        segments.append(current)

    # Detect interval pattern: alternating ACTIVE step indices
    active_segs = [seg for seg in segments if seg["key"][0] == "ACTIVE"]
    active_steps = [seg["key"][1] for seg in active_segs]
    is_interval = (
        len(active_steps) >= 4
        and len(set(active_steps)) == 2
        and active_steps[0] != active_steps[1]
    )
    if is_interval:
        # Identify which step is work (faster avg pace) vs recovery
        step_a, step_b = sorted(set(active_steps))
        paces_a = [lap.get("pace_secs") or 999 for seg in active_segs
                    if seg["key"][1] == step_a for lap in seg["laps"]]
        paces_b = [lap.get("pace_secs") or 999 for seg in active_segs
                    if seg["key"][1] == step_b for lap in seg["laps"]]
        avg_a = sum(paces_a) / len(paces_a) if paces_a else 999
        avg_b = sum(paces_b) / len(paces_b) if paces_b else 999
        work_step = step_a if avg_a < avg_b else step_b
        work_n, jog_n = 0, 0

    result = []
    for seg in segments:
        laps = seg["laps"]
        intensity = laps[0].get("intensity_type") or "ACTIVE"
        step_idx = seg["key"][1]
        total_dist = sum((lap.get("distance_km") or 1.0) for lap in laps)
        total_time = sum((lap.get("time_sec") or 0) for lap in laps)
        hrs = [lap["hr"] for lap in laps if lap.get("hr")]
        zones = [lap.get("zone") for lap in laps if lap.get("zone")]

        # Labels: full (tooltip) and short (x-axis)
        prefix = intensity_labels.get(intensity, "")
        d_str = (f"{total_dist:.1f}km" if total_dist >= 1
                 else f"{int(total_dist * 1000)}m")
        if intensity in ("WARMUP", "COOLDOWN", "REST"):
            label = f"{prefix} {d_str}"
            short_label = prefix
        elif is_interval and intensity == "ACTIVE":
            if step_idx == work_step:
                work_n += 1
                label = f"R{work_n} {d_str}"
                short_label = f"R{work_n}"
            else:
                jog_n += 1
                label = f"J{jog_n} {d_str}"
                short_label = f"J{jog_n}"
        else:
            lap_dists = [lap.get("distance_km") or 1.0 for lap in laps]
            if len(laps) > 1 and max(lap_dists) - min(lap_dists) < 0.05:
                d = lap_dists[0]
                d_s = f"{d:.1f}km" if d >= 1 else f"{int(d * 1000)}m"
                label = f"{len(laps)}×{d_s}"
            else:
                label = d_str
            short_label = label

        avg_pace = round(total_time / total_dist) if total_dist > 0 else None

        # For intervals, distinguish work vs jog intensity
        seg_intensity = intensity
        if is_interval and intensity == "ACTIVE" and step_idx != work_step:
            seg_intensity = "RECOVERY"

        # Most common zone in the segment
        zone = max(set(zones), key=zones.count) if zones else ""

        result.append({
            "label": label,
            "short_label": short_label,
            "avg_pace": avg_pace,
            "avg_hr": round(sum(hrs) / len(hrs)) if hrs else None,
            "total_elev": sum(lap.get("elevation") or 0 for lap in laps),
            "intensity": seg_intensity,
            "zone": zone,
            "distance_km": round(total_dist, 2),
        })
    return result


def _format_pace(pace_sec_per_km):
    """Format pace as M:SS/km."""
    if not pace_sec_per_km:
        return "--:--"
    mins = int(pace_sec_per_km // 60)
    secs = int(pace_sec_per_km % 60)
    return f"{mins}:{secs:02d}"



def _clean_run_name(name):
    """Strip Garmin/Runna prefixes and redundant suffixes from run names."""
    if not name:
        return "Run"
    import re
    # Strip prefixes like "Berlin - W 1 So. " or "W 1 Fr. "
    cleaned = re.sub(r'^(?:.*?W\s*\d+\s*\w+\.\s*)', '', name)
    if not cleaned or len(cleaned) < 5:
        cleaned = name  # fallback if regex ate everything or left too little
    return cleaned


def _training_objectives(conn):
    """4 canonical objective slots for the Training tab.

    Slots: Volume, Long Run, Z2 Compliance, Consistency.
    Each slot includes current value, WoW delta, and a 7-day daily trend.

    Returns dict with:
        active: bool — whether objectives are live (target race set)
        slots: list of 4 dicts with name, target, current, unit, status,
               wow_delta, wow_pct, streak_label
        prompt: str — shown when deactivated
    """
    from datetime import timedelta
    from fit.goals import get_target_race
    from fit.analysis import compute_rolling_week

    race = get_target_race(conn)
    rolling = compute_rolling_week(conn)
    prev_rolling = compute_rolling_week(
        conn, end_date=date.today() - timedelta(days=7),
    )

    # 4 canonical slot definitions with prefix-match to derive_objectives names
    slot_defs = [
        {"key": "volume", "label": "Volume", "prefix": "Peak volume", "unit": "km/wk"},
        {"key": "long_run", "label": "Long Run", "prefix": "Long run", "unit": "km"},
        {"key": "z2", "label": "Z2 Compliance", "prefix": "Z2 compliance", "unit": "%"},
        {"key": "consistency", "label": "Consistency", "prefix": "Consistency", "unit": "weeks"},
    ]

    # Load goals if target race exists
    goal_map = {}
    if race:
        goals = conn.execute("SELECT * FROM goals WHERE active = 1").fetchall()
        for g in goals:
            name = g["name"] or ""
            for sd in slot_defs:
                if name.startswith(sd["prefix"]):
                    goal_map[sd["key"]] = dict(g)
                    break

    # Consistency uses last completed ISO week
    today = date.today()
    today_iso = today.isocalendar()
    current_week_str = f"{today_iso[0]}-W{today_iso[1]:02d}"
    completed_week = conn.execute(
        "SELECT * FROM weekly_agg WHERE week < ? ORDER BY week DESC LIMIT 1",
        (current_week_str,),
    ).fetchone()
    prev_completed_week = conn.execute(
        "SELECT * FROM weekly_agg WHERE week < ? ORDER BY week DESC LIMIT 1 OFFSET 1",
        (current_week_str,),
    ).fetchone()

    def _extract_value(key, data):
        if key == "volume":
            return round(data["run_km"], 1) if data and data.get("run_km") else 0
        elif key == "long_run":
            return round(data["longest_run_km"], 1) if data and data.get("longest_run_km") else 0
        elif key == "z2":
            return round(data["z12_pct"], 1) if data and data.get("z12_pct") is not None else None
        elif key == "consistency":
            return None  # handled separately
        return None

    slots = []
    for sd in slot_defs:
        goal = goal_map.get(sd["key"])
        target = goal["target_value"] if goal else None
        streak_label = None

        # Current + previous for WoW
        if sd["key"] == "consistency":
            current = completed_week["consecutive_weeks_3plus"] if completed_week else 0
            prev = prev_completed_week["consecutive_weeks_3plus"] if prev_completed_week else None
            # Streak sub-label: show in-week progress
            runs_this_week = conn.execute("""
                SELECT COUNT(*) as n FROM activities
                WHERE type IN {types} AND date >= date(?, 'weekday 0', '-7 days')
            """.format(types=RUNNING_TYPES_SQL), (today.isoformat(),)).fetchone()
            n = runs_this_week["n"] if runs_this_week else 0
            if n >= 3:
                streak_label = "streak secured, updates Monday"
            elif n > 0:
                remaining = 3 - n
                streak_label = f"{n}/3 — {remaining} more to keep streak"
        else:
            current = _extract_value(sd["key"], rolling)
            prev = _extract_value(sd["key"], prev_rolling)

        # WoW delta
        wow_delta = None
        wow_pct = None
        if current is not None and prev is not None:
            wow_delta = round(current - prev, 1)
            if prev > 0:
                wow_pct = round((current - prev) / prev * 100)

        # Status
        status = "deactivated"
        if target is not None and current is not None:
            if sd["key"] == "z2":
                status = "on_track" if current >= target * 0.9 else "at_risk" if current >= target * 0.7 else "off_track"
            elif sd["key"] == "consistency":
                status = "on_track" if current >= target else "at_risk" if current >= target * 0.5 else "off_track"
            else:
                status = "on_track" if current >= target else "at_risk" if current >= target * 0.7 else "off_track"

        slots.append({
            "name": sd["label"],
            "target": target,
            "current": current,
            "unit": sd["unit"],
            "status": status,
            "wow_delta": wow_delta,
            "wow_pct": wow_pct,
            "streak_label": streak_label,
        })

    return {
        "active": bool(race),
        "slots": slots,
        "prompt": None if race else "Set a target race with `fit objective set`",
    }


def _last_7_days_hero(conn, config=None):
    """Last 7 Days hero card for the Training tab.

    Returns dict with:
        volume_km, run_count, volume_target_km, volume_pct,
        daily_km: list of 7 dicts (date, km, label) for bar chart,
        phase_targets: dict with min/max/peak km for target bands,
        next_workouts: list of upcoming planned workouts with expected zone/HR,
        compliance_pct/completed/total: plan adherence in window.
    """
    from datetime import timedelta
    from fit.analysis import compute_rolling_week

    rolling = compute_rolling_week(conn, config=config)
    today = date.today()

    result = {
        "compliance_pct": None,
        "compliance_completed": 0,
        "compliance_total": 0,
        "volume_km": rolling["run_km"],
        "volume_target_km": None,
        "volume_pct": None,
        "next_workouts": _next_workouts_enriched(conn),
        "run_count": rolling["run_count"],
        "daily_km": [],
        "phase_targets": None,
    }

    # Per-day km breakdown for last 7 days bar chart
    window_start = (today - timedelta(days=6)).isoformat()
    try:
        day_rows = conn.execute("""
            SELECT date, SUM(distance_km) as km
            FROM activities
            WHERE type IN {types} AND date BETWEEN ? AND ?
            GROUP BY date ORDER BY date
        """.format(types=RUNNING_TYPES_SQL), (window_start, today.isoformat())).fetchall()
        km_by_date = {r["date"]: round(r["km"], 1) for r in day_rows}
    except Exception:
        km_by_date = {}

    for i in range(7):
        d = today - timedelta(days=6 - i)
        iso = d.isoformat()
        result["daily_km"].append({
            "date": iso,
            "km": km_by_date.get(iso, 0),
            "label": d.strftime("%a"),
        })

    # Phase volume targets for band overlay
    phase = conn.execute(
        "SELECT * FROM training_phases WHERE status = 'active' LIMIT 1"
    ).fetchone()
    if phase and phase["weekly_km_min"] and phase["weekly_km_max"]:
        target_mid = (phase["weekly_km_min"] + phase["weekly_km_max"]) / 2
        result["volume_target_km"] = target_mid
        if target_mid > 0:
            result["volume_pct"] = round(rolling["run_km"] / target_mid * 100)
        result["phase_targets"] = {
            "current_min": phase["weekly_km_min"],
            "current_max": phase["weekly_km_max"],
            "phase_name": phase["name"],
        }

    # Compliance ring: the canonical plan-adherence definition (current ISO week,
    # rest days excluded, distance/zone matching) via compute_plan_adherence — the
    # SAME source as the weekly adherence strip, not a bespoke rolling-7d date-count
    # (which counted rest days and any-activity-on-a-planned-date, inflating the %).
    try:
        from fit.plan import compute_plan_adherence
        adherence = compute_plan_adherence(conn)
        non_rest = [p for p in adherence["planned"] if p["workout_type"] != "rest"]
        matched = sum(1 for m in adherence["matches"]
                      if m["actual"] is not None and not m.get("rest_day"))
        if non_rest:
            result["compliance_total"] = len(non_rest)
            result["compliance_completed"] = matched
            result["compliance_pct"] = adherence["weekly_compliance_pct"]
    except Exception:
        pass

    return result


def _zone_hr_range(zone_name, max_hr):
    """Return (low, high) HR for a zone given max_hr."""
    pcts = {
        "Z1": (0.0, 0.60), "Z2": (0.60, 0.70), "Z3": (0.70, 0.80),
        "Z4": (0.80, 0.90), "Z5": (0.90, 1.00),
    }
    lo, hi = pcts.get(zone_name.upper(), (0.60, 0.70))
    return (round(max_hr * lo), round(max_hr * hi))


def _expected_zone_for_type(workout_type):
    """Map workout type to expected primary HR zone."""
    mapping = {
        "easy": "Z2", "recovery": "Z1", "long": "Z2",
        "tempo": "Z3", "threshold": "Z4",
        "intervals": "Z4", "race": "Z4",
    }
    return mapping.get(workout_type, "Z2")


def _next_workouts_enriched(conn):
    """Next planned workouts (shared base) decorated with expected zone + HR range."""
    workouts = _next_workouts_base(conn)
    if not workouts:
        return []

    cal = conn.execute(
        "SELECT value FROM calibration WHERE metric='max_hr' AND active=1 "
        "ORDER BY date DESC LIMIT 1"
    ).fetchone()
    max_hr = cal["value"] if cal else None

    for w in workouts:
        zone = (w.pop("target_zone") or _expected_zone_for_type(w["type"])).upper()
        if not zone.startswith("Z"):
            zone = _expected_zone_for_type(w["type"])
        w["zone"] = zone
        if max_hr:
            lo, hi = _zone_hr_range(zone, max_hr)
            w["hr_range"] = f"{lo}–{hi}"
        else:
            w["hr_range"] = None
    return workouts


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
