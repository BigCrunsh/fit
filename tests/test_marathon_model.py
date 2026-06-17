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


class TestModelStructureMockSample:
    """Structure-only tests (no real MCMC) via `pymc.testing.mock_sample`: the graph is
    exactly the six fitted params + the observed likelihood, and it samples to that
    structure when `pm.sample` is mocked — fast, deterministic, no convergence needed."""

    def test_graph_is_exactly_the_six_params_plus_observed_y(self):
        pytest.importorskip("pymc")
        from fit.marathon.model import build_model, PARAMS
        m = build_model(_synthetic_ds())
        assert {rv.name for rv in m.free_RVs} == set(PARAMS)          # exactly the 6 fitted params
        assert {rv.name for rv in m.observed_RVs} == {"y"}            # one observed likelihood
        assert type(m.observed_RVs[0].owner.op).__name__ == "StudentTRV"   # robust (Student-T) likelihood

    def test_mock_sample_round_trip_yields_posterior_params(self, monkeypatch):
        pytest.importorskip("pymc")
        import pymc as pm
        from pymc.testing import mock_sample
        from fit.marathon.model import build_model, PARAMS
        monkeypatch.setattr(pm, "sample", mock_sample)               # prior-predictive, not MCMC
        with build_model(_synthetic_ds()):
            idata = pm.sample()
        assert set(PARAMS) <= set(idata.posterior.data_vars)         # graph is samplable to spec

    def test_fit_runs_end_to_end_under_mock(self, monkeypatch):
        """fit() (build → sample → log-lik → diagnostics → return) completes without real
        sampling when pm.sample is mocked; the result has the expected posterior structure."""
        pytest.importorskip("pymc")
        import pymc as pm
        from functools import partial
        from pymc.testing import mock_sample
        from fit.marathon.model import fit, PARAMS
        monkeypatch.setattr(pm, "sample", partial(
            mock_sample, sample_stats={"diverging": lambda size: np.zeros(size, dtype=int)}))
        idata = fit(_synthetic_ds(), save=False)                     # no disk, no MCMC
        assert set(PARAMS) <= set(idata.posterior.data_vars)


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
    """maximal_effort_h is the duration-keyed fade law offset(t)=β·(log t−log T₀)/H_DIV,
    LTHR-relative; hr_reserve (=MaxHR−LTHR) caps the offset so a maximal effort can never
    exceed MaxHR (matters only for a low-reserve athlete)."""

    def test_law_short_above_long_below_threshold(self):
        from fit.marathon.predict import maximal_effort_h
        from fit.marathon.features import H_DIV
        t0, beta = 100.0, -6.5
        # a 25-min effort sits above threshold; at T₀ it's exactly LTHR; a 240-min effort below
        assert maximal_effort_h(25.0, t0, beta) > 0
        assert maximal_effort_h(t0, t0, beta) == pytest.approx(0.0)
        assert maximal_effort_h(240.0, t0, beta) < 0
        # offset = β·(log t − log T₀) / H_DIV
        assert maximal_effort_h(50.0, t0, beta) == pytest.approx(beta * (np.log(50.0) - np.log(t0)) / H_DIV)

    def test_cap_binds_for_low_reserve(self):
        from fit.marathon.predict import maximal_effort_h
        from fit.marathon.features import H_DIV
        # a 22-min effort uncapped is well above threshold; reserve 3 bpm clamps it
        uncapped = maximal_effort_h(22.0, 100.0, -6.5)
        assert uncapped * H_DIV > 3.0
        assert maximal_effort_h(22.0, 100.0, -6.5, hr_reserve=3.0) == pytest.approx(3.0 / H_DIV)

    def test_cap_is_noop_when_reserve_exceeds_offset(self):
        from fit.marathon.predict import maximal_effort_h
        # reserve 22 ≥ the short-effort offset → unchanged
        assert maximal_effort_h(22.0, 100.0, -6.5, hr_reserve=22.0) == maximal_effort_h(22.0, 100.0, -6.5)

    def test_cap_never_raises_a_sub_threshold_offset(self):
        from fit.marathon.predict import maximal_effort_h
        # a long (sub-threshold, negative) offset must not be LIFTED by a tiny reserve (min, not max)
        assert maximal_effort_h(240.0, 100.0, -6.5, hr_reserve=2.0) == maximal_effort_h(240.0, 100.0, -6.5)


