# Design — effort-schedule-uncertainty

## Context

`effort_schedule(ds)` returns the maximal-effort fade law `offset(t) = β·(log t − log T₀)`. Today
it returns point values: β = the population prior (−6.5), T₀ = a shrinkage point estimate. The
forecast (`predict` + the wall overlay) consumes a single `h` per distance and treats it as exact.
The interval therefore reflects posterior spread in `α/β_d/φ/κ` + the wall penalty, but **zero**
spread from the effort assumption. This change attaches `(σ_β, σ_T₀)` and propagates them.

## The two uncertainties

- **σ_β — prior standard deviation on the fade slope.** Sources (all weak — documented, not
  measured): the validated table's own segment slopes span −6.50 / −6.04 / −7.63 (SD ≈ 0.8 within
  one athlete, conflating curvature with noise → a floor); Riegel-exponent literature reports
  cross-runner SD ~0.02–0.05 on the analogous time-distance fade. Net: **σ_β ≈ 1.0–1.5**
  bpm/log-unit as a moderately-informative prior.
- **σ_T₀ — standard error of the shrinkage estimate.** `effort_schedule` already computes a
  recency-/representativeness-weighted mean of per-race implied-T₀ values; their weighted spread
  (in log-space) is the data SE, shrunk by the same `λ` toward a prior width. Thin/cold-start data
  → wide σ_T₀ (we barely know it); many consistent hard races → tight.

## Propagation

In `effort_h_for_distance` / the goal forecast, for the N posterior draws already used by
`predict`, draw `β_i ~ Normal(β, σ_β)` and `log T₀_i ~ Normal(log T₀, σ_logT₀)` and compute
`offset_i = β_i·(log t(d) − log T₀_i)`, then `h_i`, then the predicted time per draw. The offset
spread flows into the existing `secs` array, so the 5th/95th percentiles widen. Reuses the NumPy
overlay path of the wall penalty (design Decision 2) — no PyMC change.

The widening is `≈ |κ|·|log t_goal − log T₀|·σ_β / H_DIV` (plus the T₀ term): it **grows with the
extrapolation distance from T₀**, so the marathon (t≈244, T₀≈95) widens ~±2–3 min at 1 SD while a
half (t≈110 ≈ T₀) barely moves. This is the right behaviour — it mirrors the wall penalty growing
with distance past `d_max`.

## Decisions

### Decision 1 — overlay sampling, not PyMC parameters (yet)
Sample (β, T₀) per draw in the NumPy overlay, exactly like the wall penalty. **Anti-recommendation:
make β/T₀ PyMC parameters now** — rejected: that's the heavier full-Bayesian step that only earns
its keep once β is *fitted* from data (the `maximal-effort-flag` change). Until then the overlay
gives the honest interval at a fraction of the cost, and when β-fitting lands, its posterior SD
drops straight into this same overlay.

### Decision 2 — propagate BOTH β and T₀
T₀ uncertainty shifts the whole curve's anchor; at the marathon it can dominate σ_β's contribution.
Propagating only β would understate the interval. **Anti-recommendation: β-only** (the user's
question was about β) — rejected: T₀ is the *less* certain of the two for a sparse-race athlete, so
omitting it is the bigger error.

### Decision 3 — interval definition unchanged; this is estimation uncertainty, not residual
The interval stays "uncertainty of the mean curve + wall" (design Decision 3 of the model); it does
NOT add race-day residual σ. Effort-schedule uncertainty IS mean-curve estimation uncertainty (we're
unsure what maximal HR to assume), so it belongs. P(goal) stays a fitness-sufficiency ceiling.

### Decision 4 — σ_β is a documented prior, σ_T₀ is data-derived
σ_β is judgment-informed (above) and lives as a named constant `EFFORT_BETA_PRIOR_SD`; it's the one
hand-set number, flagged as such. σ_T₀ falls out of the existing weighted estimate (no new
assumption). Both shrink/behave sensibly at cold-start (σ_β = the prior; σ_T₀ wide).

## Migration

1. `effort_schedule(ds)` returns `t0_sd` and `beta_sd` alongside `t0`/`beta` (cold-start: `beta_sd
   = EFFORT_BETA_PRIOR_SD`, `t0_sd` wide).
2. `effort_h_for_distance(..., draws=None)` gains a per-draw mode: given the RNG/seed and N, returns
   an array of `h_i` (sampled β, T₀) rather than a scalar; `predict` consumes it elementwise.
3. `forecast`/`derived_metrics`/`durability_panel`/`trend_series` interval paths use the sampled
   `h`; the *median* uses the point (β, T₀) so the headline is unchanged.
4. Validate: median unchanged (3:59:30); marathon 90% interval widens ~±2–3 min; HM interval ≈
   unchanged; cold-start athlete → widest. Document the magnitude in the marathon design notes.

## Risks

- **Double-counting with the wall penalty.** The wall penalty already widens past `d_max`; effort
  uncertainty is a *distinct* axis (HR assumption, not distance extrapolation). Keep them additive
  and label both; verify the combined interval is still calibrated (not absurdly wide).
- **σ_β is hand-set.** Mitigation: it's one documented constant; the marathon widening it produces
  (~±2–3 min) is small and clearly attributable; revisit when β is fitted (`maximal-effort-flag`).
- **Cost.** Per-draw sampling over the existing N draws is ~free (vectorised); no new sampling.
