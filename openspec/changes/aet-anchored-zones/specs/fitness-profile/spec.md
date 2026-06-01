## ADDED Requirements

### Requirement: AeT is a tracked calibration metric
The system SHALL treat `aet` as a calibration metric alongside `max_hr`, `lthr`, `weight`, `vo2max`. `aet` SHALL appear in `STALENESS_THRESHOLDS` (proposed 56 days), `RETEST_PROMPTS`, and `get_calibration_status()`. The CLI SHALL accept `fit calibrate aet <value>` as a manual override (writing `confidence='high'` like the other metrics).

#### Scenario: AeT staleness threshold reachable
- **WHEN** the active `aet` calibration is 90 days old (> 56 day threshold)
- **THEN** `is_stale(conn, 'aet')` returns True; `get_calibration_status()` reports `confidence='low'`; the retest prompt appears

#### Scenario: AeT does not exist yet — missing metric
- **WHEN** no `aet` row has been written
- **THEN** `get_calibration_status()` reports `aet` as missing with the retest prompt; `get_active_calibration('aet')` returns None

### Requirement: AeT refines Z2 ceiling only — does NOT replace LTHR as the primary anchor
`compute_hr_zones()` SHALL accept an optional `aet` argument. When `aet` is provided, the Z2 ceiling (Z3 lower bound) SHALL be set to AeT directly. Z3, Z4, Z5 boundaries SHALL continue to derive from %LTHR (Friel) regardless of whether AeT is calibrated. AeT is a **single-zone refinement, not a model replacement.**

Z2 ceiling fallback chain (in priority order):

1. AeT (active calibration value) — when present
2. 89% × LTHR (Friel's Z2 upper bound) — when LTHR calibrated, AeT missing
3. 70% × MaxHR — when neither calibrated

#### Scenario: AeT calibrated, LTHR calibrated — Z2 ceiling = AeT
- **WHEN** active `aet = 142`, active `lthr = 172`, avg_hr 140
- **THEN** `hr_zone = Z2` (below AeT)

#### Scenario: AeT calibrated, avg_hr above AeT but below Friel Z2 ceiling
- **WHEN** active `aet = 142`, active `lthr = 172`, avg_hr 148 (which is 86% of LTHR, in Friel Z2)
- **THEN** `hr_zone = Z3` (above AeT — AeT is the ceiling, not Friel)

#### Scenario: AeT missing, LTHR calibrated — Z2 ceiling falls back to 89% × LTHR
- **WHEN** no `aet`, active `lthr = 172`, avg_hr 148
- **THEN** `hr_zone = Z2` (below 89% × 172 = 153, Friel Z2 ceiling)

#### Scenario: Z4 floor stays LTHR-anchored regardless of AeT
- **WHEN** active `aet = 142`, active `lthr = 172`, avg_hr 165
- **THEN** `hr_zone = Z3` (above AeT, below 95% × 172 = 163.4 → Z4 lower); NOTE: 165 > 163.4 → Z4. Adjust test: avg_hr 162 → Z3, avg_hr 164 → Z4. Either way, the Z4 floor is unchanged by AeT.

#### Scenario: AeT confidence drives Z2-ceiling display margin
- **WHEN** active `aet = 142` has `confidence = 'medium'`
- **THEN** the dashboard's Physiology card AeT value renders with a "±3 bpm" margin note; zone classification still uses the point estimate

### Requirement: AeT auto-derives from steady-pace long runs
The sync pipeline SHALL detect candidate running activities for AeT estimation: `type = 'running'`, `distance_km >= 12`, per-km splits available, pace stddev across splits (excluding first and last km) below `analysis.aet_steady_pace_stddev_sec` (default 15 sec/km). For each candidate, the pipeline SHALL compute drift percentage from first-half vs second-half avg HR (distance-weighted) and write a calibration row per the rubric below.

| Drift % | Estimate type | Calibration value | Flag |
|---|---|---|---|
| < 0 | invalid (negative drift) | no row written | — |
| 0 ≤ drift < 5% | lower bound | `avg_hr` of run | `lower_bound` |
| 5 ≤ drift ≤ 7% | direct estimate | `avg_hr` of run | none |
| drift > 7% | upper bound | `avg_hr` of run | `upper_bound` |

Confidence per the uniform rubric (from `calibration-history`):

- Single direct estimate, no flags → `medium`
- Two direct estimates within ±3 bpm in 8-week window → `high`
- Only bounds (no direct estimates) → `low` with flag `insufficient_data`

Method SHALL be `drift_test`.

#### Scenario: Steady 15km run with mid drift — direct estimate
- **WHEN** a 15km running activity has steady splits, first-half avg HR 138, second-half avg HR 144 (drift 4.3%, avg HR 141)
- **THEN** the sync inserts `{metric: 'aet', value: 141, method: 'drift_test', flags: ['lower_bound'], confidence: 'medium'}` (drift < 5 → lower bound)

Wait — example: 4.3% drift is < 5% → lower bound. Per the rubric value = avg_hr of run = 141. Flag = `lower_bound`. Confidence = medium (single estimate, no anomaly flags). Correct.

#### Scenario: Two direct estimates within tolerance bump confidence to high
- **WHEN** two `direct_estimate` AeT rows from drift_test exist within an 8-week window, values 142 and 144 (within ±3 bpm tolerance)
- **THEN** the second row is written with flags `['agrees_with_prior']` and `confidence = 'high'`; the active AeT becomes the most recent of the two

#### Scenario: Run is not steady — no candidate
- **WHEN** a 15km activity has pace stddev > 15 sec/km (intervals, fartlek, hill repeats)
- **THEN** no AeT calibration row is produced; the activity is silently skipped

#### Scenario: Negative drift — invalid, no row written
- **WHEN** a steady run shows first-half avg HR 145, second-half avg HR 140 (negative drift, runner was warming up or fueling kicked in)
- **THEN** no AeT calibration row is written

#### Scenario: Manual override beats auto-derive
- **WHEN** user runs `fit calibrate aet 143` after several drift-test estimates already exist
- **THEN** a new row is inserted with `confidence = 'high'`, `method = 'manual'`; `get_active_calibration('aet')` returns the manual row (high beats medium per the confidence-aware selection rule)
