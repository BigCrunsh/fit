## Why

The marathon model is a Bayesian multiple regression — `log t = α + β_d·x + φ·c + κ·h + StudentT noise` — and β_d (durability), φ (fitness value), κ (effort→pace) are its three **slopes**. Today they're surfaced as **bare numbers** (plus a recent one-line intuition each). The athlete can't see **how** each is estimated, **what** it means, or — critically — its **uncertainty**: a near-zero, *prior-dominated* φ (the data barely informs it) is printed with the same confidence as a well-determined β_d. Only β_d has a graph (the durability collapse); φ and κ have none.

Each coefficient of a multiple regression is exactly what an **added-variable (partial-regression) plot** shows: net out the *other* covariates and the remaining slope **is** that coefficient — ArviZ's `plot_lm` (data + posterior mean line + HDI band). β_d already lives as that picture (the collapse); φ and κ deserve the same, and all three should show their **posterior**, not a point.

## What Changes

Replace the numeric β_d/φ/κ readout with a **decomposition**: after the Marathon Prediction Trend, show the **model formula** (`log t = α + β_d·log(dist/goal) + φ·fitness + κ·effort`, each term explained), then a **graph per coefficient, stacked vertically** — each plotting its covariate vs marathon-equivalent time with the other two netted out, so the fitted line's slope **is** that coefficient — rendered Bayesian-honestly:

- **β_d** — the **durability collapse** itself (distance axis, log; keeps its extrapolation band). No separate mini — the collapse *is* the β_d graph (de-duplicated).
- **φ** — fitness axis in **CTL** (`c·10 + 50`); slope = the race-time value of fitness.
- **κ** — effort axis in **bpm above LTHR** (`h·5`); slope = how much pace effort buys.

Each panel shows: partial-residual points (netted-out, captioned as such, **coloured by distance** like the collapse, with **run-identifying tooltips** — date · distance · finish time → marathon-equivalent), the **posterior median line + an HDI credible ribbon** (the slope's uncertainty), **greyed + "prior-dominated (thin data)"** when the `*_dominated` flag is set, a **slope-0 reference**, an **operating-point marker** ("you are here"), a **rise/run slope triangle** with a plain-language impact label (e.g. "+10 CTL → −2 min"; β_d's "×2 dist → ×2.09 time" tied to the exponent), and the **most-recent run marked** (red ring) as a shared temporal reference. **Shared log-time y-axis** so a slope is literally a straight line and the panels are comparable.

New model functions `fitness_panel` / `effort_panel` (and `distance_panel`) wrap a shared `_coeff_panel` — net out the other two covariates, return points + a posterior line/ribbon + the slope + the operating point + a slope triangle + the most-recent effort.

## Impact

- The three model signals become **legible**: estimation (the points), meaning (the slope), uncertainty (the ribbon), and marathon impact (the time axis) — and **honest about thin data** (prior-dominated panels are visibly greyed, not falsely confident).
- Consistent with the durability collapse (same added-variable idiom, same log axis) and with the Bayesian model's own posterior — no point-estimate theatre.
- Replaces the numeric readout block; the recent β_d-slope label + φ/κ intuition lines become panel captions.
- **Code**: `fit/marathon/predict.py` (`_coeff_panel` + `distance_panel`/`fitness_panel`/`effort_panel` — posterior draws for line+ribbon, point-estimate net-out for the scatter, slope triangle + most-recent effort), `fit/report/sections/charts.py` (`_param_panel_chart` + shared `_slope_triangle_annots`/`_recent_marker_annot`; the collapse gets the same triangle + recent ring), `fit/report/templates/dashboard.html` (formula block → stacked panels, h:mm log-axis with thinned ticks, run-identifying tooltips), `design_system.css` (`.param-formula`/`.param-panel`). No DB/schema change.
- **Specs**: `dashboard` — MODIFY the "first-class readouts" requirement to require the three honest panels.
- **Tests**: `pymc.testing.mock_sample` (pymc-testing skill) — build a tiny known model, mock-sample, assert each panel's line slope ≈ the known coefficient and that `prior_dominated` flows through; no real MCMC.

Affected capability: **dashboard**. Depends on: the durability model (`marathon_v2`) being fit (graceful no-op otherwise, like the collapse).
