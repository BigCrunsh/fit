# Tasks — maximal-effort-flag

**Scope decision (2026-06-17):** explicit (RPE) + manual override; **heuristic deferred** to a
follow-on (RPE covers only 2/21 races today, so the fragile HR-near-ceiling heuristic isn't worth
its risk yet — manual flagging gives the β-fit cleaner input). **Feel dropped** as a signal — it's a
strong↔weak subjective scale orthogonal to exertion (all-out RPE-10 races read feel 1–2). The β-fit
consumes maximal **races only** (sustained efforts where avg HR is the effort), not RPE-9 tempos/
intervals. T₀ keeps its at-threshold proxy (more data, incl. HMs) but now uses the **fitted** β.

## 1. Schema + ingest
- [x] Migration `017_activity_maximal_effort.sql`: add `is_maximal` (INTEGER) + `max_effort_source` (TEXT) to `activities`
- [x] Derivation (`derive_maximal_effort` in `analysis.py`; sync step 8a1 + `fit backfill maximal`): RPE ≥ 9 → maximal('rpe'); recorded RPE below → not('rpe'); no RPE → NULL. Idempotent; never clobbers `source='manual'`. **Feel not used.**
- [x] `fit effort maximal <activity_id> [--no|--auto]` CLI: manual override (sticky); `--auto` clears and re-derives
- [ ] ~~Heuristic fallback (HR-near-ceiling + even pacing)~~ — **DEFERRED** (follow-on; fragile, not needed at current RPE coverage)

## 2. Fit β from maximal efforts (`fit/marathon/predict.py`)
- [x] `_fit_beta`: prior-regularized weighted-regression slope of (avg_hr − LTHR) vs log(duration) over maximal **races**; data slope (floored SE) Bayes-combined with N(EFFORT_BETA_PRIOR, EFFORT_BETA_PRIOR_SD); returns (β, β_sd, fitted)
- [x] `effort_schedule`: β fitted from `is_maximal=1 AND run_type='race'`; gated on ≥3 races (else prior, `beta_fitted=False`); returns `beta`, `beta_sd`, `beta_fitted`
- [x] T₀ uses the **fitted** β in its implied-T₀ formula; keeps the at-threshold (offset≥0) proxy for the anchor (more data than RPE-only maximal races today — a deliberate, documented divergence from the original "T₀ from maximal efforts")
- [x] Cold-start / <3 maximal races → β stays the population prior, `beta_fitted=False` (never less robust)
- [x] β's SE (`beta_sd`) feeds `effort-schedule-uncertainty` (replaces the hand-set σ_β when fitted)
- [x] SSOT: inspection panel + `marathon_forecast` show fitted (solid line, "β fitted from N races") vs prior (dashed)

## 3. Tests
- [x] Determination: RPE 9/10 → maximal; RPE < 9 → not; no RPE → NULL; feel ignored; manual sticky; `--auto` restores derived; idempotent; non-running not flagged (`TestDeriveMaximalEffort`)
- [x] β-fit excludes sub-maximal/non-race: easy races (is_maximal=0) and maximal tempos don't feed β (`TestBetaFit`)
- [x] Prior-regularization: <3 races → prior; consistent maximal races → β moves toward data + SE tightens; perfect-fit few points → floored SE, β stays regularized
- [x] 2:1 unhappy ratio met across both classes

## 4. Validation (real data)
- [x] Maximal flags: 4 maximal **races** (3K/3K/10K/10K), tempos/intervals flagged but excluded from the fit
- [x] Fitted β = −6.20 ± 1.16 (data slope ≈ −4.4, regularized toward the −6.5 prior); NOT the contaminated −2.3; headline 3:57:42 → 3:57:15 (small, data-driven)
- [x] β's SE flows into the interval (beta_sd 1.25 → 1.16); dashboard regenerated, inspection panel shows the fitted solid line
- [x] cross-surface: forecast card β reading + inspection panel both reflect the fitted slope

## 5. Docs
- [x] `CLAUDE.md`: β is now fitted from maximal **races** (prior-regularized); RPE-only precedence + Feel dropped + manual sticky; superseded the "β deliberately NOT fit" note
- [x] `DATA_LINEAGE.md`: added the `is_maximal` flag + RPE source to the effort-schedule lineage + the derivation row
- [x] `effort_schedule` docstring: β now fitted from maximal races; T₀ uses the fitted β
