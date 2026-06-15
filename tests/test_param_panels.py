"""Durability-param added-variable panels (durability-param-panels): each model coefficient
visualised AS a slope. Guards the geometry — the fitted line's slope IS the coefficient (the
other covariates netted out), the ribbon is its posterior, and prior-dominated panels are
greyed. Uses synthetic posteriors (no real MCMC — the pymc-testing "structure, not values"
approach), since the panels are pure downstream consumers of `idata` + `ds`.
"""

import numpy as np
import pandas as pd

from fit.marathon.features import EffortDataset, CHRONIC_SCALE, H_DIV
from fit.marathon.predict import fitness_panel, effort_panel
from fit.report.sections.charts import _param_panel_chart


# ── Minimal posterior stand-in: _flat() only needs posterior[name].to_numpy() ──
class _Arr:
    def __init__(self, a): self._a = a
    def to_numpy(self): return self._a


class _Post:
    def __init__(self, d): self._d = d
    def __getitem__(self, k): return _Arr(self._d[k])


class _Idata:
    def __init__(self, d): self.posterior = _Post(d)


def _idata(alpha=5.46, beta_d=1.06, phi=0.0, kappa=0.0, sd=0.0, n=400):
    rng = np.random.default_rng(0)
    ch, dr = 2, n // 2
    return _Idata({k: rng.normal(v, sd, (ch, dr)) for k, v in
                   {"alpha": alpha, "beta_d": beta_d, "phi": phi, "kappa": kappa}.items()})


def _ds(alpha=5.46, beta_d=1.06, phi=-0.01, kappa=-0.02, goal=42.195, n=20, seed=0):
    """Efforts whose log-time follows the model exactly so netted points lie on the line."""
    rng = np.random.default_rng(seed)
    dist = np.exp(np.linspace(np.log(5), np.log(21.1), n))
    x = np.log(dist / goal)
    c = rng.normal(0, 1, n)
    h = rng.normal(0, 0.5, n)
    logt = alpha + beta_d * x + phi * c + kappa * h
    eff = pd.DataFrame({"distance_km": dist, "x": x, "c": c, "h": h, "logt": logt})
    eff["date"] = pd.date_range("2024-06-01", periods=n, freq="20D")
    return EffortDataset(efforts=eff, d_max=float(dist.max()), lthr=170.0, goal=goal, max_hr=190.0)


def _line_log_slope(panel, scale):
    """Empirical slope of the median line in log-time per model-covariate unit (c or h)."""
    L = panel["line"]
    x0, y0, x1, y1 = L[0]["x"], L[0]["minutes"], L[-1]["x"], L[-1]["minutes"]
    return (np.log(y1) - np.log(y0)) / ((x1 - x0) / scale)


class TestSlopeEqualsCoefficient:
    def test_phi_panel_line_slope_is_phi(self):
        p = fitness_panel(_idata(phi=-0.013), _ds(), c_ref=0.0, maximal_h=-1.0)
        assert abs(_line_log_slope(p, CHRONIC_SCALE) - (-0.013)) < 1e-3   # the line literally IS φ

    def test_kappa_panel_line_slope_is_kappa(self):
        p = effort_panel(_idata(kappa=-0.025), _ds(), c_ref=0.0, maximal_h=-1.0)
        assert abs(_line_log_slope(p, H_DIV) - (-0.025)) < 1e-3           # the line literally IS κ

    def test_points_carry_distance_for_colour_and_tooltip(self):
        p = fitness_panel(_idata(), _ds(), c_ref=0.0, maximal_h=-1.0)
        pt = p["points"][0]
        assert "d" in pt and pt["d"] > 0             # distance → colour + "<d>km · <h:mm>" hover
        assert "dmin" in p and "goal" in p           # colour domain for the distance encoding


