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
