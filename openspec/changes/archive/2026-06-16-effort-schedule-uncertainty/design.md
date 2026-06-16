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
  recency-/representativeness-weighted mean of per-race implied-T₀ values. **σ_T₀ is the
  precision-weighted POSTERIOR log-SD**, blending a new prior width with the data spread:
  `1/σ_T₀² = 1/σ_T₀,prior² + n_eff / s²_log`, where `s²_log` is the weighted variance of
  `log(implied_T₀)` and `n_eff = Σw` is the effective race count. **Do NOT shrink the SD by `λ`:**
  `λ = n_eff/(n_eff+pseudo)` is a *mean*-shrinkage weight; applying it to the SD would collapse the
  band toward zero exactly when data is thinnest (`n_eff→0 ⇒ λ→0 ⇒ σ→0`), the opposite of intended.
  The precision form gives the right cold-start behaviour: thin/cold-start data → σ_T₀ ≈ the prior
  width (wide); many consistent hard races → `n_eff/s²_log` dominates → tight. This requires a new
  constant **`EFFORT_T0_PRIOR_LOG_SD`** (≈0.35, spanning roughly 40–80 min around the 55-min prior).

## Propagation

In `effort_h_for_distance` / the goal forecast, for the N posterior draws already used by
`predict`, draw `β_i ~ Normal(β, σ_β)` and `log T₀_i ~ Normal(log T₀, σ_logT₀)` and compute
`offset_i = β_i·(log t(d) − log T₀_i)`, then `h_i`, then the predicted time per draw. The offset
spread flows into the existing `secs` array, so the 5th/95th percentiles widen. Reuses the NumPy
overlay path of the wall penalty (design Decision 2) — no PyMC change.

**RNG isolation (correctness-critical).** The `(β_i, log T₀_i)` draws MUST come from a generator
*deterministically derived but separate* from the one `_wall_penalty_draws` consumes (e.g.
`np.random.default_rng(seed).spawn(2)` → one child for the wall, one for effort). Sharing a single
`default_rng(seed)` stream would shift the Student-t draw order, silently changing the wall penalty
for every distance with `gap>0` (including the marathon) — breaking the "median unchanged / HM
unchanged" guarantees for reasons unrelated to effort. The reserve cap must be vectorised
(`np.minimum(off_array, hr_reserve)`), not the scalar `min()` in `maximal_effort_h`.

`β_i` and `log T₀_i` are drawn **independently**, which is an approximation: `T₀` is estimated
*conditional* on `β`, so they are negatively correlated in truth. Documented as acceptable for this
prior-σ step (the correlation tightens the band slightly; independent is the conservative/wider
choice) and revisited under `maximal-effort-flag` when β is fitted with a real joint posterior.

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
hand-set number, flagged as such. σ_T₀ falls out of the existing weighted estimate **plus** a prior
width `EFFORT_T0_PRIOR_LOG_SD` (precision-weighted posterior log-SD; see "The two uncertainties").
Both behave sensibly at cold-start (σ_β = the prior; σ_T₀ → the prior width, i.e. wide).

### Decision 5 — ship the effort-schedule inspection panel WITH this change
Add a Profile-tab diagnostic panel (offset-vs-duration) as the fourth panel in "The forecast,
decomposed" (β_d, φ, κ already have panels; the effort schedule `h` is the one input with no
visual). It plots the median fade line, the propagated 90% `(σ_β, σ_T₀)` band, the race efforts
(at/above-threshold filled + distance-coloured; sub-threshold parkruns hollow, so "why β isn't
fitted" is self-evident), the `T₀` anchor, and the 5K/10K/HM/M markers at their model-predicted
durations. **Anti-recommendation: defer to `maximal-effort-flag`** — rejected: the schedule is
invisible today and σ_β is hand-set, so a visual sanity-check of the fade law has diagnostic value
*now*, and shipping dots+line *without* the band in an earlier change would assert the very
certainty this change removes. **Build a NEW dedicated chart builder** (`_effort_schedule_panel_chart`),
not an overload of `_param_panel_chart` — that function's furniture (partial-residual netting, "no
effect" line, "you are here" on a netted covariate) is meaningless on a duration axis and bending it
risks regressing the φ/κ panels. **Misread guards:** band-first render; the line dashed + tagged
"β = population prior (not fitted)"; an explicit caption that the band is *assumed-effort* HR
uncertainty (not race-day HR variability, not comparable to the trend chart's minutes interval);
physical separation from the minutes-axis Panel B. **Gate** render on `source==model AND not
defaulted AND ≥2 at/above-threshold dots` — a lone prior line through no data is value-free.

## Migration

1. `effort_schedule(ds)` returns `t0_sd` and `beta_sd` alongside `t0`/`beta` (cold-start: `beta_sd
   = EFFORT_BETA_PRIOR_SD`, `t0_sd` wide).
2. `effort_h_for_distance(..., draws=None)` gains a per-draw mode: given the RNG/seed and N, returns
   an array of `h_i` (sampled β, T₀) rather than a scalar; `predict` consumes it elementwise.
3. `forecast`/`derived_metrics`/`trend_series` interval paths use the sampled `h`; the *median*
   uses the point (β, T₀) so the headline is unchanged. **`durability_panel` (Panel A) is NOT a free
   ride on `predict`** — it builds its band inline (its own curve loop) with `maximal_h` held fixed,
   so widening it requires sampling `β_i/log T₀_i` and recomputing `maximal_h_i` *inside* that loop
   (vectorised, reusing the converged operating duration). Budget it as a distinct, heavier step.
   `trend_series` holds σ_T₀ at today's value (it already resolves `effort_schedule` once and reuses
   it across weeks, recomputing only `c` as-of); the historical re-widening is second-order.
4. Validate: median unchanged (3:59:30); marathon 90% interval widens ~±2–3 min; HM interval ≈
   unchanged; cold-start athlete → widest. Report the effort-uncertainty band component separately
   from the wall-penalty component (a `fit doctor`/debug readout) so the two axes are auditable and
   the double-counting risk is testable, not eyeballed; assert a combined-width sanity cap.

## Risks

- **Double-counting with the wall penalty.** The wall penalty already widens past `d_max`; effort
  uncertainty is a *distinct* axis (HR assumption, not distance extrapolation). Keep them additive
  and label both; verify the combined interval is still calibrated (not absurdly wide).
- **σ_β is hand-set.** Mitigation: it's one documented constant; the marathon widening it produces
  (~±2–3 min) is small and clearly attributable; revisit when β is fitted (`maximal-effort-flag`).
- **Cost.** Per-draw sampling over the existing N draws is ~free (vectorised); no new sampling.
