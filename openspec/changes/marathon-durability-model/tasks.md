# Tasks — marathon-durability-model

## 1. Dependencies & scaffold
- [x] `forecast` extra (`pymc>=5`, `arviz`, `nutpie`, `scipy`) in `pyproject.toml`; installed (pymc 6.0.1 / arviz 1.1.0)
- [x] Create `fit/marathon/` package (NOT `fit/analysis/marathon/` — `fit/analysis.py` is a module), lazy PyMC imports

## 2. Features (no PyMC — pure pandas/numpy)
- [x] `extract_efforts(conn)`: effort SQL (races + Hard/Very-Hard tempo/progression; intervals excluded), `x/h`, `d_max`, drop-no-history; `tests/test_marathon_features.py` (8 tests)
- [ ] **REVISE `c`: use the existing chronic-load primitive** (trailing mean of daily `training_load`, ACWR's chronic denominator, point-in-time) — **drop the EWMA CTL/ATL** the first cut imported from the prototype (Decision 6: one shared load concept)
- [ ] **Goal-adaptive `D_REF`**: `x = log(d/goal)` with `goal = get_target_race(conn)` (not hardcoded 42.195); re-run feature tests
- [ ] **Long-run pace-fade ratio** (new, on existing second-half-pace machinery), gated by `effort_class ≥ Moderate`; long-run quantity from the existing long-run rule

## 3. Preparedness penalty (Decision 2)
- [ ] `fit/marathon/preparedness.py`: `s_drift(conn, goal)` = `s_default · shrink`, `shrink ∈ [floor,1]`, decreasing with extrapolation gap `log(goal/d_max)` + long-run quantity + pace-fade quality; **asymmetric (only reduces), floored, endpoint-anchored** (no free magnitude knob)
- [ ] `s_default` = labelled population fade scale (B's floor + fallback); fall back + log when preparedness data thin/noisy
- [ ] Tests: `shrink` monotone in gap + quality, never > 1, floored, `s_default` fallback, pace-fade gated by effort_class, goal-adaptive (half goal within data → ~no shrink headroom)

## 4. Model (Decisions 1, 5, 8)
- [ ] `fit(efforts)`: drop δ; priors per design; `mu = alpha + beta_d·x + phi·c + kappa·h` (**no penalty term in the graph**)
- [ ] Sample with `nuts_sampler="nutpie"` (fallback default NUTS/numpyro); **save posterior to `~/.fit/marathon_posterior.nc` immediately**
- [ ] Mandated workflow: prior-predictive plausibility → divergences==0 / r_hat<1.01 / ESS>400 → posterior-predictive + LOO-PIT; seeded smoke test
- [ ] Prior-vs-data movement summary for β_d et al. (Decision 5); prior-sensitivity re-fit in QA
- [ ] Verify pymc6 / arviz1 API (Context7) before writing — `pm.sample`/`az.summary`/`az.loo` changed since the v5 prototype
- [ ] Structure tests via `pymc.testing.mock_sample`

## 5. Predict & derived
- [ ] `predict(post, c, avg_hr, distance, goal) -> {median, lo, hi, p_ceiling}`; **extrapolation penalty = predict-time `HalfStudentT(ν=4, s_drift)` overlay** (ν=4 a labelled heavy-tail convention), `pen = γ·max(0, log(d/d_max))`
- [ ] `trend_series(post, daily_load)` — replaces the table-based trend charts
- [ ] `derived_metrics`: phi-value, layoff curve, β_d (prior-vs-data caveat), κ, live race-equivalency (per-distance penalty), required-fitness-for-goal
- [ ] `residuals` (day-quality) and `influence` via `az.loo(pointwise=True)` Pareto-k (flag k>0.7); `pm.compute_log_likelihood` first
- [ ] Tests: percentile shape, P-ceiling monotone in `c`, predict() with overlay wider than without, `pen=0` at `d≤d_max`, goal-adaptive

## 6. Unified durability + extrapolation watch view (Decision 9 — REQUIRED, the one new chart)
- [ ] Decomposed headline: power-law base + penalty band, with `s_default` (generic) and zero-penalty baselines
- [ ] One durability panel uniting existing `resilience` drift-onset (HR:pace) + new pace-fade (speed) + long-run distance progression; state the drift-vs-pace-fade difference
- [ ] Tracked series: penalty % / `s_drift` vs `s_default` baseline; preparedness inputs (longest run, pace-fade)
- [ ] Validation overlay: actual vs band once a goal-distance-class (≥~30 km) effort exists; else "unvalidated extrapolation"
- [ ] Guardrail tests: thin/noisy or far-from-`s_default` → fallback + label

## 7. Integration
- [ ] `fit/sync.py`: refit + cache step (gated/flagged)
- [ ] Report: re-source Marathon Prediction section/chart (median + interval + P-ceiling + trend + LOO flag); durability leads with measured signal, β_d optimistic bound (Decision 4)
- [ ] `fit/cli.py`: `fit forecast` command + refit trigger
- [ ] **Graceful degradation** (Decision 7): no pymc / stale posterior → anchor headline + loud note; assert never the retired table

## 8. LTHR source (open input — feeds `h` + maximal-effort HR)
- [ ] Decide: ingest Garmin watch lactate threshold vs confirm manually (`fit calibrate lthr`)
- [ ] If ingest: check `fit/garmin.py` / the Garmin client exposes lactate-threshold HR/pace; add fetch + store as a calibration row; let the anchor consume it

## 9. Retire Phase 2 of D1
- [ ] Replace the three trend consumers (`_prediction_trend_data`, trend badge, charts "VDOT (from VO2max)") with `trend_series`
- [ ] Delete `_vdot_to_marathon_seconds` + `_VDOT_TABLE` + the `TODO(marathon-durability-model)` flag; remove dead direct-table tests

## 10. Contract & docs
- [ ] Sync MCP coaching context + `fit-coach` SKILL.md to the new headline semantics (`CLAUDE.md` contract)
- [ ] Update `DATA_LINEAGE.md` (model lineage; `training_load` opaque) + `LINEAGE_REVIEW.md` status (F2/F4/F5/F6 closed)
- [ ] Def-box: extrapolation penalty, maximal-HR input, interval ≠ race-day spread, P = fitness-sufficiency ceiling

## 11. Validate
- [ ] `openspec validate marathon-durability-model --strict`
- [ ] Full suite green; `fit report` builds with and without the `forecast` extra