class TestEffortSchedule:
    """T₀ from at-or-above-threshold races (prior+data shrinkage); β stays the population prior."""

    def _ds(self, rows, lthr=171.0, goal=42.195):
        # rows: list of (days_ago, distance_km, duration_min, avg_hr, run_type)
        import pandas as pd
        from datetime import date, timedelta
        recs = []
        today = date.today()
        for days_ago, dist, dur, hr, rt in rows:
            recs.append({"date": pd.Timestamp(today - timedelta(days=days_ago)),
                         "run_type": rt, "distance_km": dist, "avg_hr": hr,
                         "logt": np.log(dur)})
        eff = pd.DataFrame(recs)
        from collections import namedtuple
        DS = namedtuple("DS", "efforts lthr goal d_max max_hr")
        return DS(efforts=eff, lthr=lthr, goal=goal, d_max=21.1, max_hr=195.0)

    def test_t0_from_at_threshold_races_beta_is_population(self):
        from fit.marathon.predict import effort_schedule, EFFORT_BETA_PRIOR
        ds = self._ds([(30, 21.1, 120, 173, "race"),   # hard HM at/above LTHR
                       (60, 21.1, 110, 172, "race"),
                       (90, 10.0, 48, 178, "race")])
        s = effort_schedule(ds)
        assert s["beta"] == EFFORT_BETA_PRIOR          # slope stays population (not fitted)
        assert 80 < s["t0"] < 150                      # threshold-duration ≈ the HMs
        assert s["defaulted"] is False

    def test_submaximal_short_race_does_not_collapse_t0(self):
        # an easy 5K run AT threshold (the real-data failure) must not pin T₀ to ~25 min
        from fit.marathon.predict import effort_schedule
        ds = self._ds([(10, 5.0, 25, 171, "race"),     # sub-maximal 5K at LTHR
                       (40, 21.1, 120, 173, "race")])   # genuine hard HM
        s = effort_schedule(ds)
        assert s["t0"] > 60                            # NOT dragged to 25 min by the easy 5K

    def test_defaults_to_prior_without_at_threshold_race(self):
        from fit.marathon.predict import effort_schedule, EFFORT_T0_PRIOR_MIN, EFFORT_BETA_PRIOR
        ds = self._ds([(30, 21.1, 120, 160, "race")])  # only a sub-threshold (easy) race
        s = effort_schedule(ds)
        assert s["defaulted"] is True
        assert s["t0"] == EFFORT_T0_PRIOR_MIN and s["beta"] == EFFORT_BETA_PRIOR

    def test_recency_shifts_t0(self):
        from fit.marathon.predict import effort_schedule
        recent = effort_schedule(self._ds([(15, 21.1, 130, 173, "race"), (20, 21.1, 128, 172, "race")]))
        old = effort_schedule(self._ds([(800, 21.1, 130, 173, "race"), (820, 21.1, 128, 172, "race")]))
        # an old block shrinks harder toward the prior (lower T₀) than the same recent block
        assert recent["t0"] > old["t0"]


def _race_ds(goal=42.195, max_hr=195.0):
    """A schedule-anchored ds (several at/above-threshold HM/10K races) for effort-propagation."""
    import pandas as pd
    from datetime import date, timedelta
    from collections import namedtuple
    today = date.today()
    rows = [(20, 21.1, 118, 173), (40, 21.1, 120, 174), (70, 10.0, 47, 179), (110, 21.1, 119, 172)]
    recs = [{"date": pd.Timestamp(today - timedelta(days=da)), "run_type": "race",
             "distance_km": dist, "avg_hr": hr, "logt": np.log(dur)} for da, dist, dur, hr in rows]
    DS = namedtuple("DS", "efforts lthr goal d_max max_hr")
    return DS(efforts=pd.DataFrame(recs), lthr=171.0, goal=goal, d_max=21.1, max_hr=max_hr)


