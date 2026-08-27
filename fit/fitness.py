"""Fitness profile: 4-dimension model with VDOT tracking, trends, and achievability."""

import logging
import math
import sqlite3
from datetime import date

import numpy as np

from fit.analysis import RUNNING_TYPES_SQL, RIEGEL_EXPONENT

logger = logging.getLogger(__name__)

# ── Daniels VDOT Formula ──
# From Daniels' Running Formula: VDOT computed from oxygen cost and VO2max fraction.
# No lookup table needed — the formula is the source of truth.


# Single-entry cache keyed by CONNECTION IDENTITY (mirrors predict._CTX_CACHE): a dashboard
# render calls get_fitness_profile ~7× (cards + charts) and the resilience dimension now runs a
# 400-iteration bootstrap + per-run drift compute, so one render would otherwise redo all of it
# 7×. One render = one connection → the first call computes, the rest hit the cache. A new
# connection (next render / a different caller) recomputes. (Mutations on the SAME connection
# followed by a re-read would see the cached value — acceptable for the read-only render path,
# same trade-off as the forecast-context cache.)
_PROFILE_CACHE: dict = {"conn": None, "profile": None}


def get_fitness_profile(conn: sqlite3.Connection) -> dict:
    """Compute the 4-dimension fitness profile from current data.

    Returns dict with:
        aerobic: {current_value, trend, rate_per_month, source, data_points}
        threshold: {current_value, trend, rate_per_month, source, data_points}
        economy: {current_value, trend, rate_per_month, source, data_points}
        resilience: {current_value, trend, rate_per_month, source, data_points}
        effective_vdot: float (blended from races + Garmin)
        garmin_vo2max: float (latest from Garmin)
        race_vdot: float (latest from race results)
        race_vdot_date: str
    """
    if _PROFILE_CACHE["conn"] is conn:
        return _PROFILE_CACHE["profile"]
    profile = {
        "aerobic": _compute_aerobic(conn),
        "threshold": _compute_threshold(conn),
        "economy": _compute_economy(conn),
        "resilience": _compute_resilience(conn),
    }

    # VDOT computation — _effective_vdot is the single trusted aerobic anchor (the Aerobic
    # dimension reads the same helper, so the bar and the headline never diverge).
    garmin_vo2 = _get_garmin_vo2max(conn)
    race_vdot, race_vdot_date = _get_race_vdot(conn)
    effective = _effective_vdot(conn)

    profile["garmin_vo2max"] = garmin_vo2
    profile["race_vdot"] = race_vdot
    profile["race_vdot_date"] = race_vdot_date
    profile["effective_vdot"] = effective

    _PROFILE_CACHE["conn"], _PROFILE_CACHE["profile"] = conn, profile
    return profile


# ── Dimension Computations ──
#
# DIMENSION_WINDOW: fitness dimensions are ungoverned display readouts (no
# staleness flag, no human-confirm), and they're fed by near-daily runs — so the
# window IS their freshness guarantee and is short (4 weeks ≈ one mesocycle).
# This is deliberately shorter than the governed *anchors* (VDOT/LTHR/AeT 180d,
# MaxHR 365d), which can afford long windows because they have a staleness
# backstop. The "current" value is the MEDIAN over the window (not the latest
# single reading): VO2max/speed-per-bpm are two-sided (terrain/tailwind/strap
# inflate, heat/fatigue deflate), so a median is the robust current state — a
# max would chase a downhill run, and the latest is just noise. (Resilience is
# the lone dimension using a max — its drift onset is pace-CV-gated, so it can't
# be inflated; see _compute_resilience.)
DIMENSION_WINDOW_DAYS = 28


def _median(nums: list[float]) -> float:
    s = sorted(nums)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _effective_vdot(conn: sqlite3.Connection):
    """The single trusted aerobic anchor every consumer reads: confirmed VDOT calibration >
    recent race VDOT > Garmin VO2max minus its ~5-point overestimate. None if none exist."""
    try:
        from fit.calibration import get_calibration_anchor  # local: calibration imports fitness
        anchor = get_calibration_anchor(conn, "vdot")
        if anchor is not None:
            return float(anchor.value)
    except Exception as e:
        logger.debug("vdot anchor unavailable, using legacy effective_vdot: %s", e)
    race_vdot, race_date = _get_race_vdot(conn)
    return _compute_effective_vdot(_get_garmin_vo2max(conn), race_vdot, race_date)


def _compute_aerobic(conn: sqlite3.Connection) -> dict:
    """Aerobic capacity = the trusted effective VDOT (the same value the forecast/headline use,
    via _effective_vdot), NOT Garmin VO2max — which reads ~5-10 high and is kept only as a
    reference (the Anchor-vs-Garmin chart). The trend DIRECTION still comes from the Garmin
    VO2max series (the densest signal), shifted to the anchor level so the sparkline matches."""
    vdot = _effective_vdot(conn)
    if vdot is None:
        return _empty_dimension("No VDOT anchor — confirm a race-effort VDOT")

    rows = conn.execute(
        "SELECT date, vo2max FROM activities "
        "WHERE vo2max IS NOT NULL AND date >= date('now', ?) ORDER BY date",
        (f"-{DIMENSION_WINDOW_DAYS} days",),
    ).fetchall()
    garmin = [(r["date"], r["vo2max"]) for r in rows]
    if garmin:
        trend, rate = _compute_trend(garmin)
        shift = vdot - garmin[-1][1]                       # anchor the Garmin trend at the VDOT level
        history = [round(v + shift, 1) for _, v in garmin[-8:]]
    else:
        trend, rate, history = "insufficient_data", None, [round(vdot, 1)]

    return {
        "current_value": round(vdot),                      # VDOT is an integer index (Daniels)
        "trend": trend,
        "rate_per_month": rate,
        "unit": "VDOT",
        "source": "VDOT anchor (race-derived)",
        "data_points": len(garmin),
        "history": history,
    }


