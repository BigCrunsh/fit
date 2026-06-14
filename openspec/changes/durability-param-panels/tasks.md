## 1. Model panel functions (predict.py)

- [x] 1.1 `fitness_panel(idata, ds, *, c_ref, maximal_h, n_grid)` mirroring `durability_panel`: net out `β_d·x` and `κ·(h−maximal_h)` from each effort's `logt` → partial-residual points keyed on **CTL** (`c·CHRONIC_SCALE+CHRONIC_REF`); posterior median line + 5–95% HDI ribbon over a CTL grid (draws of `α+β·x_goal+φ·c+κ·maximal_h`); return slope `φ` (median), `prior_dominated`, operating point (today's CTL), and the impact (min per +10 CTL).
- [x] 1.2 `effort_panel(idata, ds, *, c_ref, n_grid)`: net out `β_d·x` and `φ·(c−c_ref)` → points keyed on **bpm above LTHR** (`h·H_DIV`); median line + HDI ribbon over an effort grid; return slope `κ`, `prior_dominated`, operating point (assumed race-HR offset), impact (% / s·km⁻¹ per +5 bpm).
- [x] 1.3 Both reuse the shared `forecast_context` load; points netted at posterior medians, line/ribbon from draws (design Decision 6). Graceful when the model is not fit.

## 2. Panel charts (charts.py)

- [x] 2.1 Build three side-by-side panel charts (`chart-param-betad`, `chart-param-phi`, `chart-param-kappa`) from the panel data — partial-residual scatter + median line + HDI ribbon band, **shared log-time y-axis** (ticks formatted h:mm), each x-axis in its own units (log km / CTL / bpm above LTHR).
- [x] 2.2 Each chart: a **zero-slope reference** guide, an **operating-point marker**, influential efforts marked (existing `influence`), and a title carrying the coefficient + its credible interval.
- [x] 2.3 Prior-dominated → grey/dashed line+ribbon + a "prior-dominated" annotation.
- [x] 2.4 β_d panel cross-links (caption/anchor) to the full-width durability collapse, which stays.

## 3. Template (dashboard.html)

- [x] 3.1 Replace the numeric β_d/φ/κ readout block with a **3-column row** of the panel canvases under the existing "Durability-model params" heading; keep the durability-collapse chart above.
- [x] 3.2 Each panel caption = the plain-language impact label (the φ/κ intuition lines move here) + "points are netted-out (partial residuals), not raw runs."
- [x] 3.3 Reuse design-system styling; ribbon band opacity ≥ `40` hex; colourblind-safe; graceful empty when panels absent.

## 4. Tests (mock_sample; 2:1 unhappy:happy)

- [x] 4.1 Happy: a tiny known-coefficient model mock-sampled → each panel's median-line slope ≈ the known coefficient (in log-time); points + line + ribbon present.
- [x] 4.2 Unhappy — uncertainty: a wider posterior → a wider HDI ribbon (the ribbon reflects spread, not a constant).
- [x] 4.3 Unhappy — prior-dominated: the flag flows through to the greyed/tagged panel state.
- [x] 4.4 Unhappy — net-out correctness: the φ panel's slope is invariant to distance/effort spread (the other covariates are removed), and differs from the raw covariate-vs-time slope.
- [x] 4.5 Unhappy — not fit: panels degrade gracefully (no exception, no chart), like the collapse.
- [x] 4.6 Chart guard: three param charts build with a log y-axis, an HDI band dataset, a zero reference, and an operating-point marker; β_d collapse still present.

## 5. Validation

- [x] 5.1 Full suite green; `ruff` clean.
- [x] 5.2 `fit report` builds with and without the `forecast` extra; spot-check the three panels on real data (slopes, ribbons, operating points, impact labels; φ/κ not prior-dominated here, a thin-history fixture greys them).
- [x] 5.3 GLOSSARY / DATA_LINEAGE note: β_d/φ/κ are visualised as added-variable panels (posterior line + HDI), if those docs describe the params.