class TestEffortScheduleUncertainty:
    """effort-schedule-uncertainty: σ_β (the documented prior constant) and σ_T0 (a precision-
    weighted POSTERIOR log-SD) attach to the schedule. σ_T0 goes WIDE at cold-start and NEVER
    collapses to ~0 on a single / identical-implied race (the floor)."""

    def _ds(self, rows, lthr=171.0, goal=42.195):
        import pandas as pd
        from datetime import date, timedelta
        from collections import namedtuple
        today = date.today()
        recs = [{"date": pd.Timestamp(today - timedelta(days=da)), "run_type": rt,
                 "distance_km": dist, "avg_hr": hr, "logt": np.log(dur)}
                for da, dist, dur, hr, rt in rows]
        DS = namedtuple("DS", "efforts lthr goal d_max max_hr")
        return DS(efforts=pd.DataFrame(recs), lthr=lthr, goal=goal, d_max=21.1, max_hr=195.0)

    def test_beta_sd_is_the_documented_prior(self):
        from fit.marathon.predict import effort_schedule, EFFORT_BETA_PRIOR_SD
        s = effort_schedule(self._ds([(30, 21.1, 120, 173, "race"), (60, 10.0, 48, 178, "race")]))
        assert s["beta_sd"] == EFFORT_BETA_PRIOR_SD          # β SD is the hand-set prior, always

    def test_cold_start_t0_sd_is_the_wide_prior(self):
        from fit.marathon.predict import effort_schedule, EFFORT_T0_PRIOR_LOG_SD
        # only a sub-threshold race → defaulted → σ_T0 = the wide prior (we barely know T0)
        s = effort_schedule(self._ds([(30, 21.1, 120, 160, "race")]))
        assert s["defaulted"] is True
        assert s["t0_sd"] == EFFORT_T0_PRIOR_LOG_SD

    def test_no_efforts_still_carries_sds(self):
        from fit.marathon.predict import effort_schedule, EFFORT_BETA_PRIOR_SD, EFFORT_T0_PRIOR_LOG_SD
        from collections import namedtuple
        DS = namedtuple("DS", "efforts lthr goal d_max max_hr")
        s = effort_schedule(DS(efforts=None, lthr=171.0, goal=42.195, d_max=21.1, max_hr=195.0))
        assert s["defaulted"] is True
        assert s["beta_sd"] == EFFORT_BETA_PRIOR_SD and s["t0_sd"] == EFFORT_T0_PRIOR_LOG_SD

    def test_single_hard_race_does_not_collapse_t0_sd(self):
        from fit.marathon.predict import effort_schedule, EFFORT_T0_PRIOR_LOG_SD
        s = effort_schedule(self._ds([(30, 21.1, 120, 173, "race")]))   # ONE hard race
        assert s["defaulted"] is False
        assert s["t0_sd"] > 0.05                              # NOT ~0 — the obs floor prevents collapse
        assert s["t0_sd"] < EFFORT_T0_PRIOR_LOG_SD            # one race still tightens below the prior

    def test_more_consistent_races_tighten_t0_sd(self):
        from fit.marathon.predict import effort_schedule, EFFORT_T0_PRIOR_LOG_SD
        few = effort_schedule(self._ds([(30, 21.1, 120, 173, "race"), (50, 21.1, 120, 173, "race")]))
        many = effort_schedule(self._ds([(30 + 10 * i, 21.1, 120, 173, "race") for i in range(8)]))
        assert many["t0_sd"] < few["t0_sd"] < EFFORT_T0_PRIOR_LOG_SD   # more evidence → tighter, both < prior


