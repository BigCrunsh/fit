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


def _synthetic_ds(n=25, alpha=5.46, beta_d=1.06, seed=0, goal=42.195):
    rng = np.random.default_rng(seed)
    # efforts spanning 3 km → a half-marathon (the real durability span); x = log(d/goal)
    dist = np.exp(np.linspace(np.log(3.0), np.log(21.1), n))
    x = np.log(dist / goal)
    c = rng.normal(0, 1, n)
    h = rng.normal(0, 0.5, n)
    logt = alpha + beta_d * x + 0.0 * c + 0.0 * h + rng.normal(0, 0.03, n)
    eff = pd.DataFrame({"distance_km": dist, "x": x, "c": c, "h": h, "logt": logt})
    eff["date"] = pd.date_range("2024-06-01", periods=n, freq="20D")  # Panel B needs a date
    return EffortDataset(efforts=eff, d_max=float(dist.max()), lthr=170.0, goal=goal, max_hr=190.0)


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


class TestDurabilityPanel:
    def test_collapse_and_band_fans_out(self):
        from fit.marathon.predict import durability_panel
        ds = _synthetic_ds(n=20)
        dp = durability_panel(_synthetic_idata(alpha=np.log(240), beta_d=1.06),
                              ds, c_ref=0.0, extrapolation_scale=0.04, nu=4)
        assert len(dp["points"]) == len(ds.efforts)
        assert len(dp["curve"]) >= 30
        # band fans out past d_max (extrapolation): width at the goal > width at d_max
        def width_at(d):
            c = min(dp["curve"], key=lambda r: abs(r["distance_km"] - d))
            return c["hi"] - c["lo"]
        assert width_at(ds.goal) > width_at(ds.d_max)
        assert all(c["lo"] <= c["median"] <= c["hi"] for c in dp["curve"])

    def test_c_ref_shifts_level_not_collapse(self):
        # changing c_ref shifts the whole curve but the points still track it
        from fit.marathon.predict import durability_panel
        ds = _synthetic_ds(n=15)
        idata = _synthetic_idata(phi=-0.05)
        a = durability_panel(idata, ds, c_ref=0.0)
        b = durability_panel(idata, ds, c_ref=1.0)
        # higher fitness reference → faster curve at the goal
        assert b["curve"][-1]["median"] < a["curve"][-1]["median"]


class TestResiduals:
    def test_residual_is_observed_minus_predicted(self):
        from fit.marathon.predict import residuals
        ds = _synthetic_ds(n=10)
        out = residuals(_synthetic_idata(alpha=5.46, beta_d=1.06), ds)
        assert {"predicted_logt", "residual"} <= set(out.columns)
        # residual == logt − predicted_logt, exactly
        assert np.allclose(out["residual"], out["logt"] - out["predicted_logt"])
        assert len(out) == len(ds.efforts)


class TestMarathonEquivPoints:
    """Panel B dots — each effort projected to the goal distance, coloured by its distance."""

    def test_distance_removed_points_collapse(self):
        import math
        from fit.marathon.predict import marathon_equiv_points
        # data on a clean β_d power law, kappa=0 → removing distance collapses every effort
        # (5k…HM) onto ≈ exp(alpha), regardless of its actual distance.
        ds = _synthetic_ds(n=12, alpha=5.46, beta_d=1.06)
        pts = marathon_equiv_points(_synthetic_idata(alpha=5.46, beta_d=1.06, kappa=0.0), ds)
        assert len(pts) == len(ds.efforts)
        base = math.exp(5.46)
        for p in pts:
            assert p["minutes"] == pytest.approx(base, rel=0.15)
            assert p["distance_km"] > 0          # carried through for colour-coding

    def test_sorted_by_date_and_shaped(self):
        from fit.marathon.predict import marathon_equiv_points
        ds = _synthetic_ds(n=8)
        pts = marathon_equiv_points(_synthetic_idata(), ds)
        assert [p["date"] for p in pts] == sorted(p["date"] for p in pts)
        assert all({"date", "minutes", "distance_km"} <= set(p) for p in pts)


