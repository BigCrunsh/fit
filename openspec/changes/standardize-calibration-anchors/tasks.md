# Tasks — standardize-calibration-anchors

> The original VDOT-first phased plan evolved during implementation: the marathon
> *forecast* was split into its own change (`marathon-durability-model`), and two
> requirements emerged mid-build (suggest→confirm governance, point-in-time
> integrity). This list reflects what was actually built and shipped.

## Shared anchor layer + per-metric policy
- [x] `get_calibration_anchor()` — single read path; payload `{value, confidence, method, stale, inputs, suggestion}`
- [x] Two estimator families: `max` (VDOT, MaxHR) and `median` (LTHR, AeT); `_max_in_window` / `_median_in_window` / `_window_obs`
- [x] `AGGREGATION_POLICY` for all four metrics (windowed, staleness=window, sticky-confirm, differs); min_samples fallback
- [x] vdot added to `_PLAUSIBLE` / `_AGREE_TOLERANCE`
- [x] Tests: `test_anchor_policy.py` (max + median families, fallback, garmin exclusion, staleness)

## VDOT as a first-class metric
- [x] `backfill_race_vdot` + `backfill_effort_vdot` (races ∪ hard efforts); `effort_estimate`/`race_estimate` informational
- [x] `fit backfill vdot`; sync writes VDOT observations go-forward
- [x] `fit calibrate vdot [value] [--date]` confirms the sticky anchor (back-dating for corrections)

## Daniels pace fix (option 1, paces)
- [x] `compute_daniels_paces` anchors marathon pace on `vdot_to_race_time` (Daniels inverse), not the miscalibrated table
- [x] Pace test updated to the inverse

## Suggest→confirm governance + ledger
- [x] `evaluate_suggestions` / `accept_suggestion` / `reject_suggestion` + JSON ledger (`~/.fit/calibration_review.json`)
- [x] Surfaced: `fit sync` notice, `fit status` panel, dashboard attention panel, `fit calibrate` review flow
- [x] Tests: `test_calibration_governance.py`

## Point-in-time integrity (forward-only anchors)
- [x] `get_active_calibration(..., asof=)` — value active as of a past date
- [x] `enrich_existing_activities` classifies each activity with its as-of anchor (history not rewritten)
- [x] `fit calibrate --date` back-dating + `recompute --force` reclassifies only that window
- [x] Tests: `test_calibration_asof.py` (three-anchor period proof), `test_calibrate_cli.py`

## Dashboard + consumers
- [x] `_pace_zones`, `_vdot_comparison` read `get_calibration_anchor`
- [x] VDOT calibration-history chart (+ LTHR/AeT/weight); MaxHR/VO2max stat cards
- [x] Daniels/Riegel model assumptions in code + dashboard def-boxes
- [x] `effective_vdot` and the MCP coaching anchor line read `get_calibration_anchor`

## Deferred (intentionally, to `marathon-durability-model`)
- [ ] Marathon *forecast* re-sourcing (Bayesian model) — owns the forecast; consumes the LTHR anchor

## Validation
- [x] `openspec validate standardize-calibration-anchors --strict`
- [x] full `pytest` green (982); dashboard renders; VDOT consistent across VDOT section / Pace Zones / status / MCP
