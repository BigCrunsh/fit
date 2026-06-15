"""Marathon forecast from the fitted posterior — predict + derived readouts.

The headline interval is **estimation uncertainty (the posterior of the mean curve) +
the extrapolation wall penalty** — NOT race-day spread (so the residual σ is deliberately
excluded; design Decision 3). P(goal) is a fitness-SUFFICIENCY ceiling, not race-day odds.

The wall penalty is applied HERE, at predict time, as a NumPy overlay (design Decision 2):
for each posterior draw, draw γ ~ HalfStudentT(ν, extrapolation_scale) and add
γ·max(0, log(d/d_max)) to the predicted log-time. It is 0 for any distance within the
observed range (interpolation), and grows with the goal/d_max gap (goal-adaptive).
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


def effort_schedule(ds):
    """(T0, beta) for the maximal-effort fade law. Returns {t0, beta, defaulted, reason}.

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
    eff = getattr(ds, "efforts", None)
    if eff is None or "run_type" not in getattr(eff, "columns", []):
        return {"t0": t0_p, "beta": beta, "defaulted": True, "reason": "no efforts"}
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
                t0_data = float(np.average(implied_t0, weights=w))
                lam = n_eff / (n_eff + EFFORT_PRIOR_PSEUDO)           # data weight vs prior
                t0 = float(np.clip(np.exp((1 - lam) * np.log(t0_p) + lam * np.log(t0_data)),
                                   *_EFFORT_T0_CLAMP))
                return {"t0": t0, "beta": beta, "defaulted": False,
                        "reason": f"{int(hard.sum())}/{len(races)} at-threshold races, "
                                  f"λ={lam:.2f} (T0_data≈{t0_data:.0f}min, β=population)"}
    return {"t0": t0_p, "beta": beta, "defaulted": True,
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


def effort_h_for_distance(idata, ds, d, *, c, extrapolation_scale=0.0, nu=4, seed=0, schedule=None):
    """Maximal-effort `h` at distance `d`, keyed on the model's OWN predicted duration via a
    two-pass coupling (design Decision 2): predict t(d) with seed h=0, recompute h from t(d),
    predict once more — the correction is <0.1 bpm because κ is small. Pass `schedule` to reuse
    one `effort_schedule(ds)` across a loop (it's d-independent)."""
    sched = schedule or effort_schedule(ds)
    t0, beta, reserve = sched["t0"], sched["beta"], _reserve(ds)
    x = float(np.log(d / ds.goal))
    gap = max(0.0, float(np.log(d / ds.d_max)))

    def _t_min(h):
        r = predict(idata, x=x, c=c, h=h, gap=gap,
                    extrapolation_scale=extrapolation_scale, nu=nu, seed=seed)
        return r["median"] / 60.0

    h = maximal_effort_h(_t_min(0.0), t0, beta, reserve)         # pass 1 from seed h=0
    h = maximal_effort_h(_t_min(h), t0, beta, reserve)           # pass 2 (converged)
    return h


def _flat(idata, name):
    return idata.posterior[name].to_numpy().flatten()


def _wall_penalty_draws(nu, scale, gap, n, rng):
    """Per-draw wall penalty (log-time): γ·gap with γ ~ HalfStudentT(ν, scale)."""
    if gap <= 0 or scale <= 0:
        return np.zeros(n)
    half_studentt = np.abs(rng.standard_t(nu, size=n)) * scale
    return half_studentt * gap


def predict(idata, *, x, c, h, gap, extrapolation_scale, nu,
            goal_seconds=None, seed=0):
    """Predicted time (seconds) at covariates (x, c, h) with the wall-penalty overlay.

    `gap` = max(0, log(distance / d_max)) — 0 within the observed range. Returns
    {median, lo, hi (90% credible), p_ceiling}. `p_ceiling` (P the time beats
    `goal_seconds`) is a fitness-sufficiency ceiling, present only when goal_seconds given.
    """
    a, b, phi, kappa = (_flat(idata, p) for p in ("alpha", "beta_d", "phi", "kappa"))
    n = a.shape[0]
    mu = a + b * x + phi * c + kappa * h            # posterior of the MEAN log-minutes
    rng = np.random.default_rng(seed)
    mu = mu + _wall_penalty_draws(nu, extrapolation_scale, gap, n, rng)
    minutes = np.exp(mu)
    secs = minutes * 60.0
    out = {
        "median": float(np.median(secs)),
        "lo": float(np.percentile(secs, 5)),
        "hi": float(np.percentile(secs, 95)),
    }
    if goal_seconds is not None:
        out["p_ceiling"] = float(np.mean(secs <= goal_seconds))
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
    h = (effort_h_for_distance(idata, ds, ds.goal, c=c, extrapolation_scale=prior["scale"],
                               nu=prior["nu"], seed=seed)
         if avg_hr is None else (avg_hr - ds.lthr) / H_DIV)
    res = predict(idata, x=0.0, c=c, h=h, gap=gap,
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
        h = effort_h_for_distance(idata, ds, d, c=c, extrapolation_scale=extrapolation_scale,
                                  nu=nu, seed=seed, schedule=sched)
        r = predict(idata, x=x, c=c, h=h, gap=gap,
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
        maximal_h = effort_h_for_distance(idata, ds, ds.goal, c=c_ref,
                                          extrapolation_scale=extrapolation_scale, nu=nu, seed=seed)
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
        mu = a + b * x + phi * c_ref + kappa * maximal_h   # draws of the mean at c_ref + maximal effort
        gap = max(0.0, float(np.log(d / ds.d_max)))
        mins = np.exp(mu + _wall_penalty_draws(nu, extrapolation_scale, gap, mu.shape[0], rng))
        curve.append({"distance_km": float(d), "median": float(np.median(mins)),
                      "lo": float(np.percentile(mins, 5)), "hi": float(np.percentile(mins, 95))})
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
        h = (maximal_h if maximal_h is not None
             else effort_h_for_distance(idata, ds, ds.goal, c=c, extrapolation_scale=extrapolation_scale,
                                        nu=nu, seed=seed, schedule=sched))
        r = predict(idata, x=0.0, c=c, h=h, gap=gap,
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
