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

from typing import NamedTuple

import numpy as np

# Maximal sustainable effort vs LTHR by distance, as a bpm offset: you hold ABOVE threshold
# for short races and progressively below it as duration grows. This is LTHR-RELATIVE (the
# model is LTHR-anchored, h = (HR−LTHR)/H_DIV) and goal-adaptive — NOT an absolute HR, so it
# tracks the athlete's threshold automatically. An input assumption (±2 bpm ≈ ±3 min at the
# marathon). Interpolated in log-distance; clamped past the endpoints.
_MAXIMAL_HR_OFFSET = [(5.0, 10.0), (10.0, 5.0), (21.0975, 0.0), (42.195, -6.0)]  # (km, bpm vs LTHR)


def maximal_effort_h(distance_km, hr_reserve=None):
    """The model `h` covariate for a MAXIMAL effort at a distance — LTHR-relative and
    distance-appropriate (≈LTHR+10 for a 5k, ≈LTHR for a half, ≈LTHR−6 for a marathon).
    Returns h = offset_bpm / H_DIV. Pass to `predict`/`derived_metrics`/`durability_panel`.

    `hr_reserve` (= MaxHR − LTHR, from the MaxHR anchor) caps the offset: you cannot hold
    above your max heart rate. It is a no-op for a high-reserve athlete (e.g. reserve 22 vs
    the +10 short-race offset) but protects the short-distance limb for a low-reserve one.
    Pass `None` to skip the cap (MaxHR uncalibrated)."""
    from fit.marathon.features import H_DIV
    pts = _MAXIMAL_HR_OFFSET
    if distance_km <= pts[0][0]:
        off = pts[0][1]
    elif distance_km >= pts[-1][0]:
        off = pts[-1][1]
    else:
        off = pts[-1][1]
        for (d1, o1), (d2, o2) in zip(pts, pts[1:]):
            if d1 <= distance_km <= d2:
                f = (np.log(distance_km) - np.log(d1)) / (np.log(d2) - np.log(d1))
                off = o1 + (o2 - o1) * f
                break
    if hr_reserve is not None:
        off = min(off, hr_reserve)
    return off / H_DIV


def _reserve(ds):
    """HR reserve (MaxHR − LTHR) for the maximal-effort cap; None when MaxHR is uncalibrated
    (then `maximal_effort_h` runs uncapped). See `maximal_effort_h`."""
    mh = getattr(ds, "max_hr", None)
    return (mh - ds.lthr) if mh else None


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
    # Maximal-goal effort: the distance-appropriate, LTHR-relative maximal HR for the goal
    # (e.g. ~LTHR−6 for a marathon, ~LTHR for a half), capped at the MaxHR reserve. An
    # explicit avg_hr overrides.
    from fit.marathon.features import H_DIV
    h = maximal_effort_h(ds.goal, _reserve(ds)) if avg_hr is None else (avg_hr - ds.lthr) / H_DIV
    res = predict(idata, x=0.0, c=_current_c(conn), h=h, gap=gap,
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

# Race-equivalency rows; the maximal-effort h for each is `maximal_effort_h(distance)`
# (the LTHR-relative, distance-appropriate schedule above).
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
    # its OWN gap vs d_max (short distances interpolate → no penalty).
    equiv = []
    for label, d in _STD_DISTANCES:
        x = float(np.log(d / ds.goal))
        gap = max(0.0, float(np.log(d / ds.d_max)))
        r = predict(idata, x=x, c=c, h=maximal_effort_h(d, _reserve(ds)), gap=gap,
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
    if maximal_h is None:
        maximal_h = maximal_effort_h(ds.goal, _reserve(ds))

    for c in np.linspace(-3.0, 5.0, 81):          # chronic-load c grid (≈ load 20..100)
        r = predict(idata, x=0.0, c=float(c), h=maximal_h, gap=max(0.0, float(np.log(ds.goal / ds.d_max))),
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
    if maximal_h is None:
        maximal_h = maximal_effort_h(ds.goal, _reserve(ds))
    a, b, phi, kappa = (_flat(idata, p) for p in ("alpha", "beta_d", "phi", "kappa"))
    bm, pm, km = (float(np.median(v)) for v in (b, phi, kappa))
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
    return {"points": points, "curve": curve, "d_max": ds.d_max, "goal": ds.goal,
            "beta_d": bm}


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

    if maximal_h is None:
        maximal_h = maximal_effort_h(ds.goal, _reserve(ds))

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
        r = predict(idata, x=0.0, c=c, h=maximal_h, gap=gap,
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
    if maximal_h is None:
        maximal_h = maximal_effort_h(ds.goal, _reserve(ds))
    b, kappa = (float(np.median(_flat(idata, p))) for p in ("beta_d", "kappa"))
    eff = ds.efforts
    out = []
    for dt, logt, x, h, d in zip(eff["date"], eff["logt"], eff["x"], eff["h"], eff["distance_km"]):
        mar_min = float(np.exp(logt - b * x - kappa * (h - maximal_h)))
        date_s = dt.date().isoformat() if hasattr(dt, "date") else str(dt)[:10]
        out.append({"date": date_s, "minutes": mar_min, "distance_km": float(d)})
    out.sort(key=lambda r: r["date"])
    return out