class TestMaximalEffortCap:
    """maximal_effort_h is LTHR-relative; hr_reserve (=MaxHR−LTHR) caps the offset so a
    maximal effort can never exceed MaxHR (matters only for a low-reserve athlete)."""

    def test_uncapped_matches_schedule(self):
        from fit.marathon.predict import maximal_effort_h
        from fit.marathon.features import H_DIV
        assert maximal_effort_h(5.0) == pytest.approx(10.0 / H_DIV)        # 5k → +10 bpm vs LTHR
        assert maximal_effort_h(21.0975) == pytest.approx(0.0)            # HM → at LTHR
        assert maximal_effort_h(42.195) == pytest.approx(-6.0 / H_DIV)    # M → −6 bpm vs LTHR

    def test_cap_binds_for_low_reserve(self):
        from fit.marathon.predict import maximal_effort_h
        from fit.marathon.features import H_DIV
        # reserve 5 bpm < the +10 bpm 5k offset → the short-race limb is clamped to reserve
        assert maximal_effort_h(5.0, hr_reserve=5.0) == pytest.approx(5.0 / H_DIV)

    def test_cap_is_noop_when_reserve_exceeds_offset(self):
        from fit.marathon.predict import maximal_effort_h
        # reserve 22 (this athlete) ≥ +10 → unchanged
        assert maximal_effort_h(5.0, hr_reserve=22.0) == maximal_effort_h(5.0)

    def test_cap_never_raises_a_sub_threshold_offset(self):
        from fit.marathon.predict import maximal_effort_h
        # marathon offset is −6 bpm; a tiny reserve must not LIFT it (min, not max)
        assert maximal_effort_h(42.195, hr_reserve=2.0) == maximal_effort_h(42.195)


class TestForecastContext:
    """forecast_context loads (posterior + efforts + prior) ONCE per connection — the
    dashboard/CLI/MCP share it instead of each re-reading the zarr posterior + feature SQL."""

    def test_cache_hits_same_conn_recomputes_fresh_conn(self, monkeypatch):
        import fit.marathon.predict as P
        calls = {"n": 0}
        sentinel = object()

        def _fake_build(conn):
            calls["n"] += 1
            return sentinel

        monkeypatch.setattr(P, "_build_forecast_context", _fake_build)
        monkeypatch.setattr(P, "_CTX_CACHE", {"conn": None, "ctx": None})
        conn_a, conn_b = object(), object()
        assert P.forecast_context(conn_a) is sentinel        # builds
        assert P.forecast_context(conn_a) is sentinel        # cache hit — no rebuild
        assert calls["n"] == 1
        assert P.forecast_context(conn_b) is sentinel        # different conn → rebuild
        assert calls["n"] == 2

    def test_none_when_no_efforts(self, db):
        from fit.marathon.predict import forecast_context
        assert forecast_context(db) is None                  # empty db → degrade, not crash


class TestPosteriorCache:
    """Regression: the on-sync refit must OVERWRITE the cached posterior. zarr's default
    'w-' mode raised FileExistsError on every refit after the first, silently skipping the
    refit and leaving the forecast stale."""

    def test_save_overwrites_existing_store(self, tmp_path):
        az = pytest.importorskip("arviz")
        from fit.marathon.model import _save_posterior, load_posterior
        idata = az.from_dict({"posterior": {"alpha": np.zeros((2, 10))}})
        p = tmp_path / "marathon_posterior.zarr"
        _save_posterior(idata, p)                 # first fit
        _save_posterior(idata, p)                 # re-fit must overwrite, not raise
        loaded = load_posterior(p)
        assert loaded is not None and "alpha" in loaded.posterior


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


class TestForecastSection:
    def test_degrades_to_anchor_when_no_efforts(self, db):
        from datetime import date, timedelta
        from fit.report.sections.predictions import _marathon_forecast
        db.execute("INSERT INTO calibration (metric,value,method,confidence,date,active) "
                   "VALUES ('vdot', 40, 'manual','high',?,1)",
                   ((date.today() - timedelta(days=1)).isoformat(),))
        db.commit()
        f = _marathon_forecast(db)                       # no efforts → anchor fallback
        assert f["available"] is True and f["source"] == "anchor" and "median" in f

    def test_unavailable_without_anchor_or_model(self, db):
        from fit.report.sections.predictions import _marathon_forecast
        assert _marathon_forecast(db)["available"] is False


class TestSyncRefit:
    def test_refit_skips_without_history(self, db):
        from fit.sync import _refit_marathon_forecast
        assert _refit_marathon_forecast(db) is False     # empty db → graceful skip, no crash


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
