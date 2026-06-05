"""Marathon model: build/fit/predict. PyMC-dependent tests skip without the extra.

The overlay-math tests use a synthetic posterior (no sampling) so they're fast and
deterministic; one seeded smoke test exercises real nutpie sampling + the convergence
gate; build_model asserts the wall penalty is NOT in the graph (predict-time only).
"""

import numpy as np
import pandas as pd
import pytest

from fit.marathon.features import EffortDataset
from fit.marathon.predict import predict


class _Arr:
    def __init__(self, a):
        self._a = a

    def to_numpy(self):
        return self._a


class _Post:
    def __init__(self, d):
        self._d = d

    def __getitem__(self, k):
        return _Arr(self._d[k])


class _Idata:
    """Minimal posterior stand-in — predict() only needs posterior[name].to_numpy()."""

    def __init__(self, d):
        self.posterior = _Post(d)


def _synthetic_idata(alpha=5.46, beta_d=1.06, phi=0.0, kappa=0.0, sd=0.01, n=600):
    """Near-constant posterior draws so medians are predictable (no arviz/sampling)."""
    rng = np.random.default_rng(0)
    chains, draws = 2, n // 2
    return _Idata({
        "alpha": rng.normal(alpha, sd, (chains, draws)),
        "beta_d": rng.normal(beta_d, sd, (chains, draws)),
        "phi": rng.normal(phi, sd, (chains, draws)),
        "kappa": rng.normal(kappa, sd, (chains, draws)),
    })


class TestPredictOverlay:
    def test_overlay_widens_and_lifts_the_interval(self):
        idata = _synthetic_idata()
        base = predict(idata, x=0.0, c=0.0, h=0.0, gap=0.69,
                       extrapolation_scale=0.0, nu=4, seed=1)      # no penalty
        walled = predict(idata, x=0.0, c=0.0, h=0.0, gap=0.69,
                         extrapolation_scale=0.04, nu=4, seed=1)   # penalty on
        assert walled["hi"] > base["hi"]                          # upper tail lifts
        assert walled["median"] >= base["median"]                 # one-sided ≥0
        assert (walled["hi"] - walled["lo"]) > (base["hi"] - base["lo"])  # genuinely wider

    def test_no_penalty_within_observed_range(self):
        idata = _synthetic_idata()
        gap0 = predict(idata, x=0.0, c=0.0, h=0.0, gap=0.0,
                       extrapolation_scale=0.04, nu=4, seed=1)
        noscale = predict(idata, x=0.0, c=0.0, h=0.0, gap=0.0,
                          extrapolation_scale=0.0, nu=4, seed=1)
        assert gap0 == noscale                                    # gap=0 → identical

    def test_median_tracks_alpha_at_origin(self):
        idata = _synthetic_idata(alpha=np.log(240))
        r = predict(idata, x=0.0, c=0.0, h=0.0, gap=0.0, extrapolation_scale=0.0, nu=4)
        assert r["median"] == pytest.approx(240 * 60, rel=0.02)   # exp(alpha) minutes → seconds

    def test_p_ceiling_monotone_in_goal(self):
        idata = _synthetic_idata(alpha=np.log(240))               # ~4:00:00 = 14400 s
        easy = predict(idata, x=0, c=0, h=0, gap=0.0, extrapolation_scale=0.0, nu=4,
                       goal_seconds=15600)   # 4:20 — easy
        hard = predict(idata, x=0, c=0, h=0, gap=0.0, extrapolation_scale=0.0, nu=4,
                       goal_seconds=13200)   # 3:40 — hard
        assert 0.0 <= hard["p_ceiling"] <= easy["p_ceiling"] <= 1.0
        assert easy["p_ceiling"] > hard["p_ceiling"]


def _synthetic_ds(n=25, alpha=5.46, beta_d=1.06, seed=0):
    rng = np.random.default_rng(seed)
    x = np.linspace(-2.6, -0.1, n)            # short→near-goal efforts (durability span)
    c = rng.normal(0, 1, n)
    h = rng.normal(0, 0.5, n)
    logt = alpha + beta_d * x + 0.0 * c + 0.0 * h + rng.normal(0, 0.03, n)
    eff = pd.DataFrame({"x": x, "c": c, "h": h, "logt": logt})
    return EffortDataset(efforts=eff, d_max=21.1, lthr=170.0, goal=42.195)


class TestBuildModel:
    def test_penalty_not_in_graph(self):
        pytest.importorskip("pymc")
        from fit.marathon.model import build_model, PARAMS
        m = build_model(_synthetic_ds())
        names = set(m.named_vars)
        assert set(PARAMS) <= names            # the 6 fitted params present
        assert "gamma" not in names            # wall penalty is a predict-time overlay
        assert "delta" not in names            # δ interaction dropped (Decision 1)


@pytest.mark.slow
class TestFitSmoke:
    def test_seeded_fit_converges(self):
        pytest.importorskip("pymc")
        from fit.marathon.model import fit, diagnostics
        idata = fit(_synthetic_ds(n=30), draws=300, tune=300, chains=2, seed=1, save=False)
        diag = diagnostics(idata)
        assert diag["divergences"] == 0
        assert diag["max_rhat"] < 1.05         # lenient for the short smoke chain
        # recover the planted durability exponent
        bd = idata.posterior["beta_d"].to_numpy().mean()
        assert 0.9 < bd < 1.2