class TestEffortPropagation:
    """The (σ_β, σ_T0) overlay widens the INTERVAL only: the median is pinned to the point (β,T0),
    the wall-penalty draws are byte-untouched (RNG isolation), and the widening grows with the
    extrapolation from T0."""

    def _setup(self, kappa=-0.04):
        # alpha=log(240): a realistic ~4h marathon at the goal, so the marathon lands FAR past T0
        # (~120 min here) and the half lands near it — the real extrapolation geometry.
        return _synthetic_idata(alpha=np.log(240), beta_d=1.06, kappa=kappa), _race_ds()

    def _bands(self, idata, ds, d, *, scale=0.04, nu=4, seed=3):
        from fit.marathon.predict import effort_h_for_distance, predict
        x = float(np.log(d / ds.goal)); gap = max(0.0, float(np.log(d / ds.d_max)))
        h_pt, h_dr = effort_h_for_distance(idata, ds, d, c=0.0, extrapolation_scale=scale,
                                           nu=nu, seed=seed, draws=True)
        pt = predict(idata, x=x, c=0.0, h=h_pt, gap=gap, extrapolation_scale=scale, nu=nu, seed=seed)
        eff = predict(idata, x=x, c=0.0, h=h_pt, h_draws=h_dr, gap=gap,
                      extrapolation_scale=scale, nu=nu, seed=seed)
        return pt, eff

    def test_median_exactly_unchanged(self):
        pt, eff = self._bands(*self._setup(), 42.195)
        assert eff["median"] == pt["median"]                 # EXACT — median uses the point h

    def test_marathon_interval_widens(self):
        pt, eff = self._bands(*self._setup(), 42.195)
        assert (eff["hi"] - eff["lo"]) > (pt["hi"] - pt["lo"])

    def test_zero_sigma_is_byte_identical_to_point_path(self):
        # σ_β=σ_T0=0 → h_draws is the point h repeated → band IDENTICAL; also proves the effort RNG
        # never perturbs the wall-penalty draws (the isolation guard).
        from fit.marathon.predict import effort_h_for_distance, predict
        idata, ds = self._setup()
        sched = {"t0": 95.0, "beta": -6.5, "beta_sd": 0.0, "t0_sd": 0.0, "defaulted": False, "reason": "x"}
        d = 42.195; x = 0.0; gap = float(np.log(d / ds.d_max))
        h_pt, h_dr = effort_h_for_distance(idata, ds, d, c=0.0, extrapolation_scale=0.04, nu=4,
                                           seed=3, schedule=sched, draws=True)
        eff = predict(idata, x=x, c=0.0, h=h_pt, h_draws=h_dr, gap=gap, extrapolation_scale=0.04, nu=4, seed=3)
        pt = predict(idata, x=x, c=0.0, h=h_pt, gap=gap, extrapolation_scale=0.04, nu=4, seed=3)
        assert eff == pt                                     # identical lo/hi/median

    def test_widening_grows_with_extrapolation_from_t0(self):
        idata, ds = self._setup()
        pt_m, eff_m = self._bands(idata, ds, 42.195)
        pt_h, eff_h = self._bands(idata, ds, 21.0975)
        widen_m = (eff_m["hi"] - eff_m["lo"]) - (pt_m["hi"] - pt_m["lo"])
        widen_h = (eff_h["hi"] - eff_h["lo"]) - (pt_h["hi"] - pt_h["lo"])
        assert widen_m > widen_h > 0                         # marathon widens MORE (absolute minutes)

    def test_dropping_t0_understates_the_marathon_interval(self):
        # β-only (σ_T0 forced to 0) is narrower than β+T0 at the marathon → T0 contributes materially
        from fit.marathon.predict import effort_h_for_distance, predict, effort_schedule
        idata, ds = self._setup()
        full = effort_schedule(ds); beta_only = {**full, "t0_sd": 0.0}
        d = 42.195; gap = float(np.log(d / ds.d_max))
        hp_f, h_full = effort_h_for_distance(idata, ds, d, c=0.0, extrapolation_scale=0.04, nu=4,
                                             seed=3, schedule=full, draws=True)
        hp_b, h_bonly = effort_h_for_distance(idata, ds, d, c=0.0, extrapolation_scale=0.04, nu=4,
                                              seed=3, schedule=beta_only, draws=True)
        b_full = predict(idata, x=0.0, c=0.0, h=hp_f, h_draws=h_full, gap=gap, extrapolation_scale=0.04, nu=4, seed=3)
        b_bonly = predict(idata, x=0.0, c=0.0, h=hp_b, h_draws=h_bonly, gap=gap, extrapolation_scale=0.04, nu=4, seed=3)
        assert (b_full["hi"] - b_full["lo"]) > (b_bonly["hi"] - b_bonly["lo"])

    def test_seed_determinism(self):
        idata, ds = self._setup()
        assert self._bands(idata, ds, 42.195, seed=7)[1] == self._bands(idata, ds, 42.195, seed=7)[1]

    def test_combined_width_stays_sane(self):
        # effort uncertainty must WIDEN the band but not BLOW IT UP — combined < 2× the point width.
        # Guards a regression where σ_T0's collapse-protection over-inflates, or wall+effort double-count.
        pt, eff = self._bands(*self._setup(), 42.195)
        pt_w, eff_w = pt["hi"] - pt["lo"], eff["hi"] - eff["lo"]
        assert pt_w < eff_w < 2.0 * pt_w

    def test_reserve_cap_binds_elementwise(self):
        # a tiny MaxHR reserve clamps EVERY per-draw offset (np.minimum on the array, not scalar min)
        from fit.marathon.predict import effort_h_for_distance
        from fit.marathon.features import H_DIV
        idata = _synthetic_idata(alpha=np.log(60), kappa=-0.04)        # short predicted duration → high offset
        ds = _race_ds(max_hr=174.0)                                    # reserve = 3 bpm → binds
        _, h_dr = effort_h_for_distance(idata, ds, 5.0, c=0.0, extrapolation_scale=0.0, nu=4, seed=3, draws=True)
        assert np.all(np.asarray(h_dr) * H_DIV <= 3.0 + 1e-9)          # vectorised cap held for ALL draws


