## Why

The marathon forecast's interval is "the posterior of the mean curve + the extrapolation wall penalty" (design Decision 3). But the **maximal-effort schedule** that supplies the effort covariate `h` is fed in as if it were *exact*:

- **β** (the duration–intensity fade slope) is a population point value (−6.5) with **no variance attached**.
- **T₀** (the threshold-duration) is a shrinkage point estimate whose standard error is **discarded**.

So the forecast is mildly **overconfident**: it ignores "we don't actually know your fade slope or threshold-duration exactly." That uncertainty is genuine *estimation* uncertainty of the mean curve (not race-day residual), so it belongs in the interval — and it matters most where we extrapolate the fade furthest from `T₀` (the marathon), exactly where honesty matters most.

This is the same shape the model already uses elsewhere: `β_d`, `φ`, `κ` are all `(mean, sd)` priors whose posterior spread flows into the interval, and the wall penalty already widens the interval with distance past `d_max`. The effort schedule is the one input still treated as certain.

## What Changes

Attach uncertainty to the effort schedule and propagate it into the forecast interval:

- **β** gets a prior **standard deviation** (`Normal(EFFORT_BETA_PRIOR, σ_β)`, σ_β ≈ 1.0–1.5 bpm/log-unit), justified from the within-curve segment-slope spread (−6.50 / −6.04 / −7.63) plus Riegel-exponent literature analogues. Documented as a judgment-informed prior, not a measured constant.
- **T₀** carries the standard error of its recency-/representativeness-weighted shrinkage estimate (the spread of the per-race implied-T₀ values, blended with the prior precision), instead of collapsing to a point.
- `effort_h_for_distance` (and the goal forecast) **draw (β, T₀) per posterior draw** and recompute the offset, so the spread flows offset → `h` → predicted log-time → interval. Implemented as a NumPy overlay alongside the existing wall penalty (same mechanism, design Decision 2), NOT as new PyMC parameters.

The widening scales with `|log t_goal − log T₀|`: ~±2–3 min (1 SD) added at the marathon, essentially zero for a goal near `T₀` (a half). The median is unchanged.

## Impact

- **Forecast interval is honestly wider for far extrapolations** — the marathon interval grows by the effort-assumption uncertainty, more than the half's, mirroring the distance wall penalty. The point estimate (3:59:30) does not move.
- **No median shift, no new model fit** — pure overlay; cheap; reuses the per-draw NumPy path.
- **Sets up change `maximal-effort-flag`** — once β is fitted from maximal efforts (that change), its *posterior* SD slots straight into this propagation, replacing the prior SD with no extra wiring.
- **Code**: `fit/marathon/predict.py` (`effort_schedule` returns `(t0, beta, t0_sd, beta_sd, …)`; `effort_h_for_distance` and `predict`/`forecast` sample them per draw). No DB/schema change.
- **Specs**: `adaptive-predictions` — a requirement that the forecast interval reflects effort-schedule (β, T₀) uncertainty.

Affected capability: **adaptive-predictions**. Depends on: `duration-keyed-effort-schedule` (this extends `effort_schedule`).
