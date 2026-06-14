# Design — durability-param-panels

## Context

`durability_panel(idata, ds, c_ref, maximal_h, …)` (fit/marathon/predict.py) already produces the durability collapse: it normalises every effort to a common fitness `c_ref` and maximal effort `maximal_h` by removing `φ·(c−c_ref)` and `κ·(h−maximal_h)`, then plots distance vs the normalised time with the β_d power-law curve + a posterior band. That is an **added-variable plot** for β_d. This change mirrors it for φ and κ — netting out the *other two* covariates — and renders all three with explicit posterior uncertainty.

Model (LTHR-anchored): `mu = α + β_d·x + φ·c + κ·h`, `x = log(d/goal)`, `c = (chronic−50)/10`, `h = (HR−LTHR)/5`, StudentT(ν) likelihood. Posteriors of `α, β_d, φ, κ` and the per-effort `(x, c, h, logt)` are available via `forecast_context`.

## The three panels (one shared idiom)

Each panel isolates one covariate by removing the other two from each effort's `logt`, then shows the coefficient as the slope of the remaining relationship:

| Panel | x-axis | net out | line slope | impact label |
|------|--------|---------|-----------|--------------|
| β_d  | log distance (km) | `φ·(c−c_ref)`, `κ·(h−maximal_h)` | β_d | "×2.09 time per ×2 distance" |
| φ    | fitness — **CTL** = `c·10+50` | `β_d·x`, `κ·(h−maximal_h)` | φ | "+10 CTL ⇒ −2.1 min" |
| κ    | effort — **bpm above LTHR** = `h·5` | `β_d·x`, `φ·(c−c_ref)` | κ | "+5 bpm ⇒ −2.4% (~−8 s/km)" |

`c_ref` = today's fitness, `maximal_h` = the goal's maximal-effort h (so the β_d panel's goal point equals the headline forecast — consistency, as `durability_panel` already does).

## Bayesian-honest rendering (the review's fixes)

- **Posterior, not a point.** For each panel the line is the posterior **median** over a covariate grid; an **HDI ribbon** (5–95%) is drawn from posterior draws of the mean (`α + β·x + φ·c + κ·h` evaluated along the grid with the other covariates at their operating values). The ribbon is the primary visual.
- **Prior-dominated → greyed.** When `dm[…]["prior_dominated"]` is set, the line+ribbon render grey/dashed with a "prior-dominated (thin data)" tag — the slope is mostly the prior and the points won't trend; we must not imply confidence.
- **Slope-0 reference.** A faint horizontal (zero-slope) guide so "could be flat / no effect" is visible (ArviZ `ref_val=0` idiom).
- **Operating-point marker** ("you are here"): today's CTL (φ), the assumed race-HR (κ), the goal distance (β_d).
- **Partial-residual points** are netted out at posterior **medians** (illustrative scatter); captioned "points are netted-out, not raw runs." Influential efforts (existing LOO `influence`) marked.
- **Shared log-time y-axis** across all three → a slope is a straight line and the panels are visually comparable.

## Decisions

### Decision 1 — added-variable plots, not marginal scatters
Net out the other two covariates so the slope equals the coefficient. **Anti-recommendation: plot raw covariate vs raw time** — rejected: confounded (long races are also harder/fitter), so the raw slope is not β_d/φ/κ and would mislead.

### Decision 2 — HDI ribbon + median line, never a bare line
The slope's posterior is the figure. **Anti-recommendation: a single median line** — rejected: it hides uncertainty; a barely-determined φ would look as confident as a sharp β_d. We already expose the intervals (`*_ci`), so the data is there.

### Decision 3 — prior-dominated panels are greyed + tagged
**Anti-recommendation: render all panels identically** — rejected: on thin data the line is the prior and the points are flat; an un-greyed panel fabricates confidence. Use the existing `prior_dominated` flag.

### Decision 4 — log-time y-axis (user-chosen)
The coefficient is linear in log-time; in minutes it curves. **Anti-recommendation: linear minutes** — rejected: "see a slope as a slope" requires log; also matches the collapse's log-log. Tick labels still render h:mm so minutes stay readable.

### Decision 5 — keep all three panels AND the big collapse (user-chosen)
The 3-panel row is the comparable summary; the full-width collapse stays as the detailed β_d view (wall band, distance extrapolation). **Anti-recommendation: drop the collapse or drop the β_d mini** — rejected: the user wants all three comparable; the β_d mini cross-links to the collapse to avoid a sense of redundancy.

### Decision 6 — points netted at medians; line/ribbon from draws
The inferential content (line + ribbon) propagates posterior uncertainty; the scatter is netted at medians for tractability and captioned as partial residuals. **Anti-recommendation: net the points per-draw too** — deferred: it muddies the scatter for little gain once the ribbon already carries the uncertainty.

### Decision 8 — stacked decomposition; β_d's panel IS the collapse (as-built, from review)
After the Prediction Trend: the model formula (α/β_d/φ/κ each explained, incl. how fitness=CTL and effort=HR-vs-LTHR are computed), then a graph per coefficient **stacked vertically** (user preference over side-by-side). β_d's panel **is the durability collapse** — they were the same picture, so the separate β_d mini was dropped (the collapse keeps its unique extrapolation band). Each panel adds a **rise/run slope triangle** (the literal "the coefficient is this slope"; β_d's reads "×2 dist → ×2.09 time = 2^β_d"), **distance-coloured points + run-identifying tooltips** (matching the collapse), and a **red ring on the most-recent run** as a shared temporal reference. **Anti-recommendation: three uniform side-by-side mini-panels incl. a β_d mini** — rejected: duplicated the collapse, lost its extrapolation band, and read as redundant.

### Decision 7 — test via `pymc.testing.mock_sample`
Build a tiny model with known coefficients, mock-sample, and assert each panel's median-line slope ≈ the known coefficient (in log-space), the ribbon widens with a wider posterior, and `prior_dominated` flows to the greyed flag. **Anti-recommendation: real MCMC in tests** — rejected: slow; structure/shape is what we're guarding (pymc-testing skill).