class TestEffortSchedulePanel:
    """The inspection-panel data builder (offset-vs-duration): line + 90% band + race dots +
    std-distance markers at predicted durations + the hard-effort count for the render gate."""

    def test_shape_band_pinches_at_t0_and_markers_ordered(self):
        from fit.marathon.predict import effort_schedule_panel
        idata, ds = _synthetic_idata(alpha=np.log(150), kappa=-0.04), _race_ds()
        p = effort_schedule_panel(idata, ds, c=0.0)
        assert p["defaulted"] is False and p["n_hard"] >= 2
        # markers cover the four std distances, ordered by predicted duration (5K < 10K < HM < M)
        labels = [m["label"] for m in p["markers"]]
        assert labels == ["5K", "10K", "HM", "M"]
        xs = [m["x"] for m in p["markers"]]
        assert xs == sorted(xs)
        # band is narrowest near T0 (its zero-crossing) and wider out at the marathon marker
        def width_at(t):
            i = min(range(len(p["line"])), key=lambda k: abs(p["line"][k]["x"] - t))
            return p["hi"][i]["y"] - p["lo"][i]["y"]
        assert width_at(p["t0"]) < width_at(xs[-1])          # pinched at T0, fans out to the marathon

    def test_dots_split_hard_and_subthreshold(self):
        from fit.marathon.predict import effort_schedule_panel
        idata = _synthetic_idata(alpha=np.log(150), kappa=-0.04)
        # one clearly sub-threshold race (avg_hr far below LTHR) → a hollow dot, excluded from the fit
        import pandas as pd
        from datetime import date, timedelta
        from collections import namedtuple
        today = date.today()
        rows = [(20, 21.1, 118, 173, True), (40, 10.0, 47, 179, True), (60, 21.1, 130, 150, False)]
        recs = [{"date": pd.Timestamp(today - timedelta(days=da)), "run_type": "race",
                 "distance_km": dist, "avg_hr": hr, "logt": np.log(dur)} for da, dist, dur, hr, _ in rows]
        DS = namedtuple("DS", "efforts lthr goal d_max max_hr")
        ds = DS(efforts=pd.DataFrame(recs), lthr=171.0, goal=42.195, d_max=21.1, max_hr=195.0)
        p = effort_schedule_panel(idata, ds, c=0.0)
        assert sum(d["hard"] for d in p["dots"]) == 2
        assert sum(not d["hard"] for d in p["dots"]) == 1


