# Tasks — marathon-durability-model

## 1. Dependencies & scaffold
- [ ] Add `forecast` extra (`pymc>=5`, `arviz`, `nutpie`, `scipy`) to `pyproject.toml`; keep core install light
- [ ] Create `fit/analysis/marathon/` package with lazy PyMC imports (never imported at module top level)

## 2. Features (no PyMC — pure pandas/numpy)
- [ ] `extract_efforts(conn)`: effort-selection SQL (races + Hard/Very-Hard tempo/progression; intervals excluded)
- [ ] CTL/ATL closed-form EWMAs (τ=42/7), loads strictly before each effort day; drop no-history efforts (logged)
- [ ] Build `x`, `c`, `h` (h uses `get_calibration_anchor('lthr')`, not hardcoded 172); compute `d_max`
- [ ] Tests: EWMA vs recursion (~1%), strict-before-day, SQL selection, d_max, drop-no-history (2:1 unhappy:happy)

## 3. Model (Decisions 1, 2, 5, 8)
- [ ] `fit(efforts)`: drop δ; priors per design; `mu = alpha + beta_d·x + phi·c + kappa·h` (**no penalty term in the graph**)
- [ ] Sample with `nuts_sampler="nutpie"` (fallback default NUTS/numpyro); **save posterior to `~/.fit/marathon_posterior.nc` immediately** after sampling
- [ ] Mandated workflow: prior-predictive plausibility → divergences==0 / r_hat<1.01 / ESS>400 → posterior-predictive + LOO-PIT; seeded real-sample smoke test
- [ ] Extrapolation penalty as a **predict-time NumPy overlay** (γ NOT in the graph): `gamma ~ HalfNormal(s_drift)`, add `gamma·max(0, log(d/d_max))` to predicted log-time
- [ ] **Drift→s_drift transform (Option B)**: end-of-run HR:pace drift `δ` → `p_drift ≈ k·δ` (k∈[0.5,1.5]) → set `s_drift` so penalty median ≈ p_drift; docstring states the 3 assumptions
- [ ] Compute the **Option-A fixed default `s_drift`** too (B's baseline + fallback); fall back + log when drift thin/noisy or B diverges from A beyond threshold
- [ ] Prior-vs-data movement summary for β_d et al. (Decision 5); prior-sensitivity re-fit in QA
- [ ] Tests (`pymc.testing.mock_sample` for structure): predict() with overlay strictly wider than without; penalty 0 at d≤d_max

## 4. Predict & derived
- [ ] `predict(post, ctl, avg_hr, distance) -> {median, lo, hi, p_ceiling}` (P labelled fitness-sufficiency ceiling)
- [ ] `trend_series(post, daily_load)` (Panel B line+band) — replaces the table-based trend charts
- [ ] `derived_metrics`: phi-value, layoff/detraining curve, β_d (with prior-vs-data caveat), κ, live race-equivalency, required-CTL-for-goal
- [ ] `residuals(post, efforts)` (day-quality, for the correlation engine)
- [ ] `influence(post, efforts)` via `az.loo(pointwise=True)` Pareto-k (flag k>0.7), not N manual refits; `pm.compute_log_likelihood` first (nutpie)
- [ ] Tests: percentile shape, P-ceiling monotone in CTL, Pareto-k influence flagging

## 4b. Extrapolation watch layer (Decision 9 — REQUIRED with Option B)
- [ ] Decomposed-headline panel: power-law base + drift-penalty band, with Option-A default and zero-penalty as baseline reference lines
- [ ] Tracked series: implied marathon-penalty % and `s_drift` over time vs the A-default baseline; plus drift inputs (resilience onset / drift %) over time
- [ ] Validation overlay: when a 30 km+ effort exists, plot actual vs predicted band; until then label "unvalidated extrapolation"
- [ ] Guardrail: divergence-from-A threshold + thin/noisy-drift check trips the A-fallback (visible label)
- [ ] Tests: B-vs-A divergence flag fires; fallback path; "unvalidated" label until a 30 km+ effort

## 5. Integration
- [ ] `fit/sync.py`: refit + cache step (gated/flagged) — Decisions 2,7
- [ ] Report: re-source Marathon Prediction section/chart from the model (median + interval + P-ceiling + trend + LOO flag)
- [ ] **Durability leads with measured drift-onset**, β_d as optimistic bound (Decision 4); def-box states assumptions
- [ ] `fit/cli.py`: `fit forecast` command + refit trigger
- [ ] **Graceful degradation** (Decision 7): no pymc / no/stale posterior → anchor headline + loud note; assert never the retired table
- [ ] Tests: degradation path, no `_vdot_to_marathon_seconds` import on the dashboard path

## 6. Retire Phase 2 of D1
- [ ] Replace the three trend consumers (`_prediction_trend_data`, trend badge, charts "VDOT (from VO2max)") with `trend_series`
- [ ] Delete `_vdot_to_marathon_seconds` + `_VDOT_TABLE` and the `TODO(marathon-durability-model)` flag; remove now-dead direct-table tests

## 7. Contract & docs
- [ ] Sync MCP coaching context + `fit-coach` SKILL.md to the new headline semantics (median+interval+ceiling) — `CLAUDE.md` contract
- [ ] Update `DATA_LINEAGE.md` (model lineage; mark `training_load` opaque) and `LINEAGE_REVIEW.md` status (F2/F4/F5/F6 closed)
- [ ] Def-box: extrapolation penalty, maximal-HR input, interval ≠ race-day spread, P = fitness-sufficiency ceiling

## 8. Validate
- [ ] `openspec validate marathon-durability-model --strict`
- [ ] Full suite green; `fit report` builds with and without the `forecast` extra installed
