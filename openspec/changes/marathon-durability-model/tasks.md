# Tasks — marathon-durability-model

## 1. Dependencies & scaffold
- [x] `forecast` extra (`pymc>=5`, `arviz`, `nutpie`, `scipy`) in `pyproject.toml`; installed (pymc 6.0.1 / arviz 1.1.0)
- [x] Create `fit/marathon/` package (NOT `fit/analysis/marathon/` — `fit/analysis.py` is a module), lazy PyMC imports

## 2. Features (no PyMC — pure pandas/numpy)
- [x] `extract_efforts(conn)`: effort SQL (races + Hard/Very-Hard tempo/progression; intervals excluded), `x/h`, `d_max`, drop-no-history; `tests/test_marathon_features.py` (8 tests)
- [ ] **REVISE `c`: use the existing chronic-load primitive** (trailing mean of daily `training_load`, ACWR's chronic denominator, point-in-time) — **drop the EWMA CTL/ATL** the first cut imported from the prototype (Decision 6: one shared load concept)
- [ ] **Goal-adaptive `D_REF`**: `x = log(d/goal)` with `goal = get_target_race(conn)` (not hardcoded 42.195); re-run feature tests
- [x] **Long-run pace-fade ratio** (`preparedness.long_run_pace_fade`) on the existing splits machinery, gated by `effort_class ≥ Moderate`

## 3. Preparedness penalty (Decision 2)
- [x] `fit/marathon/preparedness.py`: `extrapolation_prior` = `GENERIC_WALL_SCALE · shrink`, shrink from pace-HOLDING only (gap is the penalty multiplier's job, not re-encoded); **asymmetric, floored**
- [x] `GENERIC_WALL_SCALE`=0.04 labelled default; `defaulted=True` + reason when no qualifying long runs
- [x] Tests (`tests/test_marathon_preparedness.py`, 8): shrink monotone in quality, clamped [floor,1], default fallback, effort-gated. Real data: 3 long runs, −2.0% fade → floor

## 4. Model (Decisions 1, 5, 8)
- [x] `fit(efforts)`: drop δ; priors per design; no penalty term in the graph (`model.build_model`/`fit`)
- [x] nutpie (fallback NUTS); posterior cached to `~/.fit/marathon_posterior.zarr` (arviz 1.x needs no NetCDF C backend)
- [x] `diagnostics` gate (divergences/r̂/ESS) + `prior_predictive_minutes`; seeded smoke test. Real fit PASSES (0 div, r̂=1.0, ESS 779). [ppc/LOO-PIT plot TODO]
- [ ] Prior-vs-data movement summary for β_d et al. (Decision 5); prior-sensitivity re-fit in QA
- [ ] Verify pymc6 / arviz1 API (Context7) before writing — `pm.sample`/`az.summary`/`az.loo` changed since the v5 prototype
- [ ] Structure tests via `pymc.testing.mock_sample`

## 5. Predict & derived
- [x] `predict.predict` + `predict.forecast`: predict-time `HalfStudentT(ν=4, extrapolation_scale)` overlay, `pen=γ·max(0,log(d/d_max))`; interval = posterior-of-mean + penalty (NOT residual σ); p_ceiling
- [x] `trend_series` — marathon-equiv tracking chronic load over time (replaces the table-based chart)
- [x] `derived_metrics`: β_d/φ/κ (prior-vs-data flag), race-equivalency (per-distance HR schedule + penalty), `required_chronic_for_goal`
- [x] `influence` via `az.loo` Pareto-k vs adaptive `good_k`; `residuals` (observed−predicted, day-quality) for the correlation engine
- [x] Tests (`tests/test_marathon_model.py`): overlay wider, pen=0 within range, p-ceiling monotone, derived structure, required-chronic, trend, influence (slow)

## 6. Unified durability + extrapolation watch view (Decision 9 — REQUIRED, the one new chart)
- [ ] Decomposed headline: power-law base + penalty band, with `GENERIC_WALL_SCALE` (generic) and zero-penalty baselines
- [ ] One durability panel uniting existing `resilience` drift-onset (HR:pace) + new pace-fade (speed) + long-run distance progression; state the drift-vs-pace-fade difference
- [ ] Tracked series: penalty % / `extrapolation_scale` vs `GENERIC_WALL_SCALE` baseline; preparedness inputs (longest run, pace-fade)
- [ ] Validation overlay: actual vs band once a goal-distance-class (≥~30 km) effort exists; else "unvalidated extrapolation"
- [ ] Guardrail tests: thin/noisy or far-from-`GENERIC_WALL_SCALE` → fallback + label

## 7. Integration
- [x] `fit/sync.py`: `_refit_marathon_forecast` step (best-effort; skips without extra/history, never blocks sync)
- [x] Report: `_marathon_forecast` section → Overview headline (median + 90% interval + P-ceiling + β_d + race-equivalency + unvalidated banner + influential efforts); degrades to anchor. [trend-chart re-source + watch panel: TODO]
- [x] `fit/cli.py`: `fit forecast` (--refit/--hr) — headline+interval+P, durability, race-equivalency, required-chronic, influential efforts; degrades to anchor
- [ ] **Graceful degradation** (Decision 7): no pymc / stale posterior → anchor headline + loud note; assert never the retired table

## 8. LTHR source — DONE (ingest the watch's lactate threshold)
- [x] `garmin.fetch_lactate_threshold` — `/userprofile-service/userprofile/personal-information` → `biometricProfile.lactateThresholdHeartRate`
- [x] `sync._sync_lactate_threshold` — store as `garmin_lt` calibration row, only when changed (≥1 bpm) → LT time-series
- [x] `DEVICE_METHODS` + anchor device-tier: human-confirm > device (garmin_lt) > race-proxy policy > legacy; device excluded from the race-suggestion median
- [x] Tests (`tests/test_lthr_ingestion.py`, 8) + live-confirmed: anchor 164 (proxy) → **173** (watch)

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
