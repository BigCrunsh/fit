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

import numpy as np


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


def forecast(conn, *, avg_hr=None, goal_seconds=None, seed=0, posterior=None):
    """End-to-end goal forecast from the DB: features → fit/load → predict with overlay.

    Returns None when the model can't run (no `forecast` extra, no efforts, no posterior)
    — the caller degrades to the Phase-1 anchor headline (design Decision 7), never crashes.
    """
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

    idata = posterior if posterior is not None else _model.load_posterior()
    if idata is None:
        return None

    prior = extrapolation_prior(conn, ds.goal)
    gap = max(0.0, float(np.log(ds.goal / ds.d_max)))
    # Maximal-goal effort: avg_hr defaults to the LTHR anchor (h=0) unless supplied
    # (the maximal-marathon-HR input — an open question; re-derive vs the real LTHR).
    h = 0.0 if avg_hr is None else (avg_hr - ds.lthr) / 5.0
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

# Distance-appropriate maximal effort: sustainable HR falls with duration, so a maximal
# 5K sits well above LTHR and a marathon below it. Offsets are bpm vs LTHR → h = bpm/5
# (h is already LTHR-relative, so the schedule is independent of the LTHR value). An
# assumption (like the maximal-marathon HR), stated as such.
_STD_DISTANCES = [
    ("5K", 5.0, 10.0 / 5.0),       # ~LTHR+10
    ("10K", 10.0, 5.0 / 5.0),      # ~LTHR+5
    ("HM", 21.0975, 0.0),          # ~LTHR
    ("M", 42.195, -6.0 / 5.0),     # ~LTHR−6 (= the headline's maximal-marathon HR)
]


def derived_metrics(idata, ds, *, c, maximal_h=-1.2, extrapolation_scale=0.0, nu=4,
                    seed=0):
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
    for label, d, h_d in _STD_DISTANCES:
        x = float(np.log(d / ds.goal))
        gap = max(0.0, float(np.log(d / ds.d_max)))
        r = predict(idata, x=x, c=c, h=h_d, gap=gap,
                    extrapolation_scale=extrapolation_scale, nu=nu, seed=seed)
        equiv.append({"label": label, "distance_km": d, **r})

    return {
        "durability_beta_d": beta_d,       # lower = better; ~1.06 textbook
        "fitness_value_phi": phi,          # Δlog-time per +10 chronic units (negative = faster)
        "effort_kappa": kappa,             # Δlog-time per +5 bpm (negative = faster)
        "race_equivalency": equiv,
    }


def required_chronic_for_goal(idata, ds, *, goal_seconds, target_p=0.80,
                              maximal_h=-1.2, extrapolation_scale=0.0, nu=4, seed=0):
    """Inverse: the chronic-load level whose P(goal-ceiling) first reaches target_p.
    Turns the goal into a fitness target. Returns chronic-load units, or None if even
    very high fitness can't reach it (within the searched range)."""
    from fit.marathon.features import CHRONIC_REF, CHRONIC_SCALE

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


def trend_series(conn, idata, ds, *, days=420, step_days=14, maximal_h=-1.2,
                 extrapolation_scale=0.0, nu=4, seed=0):
    """Marathon-equivalent at maximal effort tracking chronic load over time (Panel B —
    replaces the table-based prediction-trend chart). One point per `step_days`."""
    from datetime import date, timedelta
    from fit.training_load import chronic_load
    from fit.marathon.features import CHRONIC_REF, CHRONIC_SCALE

    gap = max(0.0, float(np.log(ds.goal / ds.d_max)))
    out = []
    today = date.today()
    for back in range(days, -1, -step_days):
        d = today - timedelta(days=back)
        c = (chronic_load(conn, asof=d) - CHRONIC_REF) / CHRONIC_SCALE
        r = predict(idata, x=0.0, c=c, h=maximal_h, gap=gap,
                    extrapolation_scale=extrapolation_scale, nu=nu, seed=seed)
        out.append({"date": d.isoformat(), "median": r["median"], "lo": r["lo"], "hi": r["hi"]})
    return out
