# Tasks — effort-schedule-uncertainty

## 1. Schedule uncertainty (`fit/marathon/predict.py`)
- [x] `EFFORT_BETA_PRIOR_SD` (~1.25) constant, justified per design (within-curve slope spread + Riegel analogues); documented as a judgment-informed prior, not measured
- [x] `EFFORT_T0_PRIOR_LOG_SD` (~0.35, spanning ≈40–80 min) constant — NEW; the prior log-SD on T₀ that makes σ_T₀ go WIDE (not collapse) at cold-start
- [x] `effort_schedule(ds)` also returns `beta_sd` (= `EFFORT_BETA_PRIOR_SD`) and `t0_sd` — the **precision-weighted posterior log-SD** `1/σ² = 1/EFFORT_T0_PRIOR_LOG_SD² + n_eff/s²_log` (s²_log = weighted variance of log(implied_T₀)); NOT `λ·spread`. Defaulted/cold-start → `t0_sd = EFFORT_T0_PRIOR_LOG_SD`. Additive keys (existing callers read by key).

## 2. Propagation (interval only; median unchanged)
- [x] `effort_h_for_distance` per-draw mode (opt-in kwarg; scalar path unchanged as default): run the 2-pass coupling ONCE for the operating duration t*, then sample `β_i ~ N(β, σ_β)`, `log T₀_i ~ N(log T₀, σ_logT₀)` → array of `h_i`; vectorise the reserve cap with `np.minimum` (not scalar `min`)
- [x] RNG isolation: draw `(β_i, log T₀_i)` from a generator deterministically derived but SEPARATE from the wall-penalty stream (`default_rng(seed).spawn(2)`), so the wall penalty is byte-identical regardless of effort sampling
- [x] `predict` accepts scalar-or-array `h`: **median from point-h, percentiles from array-h** (median unchanged by construction)
- [x] `forecast`/`derived_metrics`/`trend_series` interval paths use the sampled `h`
- [x] `durability_panel` (Panel A) — sample `β_i/log T₀_i` and recompute `maximal_h_i` INSIDE its inline curve loop (it does NOT route through the per-draw `predict`); reuse the converged operating duration
- [x] β and log T₀ drawn independently — documented approximation (negatively correlated in truth), revisited under `maximal-effort-flag`

## 3. Inspection panel (Profile tab — Decision 5)
- [x] `effort_schedule_panel(idata, ds)` in `predict.py` → `{line, band (90%), dots (hard filled / sub-threshold hollow), t0, t0_sd, std_markers, defaulted}`; std markers at the model-PREDICTED durations via `effort_h_for_distance` (point estimates, reserve cap applied)
- [x] `_effort_schedule_panel_chart` in `charts.py` — NEW dedicated builder (not an overload of `_param_panel_chart`); x = duration (min, log), y = offset bpm vs LTHR (linear, zero-line); band-first, dashed prior line tagged "β = population prior (not fitted)", reuse `_slope_triangle_annots`/`_recent_marker_annot`
- [x] Wire into the "The forecast, decomposed" sec-group as the 4th panel (`chart-effort-schedule`); gate on `source==model AND not defaulted AND ≥2 hard dots`
- [x] Athlete-readable `.param-panel-cap` with the bpm-not-minutes disclaimer

## 4. Captions / SSOT (prose must match the wider band)
- [x] Update the Marathon-Prediction def-box, Panel A caption, and `race_prediction` explainer (`cards.py`) to attribute band width to effort-assumption uncertainty too (not only the wall penalty)
- [x] (optional) one clause in `fit-coach/SKILL.md`: interval = mean-curve posterior + wall + effort-assumption uncertainty

## 5. Tests (`tests/test_marathon_model.py`) — 2:1 unhappy:happy
- [x] Median forecast EXACTLY unchanged vs the point-(β,T₀) path
- [x] Marathon 90% interval WIDER with propagation on than off
- [x] σ_β=σ_T₀=0 → band byte-identical to today (proves no RNG-stream contamination of the wall penalty)
- [x] Cold-start / defaulted schedule → WIDEST effort band (proves σ_T₀ uses the wide prior, NOT a collapsed sample SD)
- [x] Single / near-identical hard races → `t0_sd` does NOT collapse to ~0
- [x] HM interval ≈ unchanged (widening scales with |log t_goal − log T₀|)
- [x] β-only vs β+T₀: T₀ contributes materially at the marathon (guard against dropping it)
- [x] Seed-determinism; reserve cap binds elementwise (`np.minimum`)
- [x] Combined wall+effort marathon 90% half-width stays under a documented sanity cap

## 6. Validation (real data)
- [x] Before/after: median unchanged (3:57:42 model median); marathon 90% width +1.6 min (≈±2.3 min 1 SD); HM widens materially less (~±0.9 min 1 SD)
- [x] Report effort-uncertainty vs wall-penalty band components SEPARATELY (debug/doctor) → confirm not double-counted; sensitivity-test marathon width at σ_β ∈ {1.0, 1.25, 1.5}
- [x] Regenerate dashboard; the wider band shows on the Overview hero + Profile Panel A/B; the inspection panel renders; CLI matches

## 7. Docs
- [x] marathon design-of-record (`predict.py` module docstring): effort-schedule uncertainty added to the interval definition (no standalone marathon `design.md` exists)
- [x] `DATA_LINEAGE.md`: interval = mean-curve posterior + wall penalty + effort-schedule (β,T₀) uncertainty; effort-schedule panel row added
- [x] `CLAUDE.md`: the forecast interval now reflects effort-assumption uncertainty (grows with extrapolation from T₀); notes `EFFORT_T0_PRIOR_LOG_SD` and the independent-draw approximation
- [x] `fit-coach/SKILL.md`: interval = mean-curve posterior + wall + effort-assumption uncertainty
