"""Race prediction section — VDOT, Riegel extrapolation, pacing."""

import logging

from fit.report.sections import SAFE, CAUTION, DANGER, Z1, Z2, Z3, Z4, Z5, ACCENT  # noqa: F401

logger = logging.getLogger(__name__)


def _hms(secs):
    secs = int(round(secs))
    return f"{secs // 3600}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"


def _goal_seconds(conn):
    row = conn.execute(
        "SELECT target_time FROM goals WHERE active = 1 AND target_time IS NOT NULL "
        "ORDER BY type DESC LIMIT 1").fetchone()
    if not row or not row["target_time"]:
        return None
    p = str(row["target_time"]).split(":")
    try:
        return int(p[0]) * 3600 + int(p[1]) * 60 + (int(p[2]) if len(p) > 2 else 0)
    except (ValueError, IndexError):
        return None


def _marathon_forecast(conn, maximal_hr=None):
    """Bayesian forecast section for the dashboard — a template-ready dict, always
    present (`available`/`source`), degrading to the calibrated-VDOT anchor headline when
    the model can't run (never the retired table; design Decision 7).

    `maximal_hr=None` → the goal's distance-appropriate, LTHR-relative maximal effort
    (`maximal_effort_h`); pass an absolute HR only to override."""
    goal_secs = _goal_seconds(conn)

    def _anchor(reason):
        from fit.fitness import anchor_race_time
        from fit.goals import get_target_race
        tr = get_target_race(conn)
        d = (tr.get("distance_km") if tr else None) or 42.195
        secs = anchor_race_time(conn, d)
        if not secs:
            return {"available": False, "reason": reason}
        return {"available": True, "source": "anchor", "median": _hms(secs),
                "interval": None, "goal_km": d, "note": reason}

    try:
        from fit.marathon.predict import (
            forecast as run_forecast, derived_metrics, influence, _current_c, forecast_context,
        )
    except ImportError:
        return _anchor("durability model extra not installed")

    ctx = forecast_context(conn)        # one shared load (posterior + efforts + prior)
    if ctx is None:
        return _anchor("model not fit yet (run `fit sync` or `fit forecast`)")
    idata, ds = ctx.idata, ctx.ds

    try:
        fc = run_forecast(conn, avg_hr=maximal_hr, goal_seconds=goal_secs)
        if not fc:
            return _anchor("forecast could not be produced")
        ex = fc["extrapolation"]
        c = _current_c(conn)
        dm = derived_metrics(idata, ds, c=c, extrapolation_scale=ex["scale"], nu=ex["nu"])
        import math
        bd = dm["durability_beta_d"]
        phi, kap = dm["fitness_value_phi"], dm["effort_kappa"]
        goal_min = fc["median"] / 60.0
        # φ: Δ per +10 chronic-load units; κ: Δ per +5 bpm vs LTHR (both Δlog-time).
        phi_min = goal_min * (math.exp(phi["median"]) - 1)
        phi_pct = (math.exp(phi["median"]) - 1) * 100
        kappa_pct = (math.exp(kap["median"]) - 1) * 100
        infl = influence(idata, ds)
        flagged = [e for e in infl["efforts"] if e["influential"]]
        return {
            "available": True, "source": "model",
            "median": _hms(fc["median"]),
            "interval": f"{_hms(fc['lo'])} – {_hms(fc['hi'])}",
            "p_ceiling_pct": (round(fc["p_ceiling"] * 100) if "p_ceiling" in fc else None),
            "goal_time": (_hms(goal_secs) if goal_secs else None),
            "goal_km": ds.goal,
            "beta_d": f"{bd['median']:.3f}", "beta_d_ci": f"{bd['lo']:.3f}–{bd['hi']:.3f}",
            "beta_d_dominated": bool(bd["prior_dominated"]),
            "phi_reading": f"{phi_min:+.1f} min ({phi_pct:+.1f}%) per +10 fitness",
            "phi_dominated": bool(phi["prior_dominated"]),
            "kappa_reading": f"{kappa_pct:+.1f}% pace per +5 bpm",
            "kappa_dominated": bool(kap["prior_dominated"]),
            "extrap_reason": ex["reason"], "extrap_defaulted": bool(ex["defaulted"]),
            "unvalidated": bool(ds.d_max < ds.goal), "d_max": round(ds.d_max, 1),
            "dist_min": round(float(ds.efforts["distance_km"].min()), 1),  # distance-colour legend domain

            "equiv": [{"label": r["label"], "time": _hms(r["median"])} for r in dm["race_equivalency"]],
            "influential": [{"date": e["date"], "distance_km": e["distance_km"], "k": round(e["pareto_k"], 2)}
                            for e in flagged[:3]],
        }
    except Exception as e:  # pragma: no cover - defensive: a bad posterior must not break the report
        logger.warning("marathon forecast section failed: %s", e)
        return _anchor("forecast error — anchor fallback")


def _prediction_summary(conn):
    """Compact race forecast for the race card header.

    Single source = the calibrated VDOT anchor (anchor_race_time), NOT Garmin
    VO2max via the retired table. Returns None when there is no usable anchor.
    """
    try:
        from fit.fitness import anchor_race_time
        from fit.calibration import get_calibration_anchor
        from fit.goals import get_target_race

        target_race = get_target_race(conn)
        target_km = target_race["distance_km"] if target_race and target_race.get("distance_km") else 42.195

        headline = anchor_race_time(conn, target_km)
        note = ""
        if headline:
            anchor = get_calibration_anchor(conn, "vdot") or {}
            note = " (stale — re-test)" if anchor.get("stale") else ""
        else:
            # No calibrated anchor → conservative Riegel extrapolation from
            # actual races. Never the retired Garmin-VO2max table.
            from fit.analysis import riegel_fallback_secs
            headline = riegel_fallback_secs(conn, target_km)
            note = " (race estimate)" if headline else ""
        if not headline:
            return None
        return f"Prediction: {headline // 3600}:{(headline % 3600) // 60:02d}{note}"
    except Exception:
        return None