class TestUncertaintyAndNetOut:
    def _mid_width(self, p):
        m = len(p["hi"]) // 2
        return p["hi"][m]["minutes"] - p["lo"][m]["minutes"]

    def test_ribbon_widens_with_posterior_spread(self):
        narrow = fitness_panel(_idata(phi=-0.01, sd=0.0), _ds(), c_ref=0.0, maximal_h=-1.0)
        wide = fitness_panel(_idata(phi=-0.01, sd=0.06), _ds(), c_ref=0.0, maximal_h=-1.0)
        assert self._mid_width(narrow) < 1.0                    # sd≈0 → essentially no band
        assert self._mid_width(wide) > self._mid_width(narrow) + 1   # wider posterior → wider band

    def test_netting_removes_distance_and_effort(self):
        # Two efforts, SAME fitness c, different distance + effort → collapse after netting.
        a, b, phi, kappa, goal = 5.46, 1.06, -0.01, -0.02, 42.195
        rows = pd.DataFrame({"distance_km": [10.0, 21.1], "c": [0.3, 0.3], "h": [0.5, -0.5]})
        rows["x"] = np.log(rows.distance_km / goal)
        rows["logt"] = a + b * rows.x + phi * rows.c + kappa * rows.h
        rows["date"] = pd.date_range("2024-06-01", periods=2, freq="20D")
        ds = EffortDataset(efforts=rows, d_max=21.1, lthr=170.0, goal=goal, max_hr=190.0)
        p = fitness_panel(_idata(alpha=a, beta_d=b, phi=phi, kappa=kappa), ds, c_ref=0.0, maximal_h=-1.0)
        ys = [pt["minutes"] for pt in p["points"]]
        assert abs(ys[0] - ys[1]) < 0.5     # same c → same netted time (distance & effort removed)


class TestPanelChartRendering:
    def _panel(self):
        return {"points": [{"x": 50, "minutes": 240, "d": 10.0, "t": 55.0, "date": "2026-05-01"},
                           {"x": 70, "minutes": 232, "d": 21.1, "t": 120.0, "date": "2026-05-20"}],
                "line": [{"x": 40, "minutes": 250}, {"x": 80, "minutes": 230}],
                "lo": [{"x": 40, "minutes": 245}, {"x": 80, "minutes": 225}],
                "hi": [{"x": 40, "minutes": 255}, {"x": 80, "minutes": 235}],
                "x_ref": 78.0, "slope": -0.01, "dmin": 10.0, "goal": 42.195}

    def test_log_y_band_and_operating_point(self):
        cfg = _param_panel_chart("chart-param-phi", self._panel(), x_label="fitness (CTL)",
                                 x_log=False, prior_dominated=False, color="#60a5fa")["config"]
        assert '"type": "logarithmic"' in cfg                   # log-time y-axis
        assert '"90% band"' in cfg and '"fill": "+1"' in cfg     # HDI ribbon
        assert '"you are here"' in cfg and '"no effect"' in cfg  # operating point + zero-slope ref
        assert "prior-dominated" not in cfg

    def test_prior_dominated_is_greyed_and_tagged(self):
        cfg = _param_panel_chart("chart-param-phi", self._panel(), x_label="fitness (CTL)",
                                 x_log=True, prior_dominated=True, color="#60a5fa")["config"]
        assert "prior-dominated" in cfg                          # tagged
        assert "rgba(148,163,184" in cfg                         # greyed line/ribbon


class TestSlopeTriangleAndRecent:
    def test_panel_returns_triangle_and_recent(self):
        p = fitness_panel(_idata(phi=-0.013), _ds(), c_ref=0.0, maximal_h=-1.0)
        t = p["triangle"]
        assert {"x1", "x2", "y1", "y2", "run", "rise"} <= t.keys()
        assert "CTL" in t["run"]                       # the natural run unit (+10 CTL)
        assert p["recent"] is not None and {"x", "y"} <= p["recent"].keys()

    def test_chart_draws_triangle_legs_and_recent_ring(self):
        panel = {"points": [{"x": 50, "minutes": 240, "d": 10.0, "t": 55.0, "date": "2026-05-01"}],
                 "line": [{"x": 40, "minutes": 250}, {"x": 80, "minutes": 230}],
                 "lo": [{"x": 40, "minutes": 245}, {"x": 80, "minutes": 225}],
                 "hi": [{"x": 40, "minutes": 255}, {"x": 80, "minutes": 235}],
                 "x_ref": 78.0, "slope": -0.01, "dmin": 10.0, "goal": 42.195,
                 "triangle": {"x1": 40, "x2": 50, "y1": 250, "y2": 248, "run": "+10 CTL", "rise": "-2.0 min"},
                 "recent": {"x": 50, "y": 240}}
        cfg = _param_panel_chart("chart-param-phi", panel, x_label="x", x_log=False,
                                 prior_dominated=False, color="#60a5fa")["config"]
        assert '"triRun"' in cfg and '"triRise"' in cfg          # slope-triangle legs
        assert '"recent"' in cfg and '"type": "point"' in cfg     # red ring on the most-recent run
        assert "+10 CTL" in cfg


class TestGracefulWhenNotFit:
    def test_no_param_charts_on_empty_db(self, db):
        from fit.report.sections.charts import _all_charts
        ids = [c["id"] for c in _all_charts(db)]
        assert not any(i.startswith("chart-param-") for i in ids)   # no model → no panels, no crash
