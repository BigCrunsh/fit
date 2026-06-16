"""Marathon forecast from the fitted posterior — predict + derived readouts.

The headline interval is **estimation uncertainty (the posterior of the mean curve) +
the extrapolation wall penalty + the effort-schedule (β, T₀) uncertainty** — NOT race-day
spread (so the residual σ is deliberately excluded; design Decision 3). P(goal) is a
fitness-SUFFICIENCY ceiling, not race-day odds.

The wall penalty is applied HERE, at predict time, as a NumPy overlay (design Decision 2):
for each posterior draw, draw γ ~ HalfStudentT(ν, extrapolation_scale) and add
γ·max(0, log(d/d_max)) to the predicted log-time. It is 0 for any distance within the
observed range (interpolation), and grows with the goal/d_max gap (goal-adaptive).

Effort-schedule uncertainty (effort-schedule-uncertainty change) rides the SAME per-draw overlay:
`effort_h_for_distance(..., draws=True)` samples (β_i, log T0_i) ~ N(·) per draw → an array
`h_draws`; `predict` takes the **median from the point h** (so the headline never moves) and the
**5/95 percentiles from `h_draws`** (so the band widens). The effort draws use a SEPARATE RNG
substream from the wall penalty, so the wall draws are byte-identical regardless. The added width
grows with |log t_goal − log T0| (largest at the marathon, smallest near a half).
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

import numpy as np

# ── Duration-keyed maximal-effort schedule (design: duration-keyed-effort-schedule) ──
# offset(t) = beta·(log t − log T0)  — bpm vs LTHR; t = predicted maximal-effort DURATION (min).
# You hold ABOVE threshold for short (fast) efforts and progressively below it as duration grows.
# Keyed on duration, NOT distance, so it doesn't smuggle a fitness assumption into the effort
# covariate (the distance↔fitness confound the durability model removes). T0 (threshold-duration)
# and beta (fade slope) are POPULATION PRIORS the athlete's races update — a precision-weighted
# shrinkage estimate, weighted by recency (tracks fitness) and representativeness (longer efforts,
# nearer the marathon, count more) — shrinking to the prior when data is thin, so a single
# sub-maximal or stale race can't break it. Same prior+data treatment the durability model gives
# beta_d. LTHR-relative throughout (the model is LTHR-anchored, h = (HR−LTHR)/H_DIV).
EFFORT_T0_PRIOR_MIN = 55.0   # population threshold-sustainable duration (textbook MLSS ~30–60 min)
EFFORT_BETA_PRIOR = -6.5     # population duration–intensity fade (bpm per natural-log-unit)
EFFORT_TAU_DAYS = 450.0      # recency decay (~15 months) — recent races inform T0/beta more
EFFORT_PRIOR_PSEUDO = 1.0    # prior strength in "effective races"; data past this personalises
_EFFORT_T0_CLAMP = (20.0, 240.0)
_EFFORT_BETA_CLAMP = (-12.0, -2.0)

# ── Schedule uncertainty (design: effort-schedule-uncertainty) ──
# Attached to (beta, T0) so the forecast interval reflects "we don't know the fade exactly".
# beta_sd is a single HAND-SET prior (NOT measured): justified from the within-curve segment-slope
# spread (−6.50/−6.04/−7.63, SD≈0.8 — a floor, conflating curvature with noise) plus Riegel-exponent
# literature analogues → ~1.0–1.5. T0's SD is data-derived: a precision-weighted POSTERIOR log-SD
# blending the prior width below with the per-race scatter (see effort_schedule). The obs floor stops
# a single / identical-implied race from pinning T0 to ~0 width (the cold-start-collapse trap).
EFFORT_BETA_PRIOR_SD = 1.25        # bpm/log-unit — documented judgment-informed prior, not measured
EFFORT_T0_PRIOR_LOG_SD = 0.35      # prior log-SD on T0 (~40–80 min around the 55-min prior); WIDE at cold-start
EFFORT_T0_OBS_FLOOR_LOG = 0.15     # min per-race log-scatter so one/identical race can't pin T0 exactly


def effort_schedule(ds):
    """(T0, beta) for the maximal-effort fade law.
    Returns {t0, beta, t0_sd, beta_sd, defaulted, reason}.

    **beta** stays the population prior. The slope CANNOT be reliably fit from this data: the
    athlete's short races are mostly sub-maximal parkruns run *at* threshold (offset ≈ 0, not the
    ~+10 a maximal 5 K would show), so a weighted fit flattens to ≈ −2 to −3 and distorts the whole
    curve (validated: 5 K would read +3 instead of +10). Fitting beta is gated on a maximality flag
    (mark which races were all-out) — the Decision-4 follow-on. See the CLAUDE.md note.

    **T0** (the athlete's threshold-duration) IS data-driven: population prior updated by a
    recency- and representativeness-weighted estimate over the athlete's *at-or-above-threshold*
    races (offset ≥ 0 — a sub-threshold race was run easy and would drag T0 down spuriously).
    With beta fixed, each such race implies T0_i = exp(log t_i − offset_i/beta); T0 is the
    prior-shrunk weighted mean. Cold-start / no hard race → the prior, labelled ``defaulted``."""
    beta, t0_p = EFFORT_BETA_PRIOR, EFFORT_T0_PRIOR_MIN
    # cold-start uncertainty: beta at its prior SD; T0 at the WIDE prior log-SD (we barely know it).
    cold = {"beta_sd": EFFORT_BETA_PRIOR_SD, "t0_sd": EFFORT_T0_PRIOR_LOG_SD}
    eff = getattr(ds, "efforts", None)
    if eff is None or "run_type" not in getattr(eff, "columns", []):
        return {"t0": t0_p, "beta": beta, **cold, "defaulted": True, "reason": "no efforts"}
    races = eff[eff["run_type"] == "race"]
    if len(races) >= 1:
        dur = np.exp(races["logt"].to_numpy())            # grade-adjusted minutes (model time-space)
        offset = races["avg_hr"].to_numpy() - ds.lthr     # bpm vs LTHR
        hard = offset >= 0                                # genuine at/above-threshold (maximal) efforts
        if hard.any():
            dur, offset = dur[hard], offset[hard]
            today = date.today()
            ages = np.array([(today - d.date()).days if hasattr(d, "date") else 0.0
                             for d in races["date"][hard]], dtype=float)
            w = np.exp(-ages / EFFORT_TAU_DAYS) * (dur / dur.max())   # recency × representativeness
            n_eff = float(w.sum())
            implied_t0 = np.exp(np.log(dur) - offset / beta)          # offset = beta·(log t − log T0)
            if n_eff > 0:
                log_implied = np.log(implied_t0)
                mean_log = float(np.average(log_implied, weights=w))
                t0_data = float(np.average(implied_t0, weights=w))
                lam = n_eff / (n_eff + EFFORT_PRIOR_PSEUDO)           # data weight vs prior (MEAN shrink)
                t0 = float(np.clip(np.exp((1 - lam) * np.log(t0_p) + lam * np.log(t0_data)),
                                   *_EFFORT_T0_CLAMP))
                # σ_T0 = precision-weighted POSTERIOR log-SD: combine the prior precision with the
                # data precision of the MEAN (n_eff / per-race scatter). NOT λ·spread — λ is a mean
                # weight; applied to the SD it would collapse the band to ~0 at cold-start. The obs
                # floor keeps a single / identical-implied race from pinning T0 to zero width.
                obs_var = max(float(np.average((log_implied - mean_log) ** 2, weights=w)),
                              EFFORT_T0_OBS_FLOOR_LOG ** 2)
                prec = 1.0 / EFFORT_T0_PRIOR_LOG_SD ** 2 + n_eff / obs_var
                t0_sd = float(np.sqrt(1.0 / prec))
                return {"t0": t0, "beta": beta, "t0_sd": t0_sd, "beta_sd": EFFORT_BETA_PRIOR_SD,
                        "defaulted": False,
                        "reason": f"{int(hard.sum())}/{len(races)} at-threshold races, "
                                  f"λ={lam:.2f} (T0_data≈{t0_data:.0f}min, β=population)"}
    return {"t0": t0_p, "beta": beta, **cold, "defaulted": True,
            "reason": "population prior (no at-threshold race to anchor T0)"}


def maximal_effort_h(predicted_minutes, t0, beta, hr_reserve=None):
    """Model `h` covariate for a MAXIMAL effort of a given predicted DURATION (minutes), via the
    duration-keyed fade law offset(t) = beta·(log t − log T0). Returns h = offset_bpm / H_DIV.

    `hr_reserve` (= MaxHR − LTHR, from the MaxHR anchor) caps the offset so a maximal effort never
    exceeds MaxHR — a no-op for a high-reserve athlete but protective for a low-reserve one. Pass
    `None` to skip the cap (MaxHR uncalibrated). Callers normally go via `effort_h_for_distance`,
    which resolves `t0`/`beta` from `effort_schedule` and supplies the predicted duration."""
    from fit.marathon.features import H_DIV
    off = beta * (np.log(predicted_minutes) - np.log(t0))
    if hr_reserve is not None:
        off = min(off, hr_reserve)
    return off / H_DIV


def _reserve(ds):
    """HR reserve (MaxHR − LTHR) for the maximal-effort cap; None when MaxHR is uncalibrated
    (then the offset runs uncapped). See `maximal_effort_h`."""
    mh = getattr(ds, "max_hr", None)
    return (mh - ds.lthr) if mh else None


def effort_h_for_distance(idata, ds, d, *, c, extrapolation_scale=0.0, nu=4, seed=0,
                          schedule=None, draws=False):
    """Maximal-effort `h` at distance `d`, keyed on the model's OWN predicted duration via a
    two-pass coupling (design Decision 2): predict t(d) with seed h=0, recompute h from t(d),
    predict once more — the correction is <0.1 bpm because κ is small. Pass `schedule` to reuse
    one `effort_schedule(ds)` across a loop (it's d-independent).

    `draws=False` (default) → the scalar point `h` (pre-change behaviour). `draws=True` →
    `(h_point, h_draws)` where `h_draws` is a length-n array sampling (β_i, log T0_i) around the
    converged operating duration (effort-schedule-uncertainty); feed both into `predict` so the
    median uses the point and the interval uses the draws. The (β_i, log T0_i) RNG is a SEPARATE
    substream from the wall penalty's, so the wall draws are byte-identical with or without `draws`."""
    sched = schedule or effort_schedule(ds)
    t0, beta, reserve = sched["t0"], sched["beta"], _reserve(ds)
    x = float(np.log(d / ds.goal))
    gap = max(0.0, float(np.log(d / ds.d_max)))

    def _t_min(h):
        r = predict(idata, x=x, c=c, h=h, gap=gap,
                    extrapolation_scale=extrapolation_scale, nu=nu, seed=seed)
        return r["median"] / 60.0

    h = maximal_effort_h(_t_min(0.0), t0, beta, reserve)         # pass 1 from seed h=0
    t_star = _t_min(h)                                           # converged operating duration
    h = maximal_effort_h(t_star, t0, beta, reserve)              # pass 2 — point h at t_star
    if not draws:
        return h
    # Per-draw effort uncertainty: sample (β_i, log T0_i) around the SAME operating duration t_star
    # that defines the point h, so σ=0 collapses the draws to h EXACTLY (byte-identical interval).
    # One scalar 2-pass, NOT a nested per-draw 2-pass — κ is small so the coupling barely moves.
    from fit.marathon.features import H_DIV
    n = _flat(idata, "alpha").shape[0]
    # SEPARATE substream from the wall penalty (which uses default_rng(seed) inside predict): spawn a
    # child SeedSequence so the effort draws are deterministic yet never shift the wall draw order.
    eff_rng = np.random.default_rng(seed).spawn(1)[0]
    beta_i = beta + sched["beta_sd"] * eff_rng.standard_normal(n)
    logt0_i = np.log(t0) + sched["t0_sd"] * eff_rng.standard_normal(n)
    off = beta_i * (np.log(t_star) - logt0_i)                    # β_i, log T0_i drawn independently
    if reserve is not None:
        off = np.minimum(off, reserve)                           # vectorised cap (not scalar min)
    return h, off / H_DIV


def _flat(idata, name):
    return idata.posterior[name].to_numpy().flatten()


def _wall_penalty_draws(nu, scale, gap, n, rng):
    """Per-draw wall penalty (log-time): γ·gap with γ ~ HalfStudentT(ν, scale)."""
    if gap <= 0 or scale <= 0:
        return np.zeros(n)
    half_studentt = np.abs(rng.standard_t(nu, size=n)) * scale
    return half_studentt * gap


def predict(idata, *, x, c, h, gap, extrapolation_scale, nu,
            goal_seconds=None, seed=0, h_draws=None):
    """Predicted time (seconds) at covariates (x, c, h) with the wall-penalty overlay.

    `gap` = max(0, log(distance / d_max)) — 0 within the observed range. Returns
    {median, lo, hi (90% credible), p_ceiling}. `p_ceiling` (P the time beats
    `goal_seconds`) is a fitness-sufficiency ceiling, present only when goal_seconds given.

    `h` is the POINT effort and drives the **median** (so the headline never moves). `h_draws`
    (optional length-n array; effort-schedule-uncertainty) is the per-draw effort and drives the
    **interval** (5/95 percentiles + p_ceiling), so (β, T0) uncertainty widens the band without
    shifting the median. `h_draws=None` → both use `h` (the pre-change behaviour, exactly).
    """
    a, b, phi, kappa = (_flat(idata, p) for p in ("alpha", "beta_d", "phi", "kappa"))
    n = a.shape[0]
    rng = np.random.default_rng(seed)
    base = a + b * x + phi * c + _wall_penalty_draws(nu, extrapolation_scale, gap, n, rng)
    secs_med = np.exp(base + kappa * h) * 60.0                              # point effort → median
    secs_int = np.exp(base + kappa * (h if h_draws is None else h_draws)) * 60.0  # per-draw → interval
    out = {
        "median": float(np.median(secs_med)),
        "lo": float(np.percentile(secs_int, 5)),
        "hi": float(np.percentile(secs_int, 95)),
    }
    if goal_seconds is not None:
        out["p_ceiling"] = float(np.mean(secs_int <= goal_seconds))
    return out


class ForecastContext(NamedTuple):
    """The three expensive shared inputs every forecast consumer needs: the fitted
    posterior, the effort dataset, and the extrapolation prior. Built once via
    `forecast_context` so the dashboard/CLI/MCP don't each re-read the zarr posterior and
    re-run the feature SQL."""
    idata: object      # fitted posterior (arviz InferenceData)
    ds: object         # EffortDataset
    prior: dict        # extrapolation prior {scale, nu, shrink, reason, defaulted}


# Single-entry cache keyed by CONNECTION IDENTITY (sqlite3.Connection isn't weak-referenceable).
# One report build shares one open connection across all section builders, so the first call
# loads and the rest hit the cache (collapsing ~3× posterior reads + feature SQL into one). A
# fresh connection — a new build, or the MCP's per-call connection after a sync refit — has a
# different identity, so it recomputes and never serves stale results. We hold a strong ref to
# the connection (not id()) so identity can never be recycled onto a different object.
_CTX_CACHE: dict = {"conn": None, "ctx": None}


def forecast_context(conn) -> "ForecastContext | None":
    """Load the shared forecast inputs (posterior + efforts + extrapolation prior) ONCE per
    connection. Returns None when the model can't run (no `forecast` extra, no efforts, no
    posterior) — every caller degrades to the Phase-1 anchor headline, never crashes."""
    if _CTX_CACHE["conn"] is conn:
        return _CTX_CACHE["ctx"]
    ctx = _build_forecast_context(conn)
    _CTX_CACHE["conn"] = conn
    _CTX_CACHE["ctx"] = ctx
    return ctx


def _build_forecast_context(conn) -> "ForecastContext | None":
    try:
        from fit.marathon.features import extract_efforts
        from fit.marathon.preparedness import extrapolation_prior
        from fit.marathon import model as _model
    except Exception:
        return None
    try:
        ds = extract_efforts(conn)
    except ValueError:
        return None
    idata = _model.load_posterior()
    if idata is None:
        return None
    return ForecastContext(idata=idata, ds=ds, prior=extrapolation_prior(conn, ds.goal))


def forecast(conn, *, avg_hr=None, goal_seconds=None, seed=0, posterior=None):
    """End-to-end goal forecast from the DB: features → fit/load → predict with overlay.

    Returns None when the model can't run (no `forecast` extra, no efforts, no posterior)
    — the caller degrades to the Phase-1 anchor headline (design Decision 7), never crashes.
    `posterior` overrides the cached/on-disk posterior (the CLI refit path passes a fresh fit).
    """
    ctx = forecast_context(conn)
    if ctx is None:
        return None
    ds, prior = ctx.ds, ctx.prior
    idata = posterior if posterior is not None else ctx.idata

    gap = max(0.0, float(np.log(ds.goal / ds.d_max)))
    c = _current_c(conn)
    # Maximal-goal effort: the duration-keyed, LTHR-relative maximal HR for the goal (read off the
    # model's own predicted time at the goal, capped at the MaxHR reserve). An explicit avg_hr overrides.
    from fit.marathon.features import H_DIV
    if avg_hr is None:
        h, h_draws = effort_h_for_distance(idata, ds, ds.goal, c=c, extrapolation_scale=prior["scale"],
                                           nu=prior["nu"], seed=seed, draws=True)
    else:
        h, h_draws = (avg_hr - ds.lthr) / H_DIV, None   # explicit HR is certain → no effort-schedule spread
    res = predict(idata, x=0.0, c=c, h=h, h_draws=h_draws, gap=gap,
                  extrapolation_scale=prior["scale"], nu=prior["nu"],
                  goal_seconds=goal_seconds, seed=seed)
    res["extrapolation"] = prior
    res["goal"] = ds.goal
    res["d_max"] = ds.d_max
    res["gap"] = gap
    return res


def _current_c(conn):
    """Today's fitness covariate c from the shared chronic-load primitive."""
    from fit.training_load import chronic_load
    from fit.marathon.features import CHRONIC_REF, CHRONIC_SCALE
    return (chronic_load(conn) - CHRONIC_REF) / CHRONIC_SCALE


# ── Derived readouts (the metrics the model unlocks beyond the headline) ──

# Race-equivalency rows; the maximal-effort h for each is duration-keyed via
# `effort_h_for_distance` (the schedule resolved once and reused across the table).
_STD_DISTANCES = [("5K", 5.0), ("10K", 10.0), ("HM", 21.0975), ("M", 42.195)]


def derived_metrics(idata, ds, *, c, extrapolation_scale=0.0, nu=4, seed=0):
    """Scalar readouts from the posterior (design §11): durability β_d, fitness value φ,
    effort exchange κ, and a live race-equivalency table at today's fitness.

    Each carries a prior-vs-data movement flag (Decision 5) so a prior-dominated
    coefficient is never shown as a measured personal trait.
    """
    from fit.marathon.model import PRIOR_BETA_D, PRIOR_PHI, PRIOR_KAPPA

    def _summ(name, prior):
        v = _flat(idata, name)
        med, lo, hi = (float(np.median(v)), float(np.percentile(v, 5)),
                       float(np.percentile(v, 95)))
        # prior-dominated when the posterior median sits within ~1 prior-SD of the prior
        # mean AND the posterior hasn't tightened much past the prior width.
        prior_mu, prior_sd = prior
        dominated = abs(med - prior_mu) < prior_sd and float(np.std(v)) > 0.6 * prior_sd
        return {"median": med, "lo": lo, "hi": hi, "prior_dominated": dominated}

    beta_d = _summ("beta_d", PRIOR_BETA_D)
    phi = _summ("phi", PRIOR_PHI)
    kappa = _summ("kappa", PRIOR_KAPPA)

    # race-equivalency at today's fitness + maximal effort, each distance penalised by
    # its OWN gap vs d_max (short distances interpolate → no penalty). The duration-keyed
    # maximal h is per-distance; resolve the schedule once and reuse it across the table.
    sched = effort_schedule(ds)
    equiv = []
    for label, d in _STD_DISTANCES:
        x = float(np.log(d / ds.goal))
        gap = max(0.0, float(np.log(d / ds.d_max)))
        h, h_draws = effort_h_for_distance(idata, ds, d, c=c, extrapolation_scale=extrapolation_scale,
                                           nu=nu, seed=seed, schedule=sched, draws=True)
        r = predict(idata, x=x, c=c, h=h, h_draws=h_draws, gap=gap,
                    extrapolation_scale=extrapolation_scale, nu=nu, seed=seed)
        equiv.append({"label": label, "distance_km": d, **r})

    return {
        "durability_beta_d": beta_d,       # lower = better; ~1.06 textbook
        "fitness_value_phi": phi,          # Δlog-time per +10 chronic units (negative = faster)
        "effort_kappa": kappa,             # Δlog-time per +5 bpm (negative = faster)
        "race_equivalency": equiv,
    }


def required_chronic_for_goal(idata, ds, *, goal_seconds, target_p=0.80,
                              maximal_h=None, extrapolation_scale=0.0, nu=4, seed=0):
    """Inverse: the chronic-load level whose P(goal-ceiling) first reaches target_p.
    Turns the goal into a fitness target. Returns chronic-load units, or None if even
    very high fitness can't reach it (within the searched range)."""
    from fit.marathon.features import CHRONIC_REF, CHRONIC_SCALE
    sched = effort_schedule(ds) if maximal_h is None else None  # duration-keyed h is c-dependent
    gap = max(0.0, float(np.log(ds.goal / ds.d_max)))

    for c in np.linspace(-3.0, 5.0, 81):          # chronic-load c grid (≈ load 20..100)
        h = (maximal_h if maximal_h is not None
             else effort_h_for_distance(idata, ds, ds.goal, c=float(c),
                                        extrapolation_scale=extrapolation_scale, nu=nu,
                                        seed=seed, schedule=sched))
        r = predict(idata, x=0.0, c=float(c), h=h, gap=gap,
                    extrapolation_scale=extrapolation_scale, nu=nu, goal_seconds=goal_seconds, seed=seed)
        if r["p_ceiling"] >= target_p:
            return {"c": float(c), "chronic_load": float(c * CHRONIC_SCALE + CHRONIC_REF),
                    "target_p": target_p}
    return None


def influence(idata, ds):
    """Per-effort leave-one-out influence via PSIS-LOO Pareto-k (design Decision 8).

    Flags efforts the headline leans on (k above arviz's adaptive good_k), so no single
    race silently owns the forecast. Returns rows sorted by k desc. Requires a fitted
    idata with a log_likelihood group.
    """
    import warnings
    import arviz as az

    with warnings.catch_warnings():  # the Pareto-k>0.7 warning IS the signal we surface
        warnings.simplefilter("ignore")
        loo = az.loo(idata, pointwise=True)
    k = np.asarray(loo.pareto_k).flatten()
    good_k = float(getattr(loo, "good_k", 0.7))
    eff = ds.efforts.reset_index(drop=True)
    cols = set(eff.columns)
    rows = []
    for i, kv in enumerate(k):
        def _get(col):
            return eff.iloc[i][col] if (i < len(eff) and col in cols) else None
        dt = _get("date")
        date_s = dt.date().isoformat() if hasattr(dt, "date") else (str(dt) if dt is not None else None)
        dist = _get("distance_km")
        rows.append({
            "index": i,
            "id": _get("id"),
            "date": date_s,
            "distance_km": (float(dist) if dist is not None else None),
            "pareto_k": float(kv),
            "influential": bool(kv > good_k),
        })
    rows.sort(key=lambda d: d["pareto_k"], reverse=True)
    return {"good_k": good_k, "efforts": rows}


def durability_panel(idata, ds, *, c_ref=0.0, maximal_h=None, extrapolation_scale=0.0,
                     nu=4, n_grid=60, seed=0):
    """Data for Panel A (marathon_v2) — the durability collapse.

    Every effort is normalised to a common fitness (`c_ref`) and maximal effort
    (`maximal_h`) by removing φ·(c−c_ref) and κ·(h−maximal_h), so once fitness and effort
    are netted out the points collapse onto ONE power law of slope β_d. Returns per-effort
    points (km, normalised minutes, colour by distance), the fitted curve, and the 90%
    band that fans out past `d_max` via the wall penalty (the grey extrapolation band).

    **Pass `c_ref = today's fitness c`** so the curve's goal point equals the headline
    forecast (dashboard consistency) — at c_ref=0 it's the reference-fitness curve, which
    would disagree with a current-fitness headline.
    """
    if maximal_h is None:                       # goal's maximal-effort h at the reference fitness
        maximal_h, maximal_h_draws = effort_h_for_distance(
            idata, ds, ds.goal, c=c_ref, extrapolation_scale=extrapolation_scale,
            nu=nu, seed=seed, draws=True)       # per-draw normaliser → effort uncertainty in the band
    else:
        maximal_h_draws = None                  # explicit normaliser → band fans via the wall only
    a, b, phi, kappa = (_flat(idata, p) for p in ("alpha", "beta_d", "phi", "kappa"))
    am, bm, pm, km = (float(np.median(v)) for v in (a, b, phi, kappa))
    eff = ds.efforts
    points = [
        {"distance_km": float(d),
         "minutes": float(np.exp(lt - pm * (c - c_ref) - km * (h - maximal_h)))}
        for d, lt, c, h in zip(eff["distance_km"], eff["logt"], eff["c"], eff["h"])
    ]
    lo_d = max(2.5, float(eff["distance_km"].min()) * 0.9)
    grid = np.exp(np.linspace(np.log(lo_d), np.log(ds.goal * 1.02), n_grid))
    rng = np.random.default_rng(seed)
    curve = []
    for d in grid:
        x = np.log(d / ds.goal)
        gap = max(0.0, float(np.log(d / ds.d_max)))
        base = a + b * x + phi * c_ref + _wall_penalty_draws(nu, extrapolation_scale, gap, a.shape[0], rng)
        mins_med = np.exp(base + kappa * maximal_h)        # point effort → median (matches the headline)
        mins_int = np.exp(base + kappa * (maximal_h if maximal_h_draws is None else maximal_h_draws))
        curve.append({"distance_km": float(d), "median": float(np.median(mins_med)),
                      "lo": float(np.percentile(mins_int, 5)), "hi": float(np.percentile(mins_int, 95))})
    # Most-recent effort (a temporal reference, marked in every panel) + the β_d slope triangle.
    dts = [str(x)[:10] for x in eff["date"]] if "date" in eff.columns else [None] * len(points)
    recent = points[max(range(len(dts)), key=lambda k: dts[k] or "")] if any(dts) else None
    dlo = float(eff["distance_km"].min())
    d1 = float(np.exp(np.log(dlo) + 0.15 * (np.log(ds.goal) - np.log(dlo))))
    d2 = d1 * 2.0
    def _ty(d):
        return float(np.exp(am + bm * np.log(d / ds.goal) + pm * c_ref + km * maximal_h))
    triangle = {"x1": d1, "x2": d2, "y1": _ty(d1), "y2": _ty(d2),
                "run": "×2 dist", "rise": "×%.2f time = 2^β_d (β_d %.2f)" % (2 ** bm, bm)}
    return {"points": points, "curve": curve, "d_max": ds.d_max, "goal": ds.goal,
            "beta_d": bm, "recent": recent, "triangle": triangle}


def _coeff_panel(idata, ds, *, covariate, c_ref, maximal_h, n_grid=40):
    """Added-variable (partial-regression) panel for one model coefficient — the Bayesian-honest
    way to "see a slope as a slope" (durability-param-panels).

    The model is `mu = α + β_d·x + φ·c + κ·h`. To isolate one covariate we net the OTHER two out
    of each effort's log-time, leaving partial-residual points whose trend is that coefficient;
    the fitted line is the posterior mean at the goal distance + the operating values of the
    netted covariates, with a 5–95% HDI ribbon from posterior draws (uncertainty is the figure).

    covariate ∈ {"fitness" (→ φ, x-axis = CTL), "effort" (→ κ, x-axis = bpm above LTHR)}.
    β_d already has `durability_panel` (distance axis). All three share a log-time y-axis so the
    slope reads straight and the panels are comparable. Points are netted at posterior medians
    (illustrative scatter); the line + ribbon carry the posterior. Returns None if the model is
    not usable.
    """
    from fit.marathon.features import CHRONIC_REF, CHRONIC_SCALE, H_DIV
    a, b, phi, kappa = (_flat(idata, p) for p in ("alpha", "beta_d", "phi", "kappa"))
    am, bm, pm, km = (float(np.median(v)) for v in (a, b, phi, kappa))
    eff = ds.efforts
    dist = np.asarray(eff["distance_km"], float)
    cc, hh, lt = np.asarray(eff["c"], float), np.asarray(eff["h"], float), np.asarray(eff["logt"], float)
    xlog = np.log(dist / ds.goal)                       # distance term per effort
    dates = [str(d)[:10] for d in eff["date"]] if "date" in eff.columns else [None] * len(dist)

    if covariate == "fitness":
        pts_x = cc * CHRONIC_SCALE + CHRONIC_REF                         # CTL
        pts_y = np.exp(lt - bm * xlog - km * (hh - maximal_h))           # net out distance + effort
        gv = np.linspace(cc.min() - 0.5, cc.max() + 0.5, n_grid)
        grid_x = gv * CHRONIC_SCALE + CHRONIC_REF
        mu_grid = [a + phi * c + kappa * maximal_h for c in gv]          # at goal distance (x=0)
        x_ref = c_ref * CHRONIC_SCALE + CHRONIC_REF
    elif covariate == "effort":
        pts_x = hh * H_DIV                                               # bpm above LTHR
        pts_y = np.exp(lt - bm * xlog - pm * (cc - c_ref))              # net out distance + fitness
        gv = np.linspace(hh.min() - 0.3, hh.max() + 0.3, n_grid)
        grid_x = gv * H_DIV
        mu_grid = [a + phi * c_ref + kappa * h for h in gv]             # at goal distance + current fitness
        x_ref = maximal_h * H_DIV                                        # the assumed race effort
    else:
        raise ValueError(f"unknown covariate {covariate!r}")

    # Each point carries its distance so the chart colours it by distance (matching the collapse).
    points = [{"x": float(x), "minutes": float(y), "d": round(float(dd), 1)}
              for x, y, dd in zip(pts_x, pts_y, dist)]
    line, lo, hi = [], [], []
    for xv, mu in zip(grid_x, mu_grid):
        mins = np.exp(mu)
        line.append({"x": float(xv), "minutes": float(np.median(mins))})
        lo.append({"x": float(xv), "minutes": float(np.percentile(mins, 5))})
        hi.append({"x": float(xv), "minutes": float(np.percentile(mins, 95))})

    # Slope triangle (rise/run on the fitted line) — the intuitive "this IS the slope":
    # anchored low in range, run = one natural unit of the covariate, rise = the marathon impact.
    if covariate == "fitness":
        c1 = float(cc.min() + 0.2 * (cc.max() - cc.min()))
        c2 = c1 + 1.0
        ty1 = float(np.exp(am + pm * c1 + km * maximal_h))
        ty2 = float(np.exp(am + pm * c2 + km * maximal_h))
        tri = {"x1": c1 * CHRONIC_SCALE + CHRONIC_REF, "x2": c2 * CHRONIC_SCALE + CHRONIC_REF,
               "y1": ty1, "y2": ty2, "run": "+10 CTL", "rise": "%+.1f min" % (ty2 - ty1)}
    else:  # effort
        h1 = float(hh.min() + 0.2 * (hh.max() - hh.min()))
        h2 = h1 + 1.0
        ty1 = float(np.exp(am + pm * c_ref + km * h1))
        ty2 = float(np.exp(am + pm * c_ref + km * h2))
        tri = {"x1": h1 * H_DIV, "x2": h2 * H_DIV, "y1": ty1, "y2": ty2,
               "run": "+5 bpm", "rise": "%+.1f%%" % ((ty2 / ty1 - 1) * 100)}

    recent = None      # the most-recent effort — a temporal reference (red ring) marked in every panel
    if any(d is not None for d in dates):
        ri = max(range(len(dates)), key=lambda k: dates[k] or "")
        recent = {"x": float(pts_x[ri]), "y": float(pts_y[ri])}

    return {"points": points, "line": line, "lo": lo, "hi": hi, "x_ref": float(x_ref),
            "triangle": tri, "recent": recent, "dmin": float(dist.min()), "goal": float(ds.goal)}


def fitness_panel(idata, ds, *, c_ref, maximal_h, n_grid=40):
    """φ panel — marathon-equivalent time vs fitness (CTL); slope = φ. See `_coeff_panel`."""
    return _coeff_panel(idata, ds, covariate="fitness", c_ref=c_ref, maximal_h=maximal_h, n_grid=n_grid)


def effort_panel(idata, ds, *, c_ref, maximal_h, n_grid=40):
    """κ panel — marathon-equivalent time vs effort (bpm above LTHR); slope = κ. See `_coeff_panel`."""
    return _coeff_panel(idata, ds, covariate="effort", c_ref=c_ref, maximal_h=maximal_h, n_grid=n_grid)


def effort_schedule_panel(idata, ds, *, c=0.0, extrapolation_scale=0.0, nu=4, seed=0, n_grid=48):
    """Data for the effort-schedule inspection panel (effort-schedule-uncertainty, Decision 5).

    Visualises the maximal-effort fade law `offset(t) = β·(log t − log T0)` in its OWN coordinates —
    HR relative to LTHR (bpm) vs effort DURATION (minutes) — so the otherwise-hidden effort
    assumption (the `h` covariate the forecast leans on) is auditable. Returns:
      - `line`:  median fade `[{x: duration_min, y: offset_bpm}]` across the plotted duration range
      - `lo`/`hi`: the 90% `(σ_β, σ_T0)` band, `±1.645·sqrt((log t−log T0)²·σ_β² + β²·σ_logT0²)`
      - `dots`:  race efforts `[{x, y, d, date, hard}]` — `hard` = at/above-threshold (offset≥0,
        the efforts that anchor T0); sub-threshold parkruns (offset<0) are the ones a fitted slope
        would flatten on, so the panel shows WHY β is the population prior, not a fit
      - `t0`/`t0_sd`/`beta`/`defaulted`: the anchor + slope + T0's log-SD + bare-prior flag
      - `markers`: 5K/10K/HM/M at their MODEL-PREDICTED durations `[{label, x, y}]` (so they agree
        with Panel A/B; `y` is the model's capped maximal `h·H_DIV`) — the M marker lands far right
        where the band is widest, the visual punch line
      - `triangle`/`recent`/`n_hard`: the β slope triangle, most-recent-hard-effort ring, hard count

    The band is estimation uncertainty of the ASSUMED maximal-effort HR (bpm) — NOT race-day HR
    variability, and NOT comparable to the minutes interval on the trend chart.
    """
    from fit.marathon.features import H_DIV
    sched = effort_schedule(ds)
    t0, beta, beta_sd, t0_sd = sched["t0"], sched["beta"], sched["beta_sd"], sched["t0_sd"]
    eff = ds.efforts
    races = eff[eff["run_type"] == "race"] if "run_type" in getattr(eff, "columns", []) else eff.iloc[0:0]

    # Race-effort dots in (duration, offset) space; hard = genuine at/above-threshold effort.
    dots = []
    for _, r in races.iterrows():
        off = float(r["avg_hr"] - ds.lthr)
        dt = r["date"]
        date_s = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]
        dots.append({"x": float(np.exp(r["logt"])), "y": off, "d": float(r["distance_km"]),
                     "date": date_s, "hard": bool(off >= 0)})

    # Standard distances at their MODEL-PREDICTED maximal-effort durations (point estimates, so the
    # markers agree with the race-equivalency table and Panels A/B; the offset is the capped h·H_DIV).
    markers = []
    for label, d in _STD_DISTANCES:
        x = float(np.log(d / ds.goal)); gap = max(0.0, float(np.log(d / ds.d_max)))
        h = effort_h_for_distance(idata, ds, d, c=c, extrapolation_scale=extrapolation_scale,
                                  nu=nu, seed=seed, schedule=sched)
        t_pred = predict(idata, x=x, c=c, h=h, gap=gap, extrapolation_scale=extrapolation_scale,
                         nu=nu, seed=seed)["median"] / 60.0
        markers.append({"label": label, "x": float(t_pred), "y": float(h * H_DIV)})

    # Duration grid: a touch below the shortest data to a touch past the marathon marker.
    durs = [dd["x"] for dd in dots] + [m["x"] for m in markers]
    lo_d, hi_d = max(5.0, min(durs) * 0.9), max(durs) * 1.05
    grid = np.exp(np.linspace(np.log(lo_d), np.log(hi_d), n_grid))
    line, lo, hi = [], [], []
    for t in grid:
        dl = float(np.log(t) - np.log(t0))
        off = beta * dl
        sd = float(np.sqrt(dl ** 2 * beta_sd ** 2 + beta ** 2 * t0_sd ** 2))   # offset SD (bpm)
        line.append({"x": float(t), "y": float(off)})
        lo.append({"x": float(t), "y": float(off - 1.645 * sd)})
        hi.append({"x": float(t), "y": float(off + 1.645 * sd)})

    # β slope triangle (rise/run on the fade line): run = ×2 duration, rise = β·log2 bpm.
    d1 = float(np.exp(np.log(lo_d) + 0.15 * (np.log(hi_d) - np.log(lo_d)))); d2 = d1 * 2.0
    triangle = {"x1": d1, "x2": d2,
                "y1": float(beta * (np.log(d1) - np.log(t0))),
                "y2": float(beta * (np.log(d2) - np.log(t0))),
                "run": "×2 duration", "rise": "%.1f bpm (β)" % (beta * np.log(2.0))}

    hard_dots = [dd for dd in dots if dd["hard"]]
    recent = None
    if hard_dots:
        rd = max(hard_dots, key=lambda dd: dd["date"] or "")
        recent = {"x": rd["x"], "y": rd["y"]}

    return {"line": line, "lo": lo, "hi": hi, "dots": dots, "markers": markers,
            "t0": float(t0), "t0_sd": float(t0_sd), "beta": float(beta),
            "defaulted": bool(sched["defaulted"]), "triangle": triangle, "recent": recent,
            "n_hard": int(len(hard_dots))}


def residuals(idata, ds):
    """Day-quality residual per effort: observed log-time − model-predicted mean, with
    distance/fitness/effort netted out (design §11 G). A cleaner correlation input than
    raw pace — a temperature/sleep effect is no longer confounded by how fit/long each
    effort was. Returns the efforts frame with `predicted_logt` + `residual` columns
    (positive residual = slower than expected = a worse day)."""
    a, b, phi, kappa = (float(np.mean(_flat(idata, p))) for p in ("alpha", "beta_d", "phi", "kappa"))
    eff = ds.efforts.copy()
    eff["predicted_logt"] = a + b * eff["x"] + phi * eff["c"] + kappa * eff["h"]
    eff["residual"] = eff["logt"] - eff["predicted_logt"]
    return eff


def trend_series(conn, idata, ds, *, days=420, step_days=14, maximal_h=None,
                 extrapolation_scale=0.0, nu=4, seed=0):
    """Goal-equivalent at maximal effort tracking chronic load over time (Panel B —
    replaces the table-based prediction-trend chart). One point per `step_days`."""
    import pandas as pd
    from datetime import date, timedelta
    from fit.training_load import DAILY_LOAD_SQL, chronic_load_before
    from fit.marathon.features import CHRONIC_REF, CHRONIC_SCALE

    sched = effort_schedule(ds) if maximal_h is None else None  # duration-keyed h is c-dependent

    gap = max(0.0, float(np.log(ds.goal / ds.d_max)))
    # Load daily loads once; chronic_load_before is pure (no per-step full-table read).
    dl = pd.read_sql_query(DAILY_LOAD_SQL, conn, parse_dates=["date"])
    day_ord = dl["date"].map(pd.Timestamp.toordinal).to_numpy() if not dl.empty else np.array([])
    day_load = dl["load"].fillna(0.0).to_numpy() if not dl.empty else np.array([])
    out = []
    today = date.today()
    for back in range(days, -1, -step_days):
        d = today - timedelta(days=back)
        c = (chronic_load_before(d.toordinal(), day_ord, day_load) - CHRONIC_REF) / CHRONIC_SCALE
        # σ_T0 is held at today's value (the schedule is resolved once and reused across weeks, like
        # the existing point path); the per-step h_draws widens each step's band identically.
        if maximal_h is not None:
            h, h_draws = maximal_h, None
        else:
            h, h_draws = effort_h_for_distance(idata, ds, ds.goal, c=c, extrapolation_scale=extrapolation_scale,
                                               nu=nu, seed=seed, schedule=sched, draws=True)
        r = predict(idata, x=0.0, c=c, h=h, h_draws=h_draws, gap=gap,
                    extrapolation_scale=extrapolation_scale, nu=nu, seed=seed)
        out.append({"date": d.isoformat(), "median": r["median"], "lo": r["lo"], "hi": r["hi"]})
    return out


def marathon_equiv_points(idata, ds, *, maximal_h=None):
    """Per-effort goal-equivalent over TIME — the coloured dots of Panel B (marathon_v2).

    Each effort is projected to the goal distance at a maximal effort by removing distance
    (β_d·x) and the effort delta (κ·(h−maximal_h)) but **keeping its fitness-of-the-day**, so
    the dots scatter around the fitness-tracking median line and reveal which efforts the
    forecast leans on. Returns `[{date, minutes, distance_km}]` sorted by date; colour each by
    `distance_km` (RdYlBu_r) to match Panel A. Minutes so it shares Panel B's H:MM axis."""
    if maximal_h is None:                       # goal's maximal-effort h (reference-fitness normaliser)
        maximal_h = effort_h_for_distance(idata, ds, ds.goal, c=0.0)
    b, kappa = (float(np.median(_flat(idata, p))) for p in ("beta_d", "kappa"))
    eff = ds.efforts
    out = []
    for dt, logt, x, h, d in zip(eff["date"], eff["logt"], eff["x"], eff["h"], eff["distance_km"]):
        mar_min = float(np.exp(logt - b * x - kappa * (h - maximal_h)))
        date_s = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]
        out.append({"date": date_s, "minutes": mar_min, "distance_km": float(d)})
    out.sort(key=lambda r: r["date"])
    return out
