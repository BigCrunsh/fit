# Tasks — duration-keyed-effort-schedule

Spec-first: nothing is implemented until the proposal + design are approved.

## 1. Schedule core (`fit/marathon/predict.py`)
- [ ] Population priors `EFFORT_T0_PRIOR_MIN` (~55) + `EFFORT_BETA_PRIOR` (~−6.5), with cited justification (the validation table + textbook threshold-duration). Plus the shrinkage/weight knobs as named constants: recency `EFFORT_TAU_DAYS` (~450), prior strength (pseudo-count / prior precision), representativeness bandwidth.
- [ ] `effort_schedule(ds)` — the **shrinkage estimate**: precision-weighted blend of the population priors and a weighted fit over the athlete's races (weight = recency `exp(−age/τ)` × representativeness near the goal duration). Returns `(t0, beta, defaulted, reason)`; `defaulted=True` (params == priors) when data is too thin to move off them. Mirrors the `extrapolation_prior` shape.
- [ ] `maximal_effort_h(predicted_minutes, t0, beta, hr_reserve=None)` — pure duration→h function; keep the MaxHR-reserve `min`-cap.
- [ ] `effort_h_for_distance(idata, ds, d, *, c, extrapolation_scale, nu, seed=0)` — two-pass coupling (seed h=0 → predict t(d) → recompute h → predict); assert |Δoffset| < 0.05 bpm. Resolves `(t0, beta)` once via `effort_schedule(ds)`.

## 2. Rewire callers
- [ ] `forecast`, `derived_metrics`, `required_chronic_for_goal`, `durability_panel`, `trend_series` → `effort_h_for_distance` (drop direct `maximal_effort_h(distance)`). Note `required_chronic`/`trend_series` vary `c`, so h is now recomputed per `c` (it's c-dependent under duration-keying).
- [ ] Display callers: `cli` forecast `eff_hr`, `cards._model_week_trend` → same helper
- [ ] Confirm goal-switch (marathon → HM) still reads the right point (regression check)

## 3. Tests (`tests/test_marathon_model.py`, `test_marathon_features.py`)
- [ ] Cold-start (prior-only) law reproduces the validated anchors within tolerance (5 K ≤0.5 bpm, M ≤1.5 bpm) at the athlete's durations
- [ ] Shrinkage: thin/no race data → params == priors + `defaulted`; rich consistent data → moves toward the athlete's fit
- [ ] **Robustness (the failure that motivated the prior):** a single sub-maximal short race at ~LTHR does NOT collapse T₀ (no 25-min result); a stale race is down-weighted; a bad-HR race can't move the estimate far (prior caps it)
- [ ] Recency: a recent block of races shifts T₀/β more than an equally-sized old block
- [ ] One-pass coupling converges (two-pass Δ < 0.05 bpm); seed-independence
- [ ] MaxHR-reserve cap still binds for a low-reserve synthetic athlete; no-op at reserve 22
- [ ] Duration-keying is goal-independent (same distance → same h regardless of goal)
- [ ] 2:1 unhappy: no efforts, all-sub-maximal, missing LTHR, single race only

## 4. Validation (real data) — the primary gate
- [ ] Before/after forecast diff; confirm marathon shift ≤ ~2 min and headline ≈ stable (shrinkage must reproduce the anchors)
- [ ] Re-validate against the athlete's actual race max-HRs (10 K 179, HM 173) as in the original schedule
- [ ] Confirm T₀ lands ≈ the athlete's half (~110–120 min), NOT a sub-maximal short race
- [ ] Regenerate dashboard; confirm cross-surface consistency (hero / block / Panel A / Panel B / CLI / MCP) holds
- [ ] CI-equivalent check (clean `.[dev]` venv + config hidden)

## 5. Docs
- [ ] marathon `design.md` "Constants & assumptions": swap the `_MAXIMAL_HR_OFFSET` rows for (prior, shrinkage) + the validation table
- [ ] `DATA_LINEAGE.md` glossary: maximal-effort schedule → duration-keyed (prior+data); add the effort-fade ↔ durability-fade consistency note
- [ ] `CLAUDE.md`: note the maximal-effort schedule is duration-keyed (prior+data), once shipped

## 6. D15 (separate, mechanical — can land independently)
- [ ] Route the three hardcoded Riegel `1.06`s (`predict_race_time`, `riegel_fallback_secs`, the inline `**1.06` in `predictions.py`) through one `RIEGEL_EXPONENT` constant so the durability fade is single-sourced
