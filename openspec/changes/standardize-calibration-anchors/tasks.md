# Tasks — standardize-calibration-anchors

Sequencing: **VDOT-first vertical slice** (ships the live 49/35.7/35.8 fix end-to-end and proves the sync-confirm UX), then extend policies to LTHR/AeT/MaxHR.

## Phase 1 — Shared anchor layer + VDOT policy

- [ ] 1.1 `fit/calibration.py`: `AGGREGATION_POLICY` table (per-metric estimator, window, min_samples, staleness, "differs-materially" threshold). VDOT entry first.
- [ ] 1.2 Estimator helper `_max_recency_decayed(rows, half_life_days, now)` — exp-decay weighting; returns value + contributing inputs.
- [ ] 1.3 `get_calibration_anchor(conn, metric) -> {value, confidence, method, inputs, suggestion}` applying the policy over the metric's rows (informational rows included as observations).
- [ ] 1.4 Config keys: `calibration.vdot_decay_half_life_days` (210), `vdot` staleness (120). Defaults if absent.
- [ ] 1.5 Tests: `tests/test_calibration.py::TestAnchorPolicyVDOT` — decay weighting, older-road-best beats fresh-trail, garmin-only fallback, min_samples fallback, suggestion payload shape.

## Phase 2 — VDOT as a first-class calibration metric

- [ ] 2.1 `fit/sync.py`: write informational `vdot` `race_estimate` rows from completed races (mirror LTHR path; idempotent by `source_activity_id`). Garmin VO2max persisted as informational `vdot` row too.
- [ ] 2.2 `fit backfill vdot` CLI (mirror `fit backfill rpe`).
- [ ] 2.3 `fit/fitness.py`: `_get_race_vdot`/`_compute_effective_vdot` reimplemented via the VDOT policy (recency decay, no 180d cliff); `get_fitness_profile` reads `get_calibration_anchor`. `get_fitness_anchors` kept only as the qualifying-effort detector feeding estimate rows.
- [ ] 2.4 Tests: `tests/test_fitness.py` — effective_vdot no longer cliffs at 180d; trail race doesn't lower it.

## Phase 3 — Governance: confirm-at-sync (cross-metric, build once)

- [ ] 3.1 Pending-suggestion store + ledger (rejected value/date per metric) — schema or a small JSON sidecar; decide in 3.0.
- [ ] 3.2 `fit/sync.py`: after ingest, compare suggestion vs active per `differs_materially`; TTY → prompt accept/reject; non-TTY → persist pending, never block.
- [ ] 3.3 Accept writes `{method:'confirmed', confidence:'high', active:1}`; reject records ledger entry.
- [ ] 3.4 Surface pending suggestions in `fit status`, dashboard attention panel, and `fit calibrate <metric>`.
- [ ] 3.5 Tests: interactive-accept, headless-persist, ledger-no-renag, slow-trail-no-prompt.

## Phase 4 — Dashboard reads + VDOT history

- [ ] 4.1 `_vdot_comparison`, `_pace_zones`, `_race_countdown` read `get_calibration_anchor(conn,'vdot')` (replaces the interim `get_fitness_anchors` edit from `ba220e5`).
- [ ] 4.2 Calibration History: add a `vdot` series.
- [ ] 4.3 Update `tests/test_pace_anchor.py` to assert paces follow the standardized anchor (not latest-effort).
- [ ] 4.4 `mcp/server.py`: coaching context reads the shared anchor (keep MCP/skill contract per CLAUDE.md).

## Phase 5 — Extend policies to LTHR / AeT / MaxHR

- [ ] 5.1 `_robust_center(rows, window, trim)` (median/trimmed mean) — LTHR (270d, min 3), AeT (120d, min 3).
- [ ] 5.2 `_plausibility_gated_max(rows, age_decay)` — MaxHR (all-time, ~0.7 bpm/yr, reject implausible highs).
- [ ] 5.3 Wire LTHR/AeT/MaxHR into `AGGREGATION_POLICY`; their consumers already read `get_calibration_anchor`.
- [ ] 5.4 Calibration History series for all four; per-metric staleness thresholds set explicitly.
- [ ] 5.5 Tests per estimator (hot-day-high doesn't win LTHR; strap-glitch rejected for MaxHR; AeT trimmed median).

## Validation

- [ ] `openspec validate standardize-calibration-anchors --strict`
- [ ] full `pytest` green
- [ ] dashboard renders; VDOT consistent across VDOT section / Pace Zones / forecast