def _compute_threshold(conn: sqlite3.Connection) -> dict:
    """Threshold: Z2 pace at HR ceiling (speed at controlled effort), grade-adjusted."""
    values = _ga_spb_series(conn, "speed_per_bpm_z2")
    if len(values) < 3:
        return _empty_dimension("Need 3+ Z2 runs in last 4 weeks")

    current = _median([v for _, v in values])
    trend, rate = _compute_trend(values)

    return {
        "current_value": round(current, 4),
        "trend": trend,
        "rate_per_month": round(rate, 4) if rate else None,
        "unit": "m/min/bpm (Z2)",
        "source": "Z2 speed per BPM (grade-adjusted)",
        "data_points": len(values),
        "history": [v for _, v in values[-8:]],
    }


def _ga_spb_series(conn: sqlite3.Connection, col: str):
    """[(date, grade-adjusted <col>)] over the dimension window. The stored speed-per-bpm is
    scaled by raw_duration / flat-equivalent-duration (terrain removed via the splits), so a
    hilly run isn't judged less efficient than it was. Falls back to the raw value when an
    activity has no splits. `col` is an internal constant, not user input."""
    from fit.fit_file import grade_adjusted_duration_min
    rows = conn.execute(f"""
        SELECT date, id, {col} AS spb, duration_min FROM activities
        WHERE type IN {RUNNING_TYPES_SQL} AND {col} IS NOT NULL
        AND date >= date('now', '-{DIMENSION_WINDOW_DAYS} days') ORDER BY date
    """).fetchall()
    out = []
    for r in rows:
        val = r["spb"]
        if r["duration_min"] and r["duration_min"] > 0:
            sp = conn.execute(
                "SELECT split_num, pace_sec_per_km, distance_km, elevation_gain_m, "
                "elevation_loss_m FROM activity_splits WHERE activity_id=? ORDER BY split_num",
                (r["id"],)).fetchall()
            ga = grade_adjusted_duration_min([dict(s) for s in sp]) if sp else None
            if ga and ga > 0:
                val = round(val * r["duration_min"] / ga, 4)
        out.append((r["date"], val))
    return out


def _compute_economy(conn: sqlite3.Connection) -> dict:
    """Economy: overall speed per BPM (running efficiency), grade-adjusted."""
    values = _ga_spb_series(conn, "speed_per_bpm")
    if len(values) < 3:
        return _empty_dimension("Need 3+ runs with HR data in last 4 weeks")

    current = _median([v for _, v in values])
    trend, rate = _compute_trend(values)

    return {
        "current_value": round(current, 4),
        "trend": trend,
        "rate_per_month": round(rate, 4) if rate else None,
        "unit": "m/min/bpm",
        "source": "Speed per BPM (grade-adjusted)",
        "data_points": len(values),
        "history": [v for _, v in values[-8:]],
    }


# ── Resilience (drift onset) estimator ──────────────────────────────────────────────
# Drift onset is a ONE-SIDED, right-censored signal: a no-drift run is a LOWER bound
# (durable to at least its distance — we can't see past the run), a detected run is an
# observed onset, and short/hot/tired runs only push onset EARLIER. So the estimate is a
# weighted BEST-demonstrated onset (not a downward-biased mean), shrunk toward a conservative
# prior when the evidence is thin or stale — mirroring the maximal-effort schedule's T₀.
# All four constants are judgment-informed priors, NOT measured values.
RESILIENCE_LOOKBACK_DAYS = 120     # query bound; the half-life decay does the real weighting
RESILIENCE_HALF_LIFE_DAYS = 21     # recency decay — durability is trainable/detrainable
RESILIENCE_LENGTH_REF_KM = 32.0    # length-weight reference (~marathon long run); weight caps at 1
RESILIENCE_SHRINK_K = 2.0          # shrink strength: λ = N_eff / (N_eff + K)
RESILIENCE_PRIOR_FRAC = 0.6        # cold-start prior = this × typical recent long run …
RESILIENCE_PRIOR_FLOOR_KM = 8.0    # … floored here (the qualifying-run threshold)
# Confidence-interval shape. The CI is a Bayesian bootstrap (sampling spread) widened on the
# upside by the unobserved-distance gap. These four are THREE ORTHOGONAL small-N safeguards, not
# one knob: shrink-to-prior (RESILIENCE_SHRINK_K) governs the POINT estimate; the floor sets a
# MINIMUM CI width when the bootstrap degenerates at 1–2 runs; the coverage term adds the censored
# UPSIDE (distance you've never run). The principled unification — one censored-likelihood
# posterior — is the deferred option-3 (memory `resilience-bayesian-ci`); these are pinned by
# test_resilience until then.
RESILIENCE_BAND_FLOOR = 0.05       # min CI half-width as a fraction of the estimate …
RESILIENCE_BAND_FLOOR_THIN = 0.08  # … plus this / √N_eff (wider when few runs feed it)
RESILIENCE_BAND_FLOOR_LO = 0.5     # floor applies at half strength on the well-supported low side
RESILIENCE_BAND_COVERAGE = 0.4     # fraction of the longest-run→goal gap added to the upper bound
# Resilience = AEROBIC durability: how far you hold marathon-style (sub-threshold) effort
# before HR decouples. Hard-effort runs decouple early BY DESIGN (run above aerobic pace), so
# they're excluded; a NULL/unclassified run_type is kept (assumed steady). (Durability knob B.)
RESILIENCE_HARD_TYPES = ("tempo", "intervals", "progression", "race")
RESILIENCE_MIN_KM = 8              # only long runs probe durability