class TestBetaFit:
    """β is fitted (prior-regularized) from maximal RACES only (maximal-effort-flag). Thin or
    narrow-range data stays at the population prior; consistent maximal data personalises it."""

    def _ds(self, rows, lthr=171.0, goal=42.195):
        # rows: (days_ago, distance_km, duration_min, avg_hr, run_type, is_maximal)
        import pandas as pd
        from datetime import date, timedelta
        from collections import namedtuple
        today = date.today()
        recs = [{"date": pd.Timestamp(today - timedelta(days=da)), "run_type": rt,
                 "distance_km": dist, "avg_hr": hr, "logt": np.log(dur), "is_maximal": im}
                for da, dist, dur, hr, rt, im in rows]
        DS = namedtuple("DS", "efforts lthr goal d_max max_hr")
        return DS(efforts=pd.DataFrame(recs), lthr=lthr, goal=goal, d_max=21.1, max_hr=195.0)

    def _slope_rows(self, slope, durs, lthr=171.0):
        # maximal races lying on offset = slope·(log dur − log 60), so the data slope == `slope`
        return [(30 + 5 * i, 10.0, d, lthr + slope * (np.log(d) - np.log(60.0)), "race", 1)
                for i, d in enumerate(durs)]

    def test_two_maximal_races_stay_prior(self):
        from fit.marathon.predict import effort_schedule, EFFORT_BETA_PRIOR, EFFORT_BETA_PRIOR_SD
        s = effort_schedule(self._ds(self._slope_rows(-3.0, [15, 60])))   # only 2 < min 3
        assert s["beta"] == EFFORT_BETA_PRIOR and s["beta_sd"] == EFFORT_BETA_PRIOR_SD
        assert s["beta_fitted"] is False

    def test_no_is_maximal_column_stays_prior(self):
        # the pre-change ds (races but no is_maximal column) → β prior, backward compatible
        from fit.marathon.predict import effort_schedule, EFFORT_BETA_PRIOR
        ds = _race_ds()  # has run_type but no is_maximal column
        s = effort_schedule(ds)
        assert s["beta"] == EFFORT_BETA_PRIOR and s["beta_fitted"] is False

    def test_consistent_maximal_races_move_beta_toward_data(self):
        from fit.marathon.predict import effort_schedule, EFFORT_BETA_PRIOR, EFFORT_BETA_PRIOR_SD
        s = effort_schedule(self._ds(self._slope_rows(-4.0, [12, 20, 35, 60, 100, 120])))
        assert s["beta_fitted"] is True
        assert EFFORT_BETA_PRIOR < s["beta"] < -4.0      # between the prior (−6.5) and data slope (−4)
        assert s["beta_sd"] < EFFORT_BETA_PRIOR_SD       # data tightened the SE below the prior

    def test_nonrace_maximal_excluded_from_fit(self):
        # a maximal TEMPO (avg HR dragged low by recoveries) must NOT feed the slope — races only
        from fit.marathon.predict import effort_schedule
        races = self._slope_rows(-4.0, [12, 35, 100])
        base = effort_schedule(self._ds(races))
        with_tempo = effort_schedule(self._ds(races + [(20, 12.0, 60, 140, "tempo", 1)]))
        assert with_tempo["beta"] == base["beta"]        # tempo excluded → β unchanged

    def test_subthreshold_flagged_race_excluded_from_fit(self):
        # an explicitly non-maximal race (is_maximal=0) doesn't feed the slope
        from fit.marathon.predict import effort_schedule
        races = self._slope_rows(-4.0, [12, 35, 100])
        base = effort_schedule(self._ds(races))
        with_easy = effort_schedule(self._ds(races + [(15, 21.0, 110, 160, "race", 0)]))
        assert with_easy["beta"] == base["beta"]

    def test_few_points_perfect_fit_stays_regularized(self):
        # 3 maximal races on a PERFECT line → the obs floor keeps β regularized (NOT snapped to the
        # data slope) and the SE doesn't collapse to ~0
        from fit.marathon.predict import effort_schedule, EFFORT_BETA_PRIOR
        s = effort_schedule(self._ds(self._slope_rows(-3.0, [15, 45, 120])))
        assert s["beta_fitted"] is True
        assert -3.0 > s["beta"] > EFFORT_BETA_PRIOR      # pulled toward −3 but not all the way
        assert s["beta_sd"] > 0.3                        # SE not collapsed (floor held)


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
