"""Bayesian marathon-durability model — fit, diagnose, cache. PyMC imported lazily.

    log(t_i) = α + β_d·x_i + φ·c_i + κ·h_i + StudentT(ν, 0, σ)

δ is dropped (design Decision 1). The extrapolation **wall penalty is NOT in the graph**
— it is a predict-time overlay (`predict.py` / `preparedness.py`), because every observed
effort has d ≤ d_max so the likelihood never sees it; putting it in the model would only
pollute ESS/r̂ (design Decision 2). Sampler: nutpie. Posterior cached as a zarr store.

API note (verified against pymc 6.0.1 / arviz 1.1.0): intervals come from posterior
PERCENTILES, not `az.summary` HDI columns (renamed to `eti*` in arviz 1.x); the cache is
zarr (arviz 1.x `to_netcdf` needs a C backend we don't ship). See design Decision 8.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

import numpy as np

from fit.marathon.features import EffortDataset, extract_efforts

logger = logging.getLogger(__name__)

POSTERIOR_PATH = Path.home() / ".fit" / "marathon_posterior.zarr"
PARAMS = ("alpha", "beta_d", "phi", "kappa", "sigma", "nu")

# Weakly-to-mildly informative priors (handover §3). Slope priors are deliberately tight
# (a >5% effect per unit is implausible) — so a prior-sensitivity re-fit is required (D5).
PRIOR_BETA_D = (1.06, 0.05)   # Riegel-centred durability exponent
PRIOR_PHI = (0.0, 0.05)       # fitness: Δ log-time per +10 chronic-load units
PRIOR_KAPPA = (0.0, 0.05)     # effort: Δ log-time per +5 bpm vs LTHR
PRIOR_SIGMA = 0.06            # HalfNormal scale
PRIOR_NU = (2.0, 0.1)         # Gamma(α,β) — Student-T robustness


def build_model(ds: EffortDataset):
    """Construct the PyMC model from an EffortDataset (no sampling)."""
    import pymc as pm

    eff = ds.efforts
    x, c, h, logt = (eff[k].to_numpy() for k in ("x", "c", "h", "logt"))
    # α = log-time at the goal distance (x=0), reference fitness (c=0), effort=LTHR (h=0).
    # Centre on a crude goal-time guess (~5.5 min/km); the data identifies α tightly, so
    # the centre barely matters (wide sd).
    alpha_mu = float(np.log(ds.goal * 5.5))
    with pm.Model() as model:
        alpha = pm.Normal("alpha", alpha_mu, 0.5)
        beta_d = pm.Normal("beta_d", *PRIOR_BETA_D)
        phi = pm.Normal("phi", *PRIOR_PHI)
        kappa = pm.Normal("kappa", *PRIOR_KAPPA)
        sigma = pm.HalfNormal("sigma", PRIOR_SIGMA)
        nu = pm.Gamma("nu", *PRIOR_NU)
        mu = alpha + beta_d * x + phi * c + kappa * h
        pm.StudentT("y", nu=nu, mu=mu, sigma=sigma, observed=logt)
    return model


def diagnostics(idata) -> dict:
    """Convergence gate (design Decision 8): divergences, r̂, ESS. Uses az.summary only
    for the stable r_hat/ess_* columns (NOT the renamed interval columns)."""
    import arviz as az

    summary = az.summary(idata, var_names=list(PARAMS))
    n_div = int(idata.sample_stats["diverging"].sum())
    max_rhat = float(summary["r_hat"].max())
    min_ess = float(min(summary["ess_bulk"].min(), summary["ess_tail"].min()))
    return {
        "divergences": n_div,
        "max_rhat": max_rhat,
        "min_ess": min_ess,
        "passed": n_div == 0 and max_rhat < 1.01 and min_ess > 400,
    }


def prior_predictive_minutes(ds: EffortDataset, draws: int = 200, seed: int = 7) -> np.ndarray:
    """Prior-predictive marathon-equivalent times (minutes) — sanity-check the priors
    generate plausible times BEFORE trusting a fit (design Decision 8)."""
    import pymc as pm

    with build_model(ds):
        pri = pm.sample_prior_predictive(draws=draws, random_seed=seed)
    return np.exp(pri.prior_predictive["y"].to_numpy().flatten())


def fit(ds: EffortDataset, *, draws: int = 1000, tune: int = 1000, chains: int = 4,
        seed: int = 7, save: bool = True, path: Path = POSTERIOR_PATH):
    """Sample the posterior (nutpie), attach log-likelihood (for LOO influence), run the
    convergence gate, and cache to a zarr store. Returns the ArviZ InferenceData.

    Raises ImportError if the `forecast` extra is absent — callers degrade to the anchor
    headline (design Decision 7), never crash the dashboard.
    """
    import pymc as pm

    with build_model(ds):
        try:
            idata = pm.sample(draws=draws, tune=tune, chains=chains, target_accept=0.95,
                              nuts_sampler="nutpie", random_seed=seed, progressbar=False)
        except Exception as e:  # nutpie unavailable / backend issue → default NUTS
            logger.warning("nutpie sampling failed (%s); falling back to default NUTS", e)
            idata = pm.sample(draws=draws, tune=tune, chains=chains, target_accept=0.95,
                              random_seed=seed, progressbar=False)
        pm.compute_log_likelihood(idata, progressbar=False)

    diag = diagnostics(idata)
    if not diag["passed"]:
        logger.warning("marathon model diagnostics did not pass: %s", diag)
    if save:
        _save_posterior(idata, path)
    return idata


def _save_posterior(idata, path: Path = POSTERIOR_PATH) -> None:
    """Cache the posterior to a zarr store, OVERWRITING any existing one.

    zarr defaults to mode 'w-' (create, fail if the store exists), so every refit after the
    first one raised ``FileExistsError: Cannot create '' with mode 'w-'`` — which is why the
    on-sync ``_refit_marathon_forecast`` was silently skipping and the forecast went stale.
    Mode 'w' overwrites (the error message's own recommendation)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    idata.to_zarr(str(path), mode="w")


def load_posterior(path: Path = POSTERIOR_PATH):
    """Load the cached posterior, or None when absent/unreadable (→ degrade, D7)."""
    if not Path(path).exists():
        return None
    try:
        import arviz as az
        return az.from_zarr(str(path))
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("could not load cached posterior: %s", e)
        return None


def fit_from_db(conn: sqlite3.Connection, **kw):
    """Convenience: extract efforts from the DB and fit. Propagates ValueError from
    extract_efforts (no LTHR anchor / no efforts) so the caller degrades gracefully."""
    return fit(extract_efforts(conn), **kw)
