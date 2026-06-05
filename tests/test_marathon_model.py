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


class TestDerivedMetrics:
    def test_structure_and_equivalency_monotone(self):
        from fit.marathon.predict import derived_metrics
        ds = _synthetic_ds()
        dm = derived_metrics(_synthetic_idata(alpha=np.log(240), beta_d=1.06),
                             ds, c=0.0, extrapolation_scale=0.0, nu=4)
        for key in ("durability_beta_d", "fitness_value_phi", "effort_kappa", "race_equivalency"):
            assert key in dm
        times = [r["median"] for r in dm["race_equivalency"]]
        assert times == sorted(times)                  # 5K < 10K < HM < M
        assert {r["label"] for r in dm["race_equivalency"]} == {"5K", "10K", "HM", "M"}
        assert "prior_dominated" in dm["durability_beta_d"]

    def test_required_chronic_easy_vs_impossible(self):
        from fit.marathon.predict import required_chronic_for_goal
        ds = _synthetic_ds()
        idata = _synthetic_idata(alpha=np.log(240))    # ~4:00 at c=0
        assert required_chronic_for_goal(idata, ds, goal_seconds=18000) is not None  # 5:00 — easy
        assert required_chronic_for_goal(idata, ds, goal_seconds=7200) is None       # 2:00 — impossible


class TestTrendSeries:
    def test_points_over_time(self, db):
        from datetime import date, timedelta
        from fit.marathon.predict import trend_series
        for i in range(20):
            d = (date.today() - timedelta(days=i * 5)).isoformat()
            db.execute("INSERT INTO activities (id, date, type, training_load) "
                       "VALUES (?, ?, 'running', 60)", (f"a{i}", d))
        db.commit()
        ts = trend_series(db, _synthetic_idata(), _synthetic_ds(), days=120, step_days=30)
        assert len(ts) == 5                            # 120/30 + 1
        assert all({"date", "median", "lo", "hi"} <= set(p) for p in ts)
        assert all(p["lo"] <= p["median"] <= p["hi"] for p in ts)


class TestForecastDegrade:
    def test_forecast_returns_none_without_posterior(self, db):
        # LTHR + a qualifying effort exist, but no cached posterior and none passed → None
        from datetime import date, timedelta
        from fit.marathon.predict import forecast
        db.execute("INSERT INTO calibration (metric, value, method, confidence, date, active) "
                   "VALUES ('lthr', 170, 'manual', 'high', ?, 1)",
                   ((date.today() - timedelta(days=1)).isoformat(),))
        db.execute("INSERT INTO activities (id, date, type, run_type, distance_km, duration_min, avg_hr, training_load) "
                   "VALUES ('r', ?, 'running', 'race', 10, 50, 175, 80)",
                   ((date.today() - timedelta(days=400)).isoformat(),))
        db.commit()
        assert forecast(db, posterior=None) is None     # degrade, not crash


@pytest.mark.slow
class TestFitSmoke:
    def test_seeded_fit_converges_and_influence(self):
        pytest.importorskip("pymc")
        from fit.marathon.model import fit, diagnostics
        from fit.marathon.predict import influence
        ds = _synthetic_ds(n=30)
        idata = fit(ds, draws=300, tune=300, chains=2, seed=1, save=False)
        diag = diagnostics(idata)
        assert diag["divergences"] == 0
        assert diag["max_rhat"] < 1.05
        assert 0.9 < idata.posterior["beta_d"].to_numpy().mean() < 1.2
        infl = influence(idata, ds)               # needs the log_likelihood group
        assert len(infl["efforts"]) == len(ds.efforts)
        assert "good_k" in infl and all("pareto_k" in e for e in infl["efforts"])