def resilience_run_filter(alias="a"):
    """SQL predicate selecting runs eligible for the durability/resilience signal: steady aerobic
    only — RESILIENCE_HARD_TYPES decouple early by design and are excluded; NULL/unclassified is
    kept (assumed steady). Single-sourced so the resilience dimension AND the drift charts score
    the SAME population (pair with each surface's distance/window gates, e.g. RESILIENCE_MIN_KM)."""
    hard = ", ".join(f"'{t}'" for t in RESILIENCE_HARD_TYPES)
    return f"({alias}.run_type IS NULL OR {alias}.run_type NOT IN ({hard}))"


def _weighted_quantile(pairs, q):
    """Weighted q-quantile (q in [0,1]) of (value, weight) pairs — the smallest value whose
    cumulative weight (ascending) reaches q·Σw. Used for the weighted best-demonstrated onset."""
    pts = sorted((v, w) for v, w in pairs if w > 0)
    if not pts:
        return None
    total = sum(w for _, w in pts)
    target = q * total
    cum = 0.0
    for v, w in pts:
        cum += w
        if cum >= target:
            return v
    return pts[-1][0]


def _goal_long_km(conn):
    """~0.75 × the target race distance — the long run a marathon-style goal demands — or None."""
    try:
        from fit.goals import get_target_race
        t = get_target_race(conn)
        if t and t.get("distance_km"):
            return round(float(t["distance_km"]) * 0.75, 1)
    except Exception:
        return None
    return None


def _compute_resilience(conn: sqlite3.Connection) -> dict:
    """Resilience: drift onset km — a recency- and length-weighted, censored estimate with an
    asymmetric uncertainty band and a confidence level (resilience-uncertainty change).

    Drift onset comes from compute_cardiac_drift (the ONE source); this aggregates the per-run
    points: a no-drift run is a right-censored LOWER bound at its full distance, a detected run
    is an observed onset. Recent + long runs weigh more; the estimate shrinks toward a
    conservative prior when the effective sample is thin or stale, so a lone/old run is never
    reported as a confident durability figure.
    """
    splits_runs = conn.execute(f"""
        SELECT a.id, a.date, a.distance_km FROM activities a
        WHERE a.type IN {RUNNING_TYPES_SQL}
        AND a.splits_status = 'done'
        AND a.distance_km >= {RESILIENCE_MIN_KM}
        AND {resilience_run_filter()}
        AND a.date >= date('now', '-{RESILIENCE_LOOKBACK_DAYS} days')
        ORDER BY a.date
    """).fetchall()

    if not splits_runs:
        return _empty_dimension(
            "Enable .fit file download: fit sync --splits. "
            "Need long runs (8km+) with split data for resilience tracking."
        )

    from fit.fit_file import compute_cardiac_drift
    today = date.today()
    points = []   # {date, value, censored, age, dist, weight}
    for run in splits_runs:
        splits = conn.execute("""
            SELECT split_num, avg_hr, pace_sec_per_km, distance_km,
                   elevation_gain_m, elevation_loss_m FROM activity_splits
            WHERE activity_id = ? ORDER BY split_num
        """, (run["id"],)).fetchall()
        if len(splits) < 4:
            continue
        drift = compute_cardiac_drift([dict(s) for s in splits])
        status = drift.get("status") if drift else None
        if status == "detected" and drift.get("drift_onset_km"):
            value, censored = float(drift["drift_onset_km"]), False
        elif status == "none":
            value, censored = float(run["distance_km"]), True   # lower bound: held to the end
        else:
            continue   # inconclusive (variable pace) / insufficient — not usable
        dist = float(run["distance_km"] or 0)
        age = max(0, (today - date.fromisoformat(run["date"])).days)
        recency = 0.5 ** (age / RESILIENCE_HALF_LIFE_DAYS)
        length = min(dist / RESILIENCE_LENGTH_REF_KM, 1.0) if RESILIENCE_LENGTH_REF_KM else 1.0
        points.append({"date": run["date"], "value": value, "censored": censored,
                       "age": age, "dist": dist, "weight": recency * length})

    if not points:
        return _empty_dimension("No usable drift data from recent long runs")

    weights = [p["weight"] for p in points]
    values = [p["value"] for p in points]

    # Cold-start prior: a conservative fraction of the typical recent long run.
    dists = sorted(p["dist"] for p in points)
    prior = max(RESILIENCE_PRIOR_FLOOR_KM, RESILIENCE_PRIOR_FRAC * dists[len(dists) // 2])

    def _estimate(ws):
        """The shrunk, weighted best-demonstrated onset (75th pct, one-sided) for a weight vector,
        plus its Kish N_eff. Used for the point estimate AND each bootstrap resample."""
        s1, s2 = sum(ws), sum(w * w for w in ws)
        ne = (s1 * s1 / s2) if s2 > 0 else 0.0
        wb = _weighted_quantile(list(zip(values, ws)), 0.75) or 0.0
        lam = ne / (ne + RESILIENCE_SHRINK_K) if (ne + RESILIENCE_SHRINK_K) > 0 else 0.0
        return lam * wb + (1 - lam) * prior, ne

    est, n_eff = _estimate(weights)

    # ── Confidence interval — Bayesian bootstrap (sampling uncertainty) + the censored upside ──
    # Reweight the points by Dirichlet(1..1) draws and recompute the estimate; the 5–95% spread is
    # the sampling CI (wide when few runs feed it). A bootstrap can't see distance you've never run,
    # so the UPPER bound also carries the coverage gap to the goal long-run. A small-N floor keeps a
    # 1–2-run history from looking falsely precise (the bootstrap degenerates there). Seeded →
    # deterministic report.
    # Option 3 (deferred — see memory `resilience-bayesian-ci`): a censored-likelihood Bayesian
    # posterior (KM / parametric survival) would unify the shrink-to-prior and the interval.
    longest = max(p["dist"] for p in points)
    best_age = min(p["age"] for p in points)            # recency of the freshest evidence
    stale_hl = best_age / RESILIENCE_HALF_LIFE_DAYS
    goal_long = _goal_long_km(conn)
    coverage_gap = max(0.0, goal_long - longest) if goal_long else 0.0
    rng = np.random.default_rng(0)
    boot = sorted(_estimate(list(np.asarray(weights) * g))[0]
                  for g in rng.dirichlet(np.ones(len(points)), size=400))
    lo_bs, hi_bs = float(np.percentile(boot, 5)), float(np.percentile(boot, 95))
    floor = est * (RESILIENCE_BAND_FLOOR + RESILIENCE_BAND_FLOOR_THIN / math.sqrt(max(n_eff, 0.5)))
    lo = max(0.0, min(lo_bs, est - RESILIENCE_BAND_FLOOR_LO * floor))
    hi = max(hi_bs, est + floor) + RESILIENCE_BAND_COVERAGE * coverage_gap   # censored / unobserved upside

    # Confidence: enough recent long runs near the goal distance → high; thin/stale/short → low.
    recent = best_age <= RESILIENCE_HALF_LIFE_DAYS
    covered = (goal_long is None) or (longest >= 0.8 * goal_long)
    if n_eff >= 4 and recent and covered:
        level, reason = "high", "several recent long runs near goal distance"
    elif n_eff < 1.5 or stale_hl > 2.5 or (goal_long and longest < 0.5 * goal_long):
        level, reason = "low", ("thin data" if n_eff < 1.5 else
                                "best evidence is stale" if stale_hl > 2.5 else
                                "longest run far short of goal")
    else:
        level, reason = "med", "moderate recent long-run evidence"

    trend, rate = _compute_trend([(p["date"], p["value"]) for p in points])

    return {
        "current_value": round(est, 1),
        "trend": trend,
        "rate_per_month": round(rate, 1) if rate else None,
        "unit": "km (drift onset)",
        "source": "Cardiac drift analysis (recency/length-weighted, censored)",
        "data_points": len(points),
        "n_eff": round(n_eff, 1),
        "band": {"lo": round(lo, 1), "hi": round(hi, 1)},
        "confidence": {"level": level, "reason": reason},
        "history": [p["value"] for p in points[-8:]],
        "points": [{"date": p["date"], "value": round(p["value"], 1),
                    "censored": p["censored"], "dist": round(p["dist"], 1)} for p in points],
    }


# ── VDOT Computation ──


def _oxygen_cost(velocity_m_per_min: float) -> float:
    """Oxygen cost of running at a given velocity (ml/kg/min).

    Daniels' formula: VO2 = -4.60 + 0.182258v + 0.000104v²
    """
    v = velocity_m_per_min
    return -4.60 + 0.182258 * v + 0.000104 * v * v


def _vo2max_fraction(time_min: float) -> float:
    """Fraction of VO2max sustainable for a given duration.

    Daniels' formula: %VO2max = 0.8 + 0.1894393e^(-0.012778t) + 0.2989558e^(-0.1932605t)
    """
    t = time_min
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)


def compute_vdot_from_race(distance_km: float, time_seconds: int) -> float | None:
    """Compute VDOT from a race result using Daniels' oxygen cost formula.

    VDOT = oxygen_cost(velocity) / vo2max_fraction(time)
    This is the exact formula from Daniels' Running Formula, not a table lookup.

    DANIELS-BASED ASSUMPTIONS (see also _oxygen_cost / _vo2max_fraction):
      - **Population-average running economy.** oxygen_cost is the Daniels &
        Gilbert regression — an AVERAGE cost of running at a given speed. Real
        economy varies ±10-15% between runners, so VDOT is a performance INDEX
        (pseudo-VO2max), not a measured VO2max. The athlete's actual economy is
        tracked separately (the speed_per_bpm / Aerobic Efficiency dimension).
      - **Average endurance.** vo2max_fraction is a fixed %VO2max-vs-duration
        curve — assumes the athlete sustains the population-average fraction for
        a given race duration. Personal endurance/durability is NOT modelled
        here (the Riegel forecast captures that — see predict_race_time).
      - **Clean effort.** Assumes a near-maximal, evenly-paced effort on a flat,
        accurately-measured course in fair conditions. Hills / heat / trail /
        pacing blow-ups depress VDOT; they're handled as calibration CONFIDENCE
        (surfaced at the confirm prompt), never silently excluded.
    """
    if distance_km <= 0 or time_seconds <= 0:
        return None

    time_min = time_seconds / 60.0
    distance_m = distance_km * 1000.0
    velocity = distance_m / time_min  # meters per minute

    vo2 = _oxygen_cost(velocity)
    fraction = _vo2max_fraction(time_min)

    if fraction <= 0:
        return None

    vdot = vo2 / fraction
    return round(vdot, 1)


def vdot_to_race_time(vdot: float, distance_km: float) -> int | None:
    """Predict race time in seconds for a given VDOT and distance.

    Uses binary search: find the time where compute_vdot_from_race(distance, time) = vdot.
    """
    if vdot <= 0 or distance_km <= 0:
        return None

    # Binary search for time that produces the target VDOT
    # VDOT decreases as time increases (slower = lower VDOT)
    lo = 60 * 5       # 5 minutes minimum
    hi = 60 * 60 * 7  # 7 hours maximum

    for _ in range(50):  # max iterations
        mid = (lo + hi) // 2
        computed = compute_vdot_from_race(distance_km, mid)
        if computed is None:
            return None
        if abs(computed - vdot) < 0.1:
            return mid
        if computed > vdot:
            lo = mid  # too fast (high VDOT) → need more time
        else:
            hi = mid  # too slow (low VDOT) → need less time

    return (lo + hi) // 2


def anchor_race_time(conn: sqlite3.Connection, distance_km: float) -> int | None:
    """Predicted race time (seconds) at a distance, from the calibrated VDOT anchor.

    The single source for the race-forecast headline. Supersedes the retired
    ``_vdot_to_marathon_seconds`` table and the "latest Garmin VO2max" input:
    Garmin's HR-based VO2max runs well above this athlete's race-implied VDOT, so
    forecasting off it inflated the number. The anchor is race-calibrated, so the
    forecast is grounded in what was actually run.

    Returns None when there is no usable anchor (dashboard then degrades to the
    per-race Riegel extrapolation, never to the removed table).
    """
    if conn is None or distance_km <= 0:
        return None
    from fit.calibration import get_calibration_anchor  # local: avoid import cycle
    anchor = get_calibration_anchor(conn, "vdot")
    if anchor is None:
        return None
    return vdot_to_race_time(anchor.value, distance_km)


def inverse_vdot(target_time_seconds: int, distance_km: float) -> float | None:
    """Inverse Daniels: what VDOT do you need for a target time at a given distance?

    This is simply compute_vdot_from_race — the VDOT that produces this performance.
    E.g., marathon 4:00:00 → VDOT needed to sustain that pace for that duration.
    """
    return compute_vdot_from_race(distance_km, target_time_seconds)


def _get_garmin_vo2max(conn: sqlite3.Connection) -> float | None:
    """Latest Garmin VO2max estimate."""
    row = conn.execute(
        "SELECT vo2max FROM activities WHERE vo2max IS NOT NULL ORDER BY date DESC LIMIT 1"
    ).fetchone()
    return row["vo2max"] if row else None


def get_fitness_anchors(
    conn: sqlite3.Connection,
    days: int = 365,
    min_distance_km: float = 5.0,
    max_distance_km: float = 25.0,
    lthr: int | None = None,
    max_pace_cv_pct: float = 15.0,
) -> list[dict]:
    """Activities that qualify as fitness/VDOT anchors per physiological criteria.

    Unlike race_calendar (which is manual and sometimes mislabeled — a "long
    run training" tagged as a race poisons the anchor), this filters the
    actual activity log by effort signature:

      1. Distance in [min_distance_km, max_distance_km] — default 5–25 km
         (covers 5K through half-marathon; longer brings fuel/glycogen into
         play, shorter is too anaerobic for Daniels' formula).
      2. Avg HR ≥ LTHR — proxy for "this was a sustained max effort", not
         a tempo or long-run training pace.
      3. Pace consistent across splits (CV ≤ max_pace_cv_pct) — rules out
         interval workouts and runs with walk breaks.

    External limiters (heat, illness, sleep) aren't visible in the activity
    record, so the user judges those manually. The function reports
    confidence so they can weigh the evidence.

    LTHR comes from the active calibration unless overridden via the `lthr`
    arg (handy for tests). When no LTHR is calibrated, returns [] — without
    a threshold anchor there's no way to apply criterion 2.

    Returns activities sorted VDOT-descending (best fitness signal first).
    """
    from fit.calibration import get_active_calibration

    if lthr is None:
        cal = get_active_calibration(conn, "lthr")
        if not cal:
            return []
        lthr = cal["value"]

    rows = conn.execute(
        f"""
        SELECT id, date, name, distance_km, duration_min, avg_hr, max_hr,
               pace_sec_per_km
        FROM activities
        WHERE type IN {RUNNING_TYPES_SQL}
          AND date >= date('now', ?)
          AND distance_km >= ? AND distance_km <= ?
          AND avg_hr >= ?
          AND duration_min IS NOT NULL AND duration_min > 0
        ORDER BY date DESC
        """,
        (f"-{days} days", min_distance_km, max_distance_km, lthr),
    ).fetchall()

    anchors = []
    for r in rows:
        # Criterion 3: pace coefficient of variation across splits.
        # Sub-15% rules out interval workouts (which alternate fast/slow)
        # and runs with walk breaks (one km drops to 7+ min/km).
        splits = conn.execute(
            "SELECT pace_sec_per_km FROM activity_splits "
            "WHERE activity_id = ? AND pace_sec_per_km IS NOT NULL",
            (r["id"],),
        ).fetchall()
        pace_cv_pct = None
        if len(splits) >= 3:
            paces = [s["pace_sec_per_km"] for s in splits]
            mean_p = sum(paces) / len(paces)
            if mean_p > 0:
                stdev_p = (sum((p - mean_p) ** 2 for p in paces) / len(paces)) ** 0.5
                pace_cv_pct = stdev_p / mean_p * 100
                if pace_cv_pct > max_pace_cv_pct:
                    continue

        secs = r["duration_min"] * 60
        vdot = compute_vdot_from_race(r["distance_km"], secs)
        if vdot is None:
            continue

        hr_margin_pct = (r["avg_hr"] - lthr) / lthr * 100

        # Confidence rubric — tighter HR margin + tighter pace CV → higher.
        # "high" requires meaningful headroom over LTHR (≥3% = ~5 bpm)
        # and tight pacing if splits exist.
        if hr_margin_pct >= 3 and (pace_cv_pct is None or pace_cv_pct <= 6):
            confidence = "high"
        elif hr_margin_pct >= 0 and (pace_cv_pct is None or pace_cv_pct <= 12):
            confidence = "medium"
        else:
            confidence = "low"

        # Mark whether this date also has a race_calendar entry — purely
        # informational, doesn't gate qualification.
        race_match = conn.execute(
            "SELECT 1 FROM race_calendar WHERE date = ? AND result_time IS NOT NULL LIMIT 1",
            (r["date"],),
        ).fetchone()

        anchors.append({
            "activity_id": r["id"],
            "date": r["date"],
            "name": r["name"],
            "distance_km": round(r["distance_km"], 2),
            "duration_min": round(r["duration_min"], 1),
            "pace_sec_per_km": r["pace_sec_per_km"],
            "avg_hr": r["avg_hr"],
            "max_hr": r["max_hr"],
            "hr_margin_pct": round(hr_margin_pct, 1),
            "pace_cv_pct": round(pace_cv_pct, 1) if pace_cv_pct is not None else None,
            "vdot": round(vdot, 1),
            "confidence": confidence,
            "source": "race" if race_match else "training",
        })

    anchors.sort(key=lambda a: a["vdot"], reverse=True)
    return anchors


def _get_race_vdot(conn: sqlite3.Connection) -> tuple[float | None, str | None]:
    """Best VDOT from recent race results (last 6 months).

    Uses the BEST (highest) VDOT from recent races, not the most recent.
    This avoids a single bad race (wind, illness, pacing) dragging down
    the effective VDOT. The best recent race is the most representative
    of actual fitness potential.
    """
    races = conn.execute("""
        SELECT date, distance_km, result_time FROM race_calendar
        WHERE status = 'completed' AND result_time IS NOT NULL AND distance_km IS NOT NULL
        AND date >= date('now', '-180 days')
        ORDER BY date DESC
    """).fetchall()

    if not races:
        return None, None

    def _parse_time(t):
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0

    # Compute VDOT for each recent race, pick the best
    best_vdot = None
    best_date = None
    for r in races:
        time_sec = _parse_time(r["result_time"])
        vdot = compute_vdot_from_race(r["distance_km"], time_sec)
        if vdot and (best_vdot is None or vdot > best_vdot):
            best_vdot = vdot
            best_date = r["date"]

    return best_vdot, best_date


def _compute_effective_vdot(garmin_vo2: float | None, race_vdot: float | None,
                             race_date: str | None) -> float | None:
    """Compute effective VDOT from race results and Garmin VO2max.

    Race VDOT is ALWAYS preferred over Garmin VO2max because:
    - Race VDOT comes from actual performance (you ran that time)
    - Garmin VO2max is estimated from wrist HR during short GPS runs
    - Garmin consistently overestimates by 5-10 VDOT points

    When race data exists (<6 months), use race VDOT directly.
    Fall back to Garmin only when no recent races exist, and even then
    apply a discount factor (Garmin reads high).
    """
    if race_vdot and race_date:
        days_ago = (date.today() - date.fromisoformat(race_date)).days
        if days_ago <= 180:  # 6 months
            return race_vdot

    # No recent race — use Garmin with discount (tends to read ~5 VDOT high)
    if garmin_vo2:
        return round(garmin_vo2 - 5, 1)

    return None


# ── Trend Computation ──


def _compute_trend(values: list[tuple[str, float]]) -> tuple[str, float | None]:
    """Compute trend direction and rate from time-series data.

    Args:
        values: List of (date_string, value) pairs, sorted by date.

    Returns:
        (trend, rate_per_month) where trend is 'improving'/'declining'/'flat'/'insufficient_data'
    """
    if len(values) < 3:
        return "insufficient_data", None

    # Convert dates to numeric (days from first)
    base_date = date.fromisoformat(values[0][0])
    xs = [(date.fromisoformat(d) - base_date).days for d, _ in values]
    ys = [v for _, v in values]

    # Simple linear regression
    n = len(xs)
    sum_x = sum(xs)
    sum_y = sum(ys)
    sum_xy = sum(x * y for x, y in zip(xs, ys))
    sum_x2 = sum(x * x for x in xs)

    denom = n * sum_x2 - sum_x * sum_x
    if denom == 0:
        return "flat", 0.0

    slope = (n * sum_xy - sum_x * sum_y) / denom

    # Rate per month (30 days)
    rate_per_month = slope * 30

    # Mean value for relative threshold
    mean_y = sum_y / n
    if mean_y == 0:
        return "flat", 0.0

    # Threshold: >2% change per month = trending, otherwise flat
    relative_rate = abs(rate_per_month / mean_y) * 100
    if relative_rate < 2:
        return "flat", round(rate_per_month, 4)
    elif rate_per_month > 0:
        return "improving", round(rate_per_month, 4)
    else:
        return "declining", round(rate_per_month, 4)


def _empty_dimension(message: str) -> dict:
    """Return an empty dimension with an actionable message."""
    return {
        "current_value": None,
        "trend": "insufficient_data",
        "rate_per_month": None,
        "unit": None,
        "source": None,
        "data_points": 0,
        "message": message,
        "history": [],
    }


# ── Objective Derivation ──


def derive_objectives(conn, race_id: int) -> list[dict]:
    """Auto-derive training objectives from a target race.

    Uses Daniels VDOT for aerobic targets, distance heuristics for volume/long run,
    timeline for consistency requirements.

    Returns list of objective dicts ready for goals table upsert.
    """
    race = conn.execute("SELECT * FROM race_calendar WHERE id = ?", (race_id,)).fetchone()
    if not race:
        return []

    distance_km = race["distance_km"] or 42.195
    target_time = race["target_time"]

    # Parse target time
    target_secs = None
    if target_time:
        parts = target_time.split(":")
        if len(parts) == 3:
            target_secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            target_secs = int(parts[0]) * 60 + int(parts[1])



    objectives = []

    # 1. VO2max / VDOT target (from Daniels)
    if target_secs:
        required_vdot = compute_vdot_from_race(distance_km, target_secs)
        if required_vdot:
            # Target is the VDOT needed — no Garmin offset since we now
            # use race VDOT (not Garmin VO2max) for achievability
            objectives.append({
                "name": f"VDOT ≥{required_vdot:.0f}",
                "type": "metric",
                "target_value": round(required_vdot),
                "target_unit": "VDOT",
                "derivation_source": "auto_daniels",
                "auto_value": round(required_vdot),
            })

    # 2. Peak weekly volume (distance-based heuristic)
    if distance_km >= 40:
        volume_range = (50, 65)
    elif distance_km >= 20:
        volume_range = (40, 50)
    elif distance_km >= 10:
        volume_range = (30, 40)
    else:
        volume_range = (20, 30)

    objectives.append({
        "name": f"Peak volume {volume_range[0]}-{volume_range[1]}km/wk",
        "type": "metric",
        "target_value": volume_range[1],
        "target_unit": "km/week",
        "derivation_source": "auto_distance",
        "auto_value": volume_range[1],
    })

    # 3. Long run target (distance-based)
    if distance_km >= 40:
        long_run = 32
    elif distance_km >= 20:
        long_run = 21
    elif distance_km >= 10:
        long_run = 15
    else:
        long_run = 10

    objectives.append({
        "name": f"Long run {long_run}km",
        "type": "metric",
        "target_value": long_run,
        "target_unit": "km",
        "derivation_source": "auto_distance",
        "auto_value": long_run,
    })

    # 4. Consistency (timeline-based)
    if distance_km >= 40:
        consistency_weeks = 12
    elif distance_km >= 20:
        consistency_weeks = 8
    else:
        consistency_weeks = 6

    objectives.append({
        "name": f"Consistency {consistency_weeks}wk",
        "type": "habit",
        "target_value": consistency_weeks,
        "target_unit": "consecutive_weeks",
        "derivation_source": "auto_timeline",
        "auto_value": consistency_weeks,
    })

    # 5. Z2 compliance (always 80%+ for base)
    objectives.append({
        "name": "Z2 compliance ≥80%",
        "type": "metric",
        "target_value": 80,
        "target_unit": "%",
        "derivation_source": "auto_distance",
        "auto_value": 80,
    })

    # ── Dimension-specific targets (for fitness profile display) ──

    if target_secs and required_vdot:
        # Aerobic target: the VDOT the goal requires. The dimension's current value is now the
        # calibrated VDOT anchor (race-derived), so compare like-for-like — no +5 Garmin pad.
        aerobic_target = round(required_vdot)
        objectives.append({
            "name": "_dim_aerobic",
            "type": "metric",
            "target_value": aerobic_target,
            "target_unit": "VDOT",
            "derivation_source": "auto_daniels",
            "auto_value": aerobic_target,
        })

        # Threshold target: Z2 speed_per_bpm_z2 at required VDOT
        # Daniels easy pace for VDOT X ≈ marathon pace * 1.25
        # speed_per_bpm at easy pace ≈ (easy_m_per_min / Z2_hr)
        marathon_pace_m_per_min = (distance_km * 1000) / (target_secs / 60)
        easy_pace_m_per_min = marathon_pace_m_per_min * 0.78  # ~78% of marathon pace
        # HRs are LTHR-relative (personalised), not stale textbook absolutes (was 134 / 165).
        from fit.calibration import get_calibration_anchor as _gca
        _lthr_a = _gca(conn, "lthr")
        _lthr = float(_lthr_a.value) if _lthr_a is not None else 172.0
        z2_hr = round(0.89 * _lthr)   # Friel %LTHR Z2 ceiling (≈154 at LTHR 173), was hardcoded 134
        threshold_target = round(easy_pace_m_per_min / z2_hr, 3)
        objectives.append({
            "name": "_dim_threshold",
            "type": "metric",
            "target_value": threshold_target,
            "target_unit": "spd/bpm_z2",
            "derivation_source": "auto_daniels",
            "auto_value": threshold_target,
        })

        # Economy target: speed_per_bpm at marathon pace and race HR (~LTHR-6, the marathon
        # point of the maximal-effort schedule; LTHR-relative, was hardcoded 165).
        race_hr = round(_lthr - 6)
        economy_target = round(marathon_pace_m_per_min / race_hr, 3)
        objectives.append({
            "name": "_dim_economy",
            "type": "metric",
            "target_value": economy_target,
            "target_unit": "spd/bpm",
            "derivation_source": "auto_daniels",
            "auto_value": economy_target,
        })

        # Resilience target: drift-free distance (as fraction of race distance)
        resilience_target = round(distance_km * 0.75)  # hold pace through 75% of distance
        objectives.append({
            "name": "_dim_resilience",
            "type": "metric",
            "target_value": resilience_target,
            "target_unit": "km",
            "derivation_source": "auto_distance",
            "auto_value": resilience_target,
        })

    return objectives


def compute_achievability(conn, objectives: list[dict], days_remaining: int) -> list[dict]:
    """Compute achievability for each objective: ✓ on track / ⚠ tight / ✗ at risk.

    Adds 'achievability', 'current_value', and 'gap' to each objective dict.
    """
    profile = get_fitness_profile(conn)
    months = max(days_remaining / 30, 0.5)

    for obj in objectives:
        target = obj.get("target_value")
        unit = obj.get("target_unit", "")
        current = None
        trend_rate = None

        if "vdot" in obj["name"].lower() or "vdot" in unit.lower():
            # Use effective_vdot (race-based), not Garmin VO2max
            current = profile["effective_vdot"]
            dim = profile["aerobic"]
            trend_rate = dim.get("rate_per_month")

        elif "volume" in obj["name"].lower() or "km/week" in unit:
            # Use 4-week avg (not just latest week which may be a deload)
            row = conn.execute(
                "SELECT ROUND(AVG(run_km), 1) as avg FROM (SELECT run_km FROM weekly_agg ORDER BY week DESC LIMIT 4)"
            ).fetchone()
            current = row["avg"] if row and row["avg"] else 0
            # Safe ramp projection: ~7% per week avg (accounts for deloads)
            if current and current > 0:
                weeks = max(days_remaining / 7 - 3, 1)  # -3 for taper
                projected_peak = current * (1.07 ** weeks)
                trend_rate = (projected_peak - current) / max(months, 0.5)

        elif "long run" in obj["name"].lower():
            row = conn.execute("SELECT longest_run_km FROM weekly_agg ORDER BY week DESC LIMIT 1").fetchone()
            current = row["longest_run_km"] if row else 0
            # Long run builds ~1-2km per week safely
            if current and current > 0:
                weeks = max(days_remaining / 7 - 3, 1)
                projected_peak = current + weeks * 1.5
                trend_rate = (projected_peak - current) / max(months, 0.5)

        elif "consistency" in obj["name"].lower() or "consecutive" in unit:
            # Weeks-equivalent at the target frequency over a window as long as the
            # objective itself — so "12 weeks of consistency" still reads in weeks.
            # An ISO-week streak reset to 0 whenever a week boundary split an
            # every-other-day plan's runs 3/2, which is not a consistency failure.
            from fit.analysis import compute_sustained_weeks
            current = compute_sustained_weeks(conn, target_weeks=target)

        elif "z2" in obj["name"].lower() or "%" in unit:
            # Use 4-week rolling average (not just current week which may have only 1 run)
            row = conn.execute(
                "SELECT ROUND(AVG(z12_pct), 1) as avg FROM (SELECT z12_pct FROM weekly_agg ORDER BY week DESC LIMIT 4)"
            ).fetchone()
            current = row["avg"] if row and row["avg"] else 0

        obj["current_value"] = current
        if target and current is not None:
            gap = target - current
            obj["gap"] = round(gap, 1)

            # Achievability: on_track = already met OR within 10%.
            # tight = projected to reach with safe progression.
            # at_risk = projected won't reach in time.
            if gap <= 0:
                obj["achievability"] = "on_track"
            elif gap <= target * 0.1:
                # Within 10% of target — almost there
                obj["achievability"] = "on_track"
            elif trend_rate and trend_rate > 0:
                months_needed = gap / trend_rate
                if months_needed <= months:
                    obj["achievability"] = "tight"  # achievable but not there yet
                elif months_needed <= months * 1.3:
                    obj["achievability"] = "tight"
                else:
                    obj["achievability"] = "at_risk"
            elif "consistency" in obj["name"].lower():
                weeks_remaining = days_remaining / 7
                if current + weeks_remaining >= target:
                    obj["achievability"] = "tight" if current > 0 else "at_risk"
                else:
                    obj["achievability"] = "at_risk"
            else:
                obj["achievability"] = "at_risk"
        else:
            obj["gap"] = None
            obj["achievability"] = "unknown"

    return objectives


# ── Checkpoint Enrichment ──


def derive_checkpoint_targets(conn) -> list[dict]:
    """Compute derived target times for upcoming checkpoint races.

    For each registered race before the target, uses Riegel back-calculation:
    "To be on track for target_time at target_distance, run this distance in X."
    """
    from fit.goals import get_target_race

    target = get_target_race(conn)
    if not target or not target.get("target_time") or not target.get("distance_km"):
        return []

    def _parse_time(t):
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return 0

    target_secs = _parse_time(target["target_time"])
    target_km = target["distance_km"]
    target_date = target["date"]

    # Get upcoming registered races (excluding the target itself)
    checkpoints = conn.execute("""
        SELECT * FROM race_calendar
        WHERE date >= date('now') AND date < ? AND status IN ('registered', 'planned')
        AND id != ?
        ORDER BY date
    """, (target_date, target["id"])).fetchall()

    results = []
    for cp in checkpoints:
        cp_km = cp["distance_km"]
        if not cp_km or cp_km <= 0:
            continue

        # Riegel back-calculation: what time at cp_km corresponds to target_secs at target_km?
        derived_secs = round(target_secs * (cp_km / target_km) ** RIEGEL_EXPONENT)
        derived_vdot = compute_vdot_from_race(cp_km, derived_secs)

        days_to_cp = (date.fromisoformat(cp["date"]) - date.today()).days

        def _fmt_time(s):
            h = s // 3600
            m = (s % 3600) // 60
            sec = s % 60
            if h > 0:
                return f"{h}:{m:02d}:{sec:02d}"
            return f"{m}:{sec:02d}"

        user_target = cp["target_time"]
        user_secs = _parse_time(user_target) if user_target else None

        # Readiness signal
        if user_secs and derived_secs:
            if user_secs < derived_secs:
                signal = "aiming faster than needed ✓"
            elif user_secs <= derived_secs * 1.05:
                signal = "close to on-track pace"
            else:
                signal = "slower than on-track pace ⚠"
        else:
            signal = None

        results.append({
            "race_id": cp["id"],
            "name": cp["name"],
            "date": cp["date"],
            "distance": cp["distance"],
            "distance_km": cp_km,
            "days": days_to_cp,
            "user_target": user_target,
            "user_target_secs": user_secs,
            "derived_target": _fmt_time(derived_secs),
            "derived_target_secs": derived_secs,
            "derived_vdot": derived_vdot,
            "signal": signal,
            "target_race_name": target["name"],
        })

    return results


def update_vdot_from_race_result(conn, race_id: int) -> dict | None:
    """After a race completion, compute VDOT and update fitness context.

    Returns the readiness signal dict or None.
    """
    race = conn.execute("""
        SELECT * FROM race_calendar WHERE id = ? AND status = 'completed' AND result_time IS NOT NULL
    """, (race_id,)).fetchone()

    if not race or not race["distance_km"] or not race["result_time"]:
        return None

    def _parse_time(t):
        parts = t.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return 0

    result_secs = _parse_time(race["result_time"])
    race_vdot = compute_vdot_from_race(race["distance_km"], result_secs)

    if not race_vdot:
        return None

    # Get target race for projection
    from fit.goals import get_target_race
    target = get_target_race(conn)
    projection = None
    if target and target.get("distance_km"):
        proj_secs = vdot_to_race_time(race_vdot, target["distance_km"])
        if proj_secs:
            h = proj_secs // 3600
            m = (proj_secs % 3600) // 60
            projection = f"{h}:{m:02d}"

    return {
        "race_name": race["name"],
        "distance_km": race["distance_km"],
        "result_time": race["result_time"],
        "race_vdot": race_vdot,
        "projection": projection,
        "target_race": target["name"] if target else None,
        "message": (
            f"{race['name']} result ({race['result_time']}) → VDOT {race_vdot}"
            + (f" → {target['name']} projection: {projection}" if projection else "")
        ),
    }
