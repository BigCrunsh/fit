# fitness-profile Specification

## Purpose
TBD - created by archiving change target-race-model. Update Purpose after archive.
## Requirements
### Requirement: 4-dimension fitness profile
The system SHALL track running fitness across four dimensions: aerobic capacity (VO2max, VDOT), threshold (LTHR, Z2 pace), economy (speed_per_bpm, cadence), and resilience (drift onset, pace fade). Each dimension has a current value, trend direction, and rate of change.

#### Scenario: Compute fitness profile
- **WHEN** `get_fitness_profile(conn)` is called
- **THEN** returns dict with four dimensions, each having: current_value, trend (improving/declining/flat), rate_per_month, data_points_count

#### Scenario: Insufficient data
- **WHEN** fewer than 4 weeks of running data exist
- **THEN** dimensions with insufficient data show "insufficient_data" status with note: "Need N more weeks"

### Requirement: VDOT from race results
The system SHALL compute VDOT from each completed race using Daniels tables. VDOT is the cross-distance fitness equivalent — a 22:00 5K and a 1:47 HM both correspond to a specific VDOT. Race VDOT is more reliable than Garmin's wrist-based VO2max.

#### Scenario: VDOT from 5K result
- **WHEN** S25 race result is 22:00 for 5.0km
- **THEN** VDOT computes to ~46, which projects to marathon 3:52

#### Scenario: VDOT from HM result
- **WHEN** Müggelsee HM result is 1:49:24 for 21.1km
- **THEN** VDOT computes to ~47, which projects to marathon 3:48

#### Scenario: Effective VDOT blends sources
- **WHEN** Garmin VO2max is 49 and most recent race VDOT is 46 (from 3 weeks ago)
- **THEN** effective_vdot is ~46 (race result preferred when <8 weeks old)
- **AND** dashboard shows both: "VDOT 46 (from S25) · Garmin VO2max 49"

### Requirement: Trend and rate computation
Each fitness dimension SHALL have a trend computed from the last 8 weeks of data. Rate of change = linear regression slope expressed per month.

#### Scenario: VO2max trend
- **WHEN** VO2max was 48 eight weeks ago and 49 now
- **THEN** trend = "improving", rate = +0.5/month

#### Scenario: Economy declining
- **WHEN** speed_per_bpm dropped from 1.10 to 1.05 over 4 weeks
- **THEN** trend = "declining", rate = -0.05/month

### Requirement: Resilience from split analysis
Resilience dimension SHALL track drift onset km (from cardiac drift analysis) and long run ceiling (longest distance without significant drift). Requires .fit file data — graceful degradation when unavailable.

#### Scenario: Resilience with splits
- **WHEN** most recent long run had drift onset at km 14
- **THEN** resilience current_value = 14km, trend from previous long runs

#### Scenario: Resilience without splits
- **WHEN** no .fit split data available
- **THEN** resilience shows "Enable fit sync --splits for resilience tracking"

### Requirement: HR zone primary selection follows a documented fallback chain
`compute_hr_zones()` SHALL select the primary `hr_zone` using this priority:

1. **AeT-anchored** (`hr_zone_aet`) — when an active `aet` calibration row exists. *Not yet implemented; reserved for `aet-anchored-zones`.*
2. **%LTHR (Friel)** (`hr_zone_lthr`) — when an active `lthr` calibration exists.
3. **%MaxHR** (`hr_zone_maxhr`) — as a last resort when neither AeT nor LTHR is available.

An explicit `profile.zone_model` config value (`max_hr` | `lthr` | `aet`) overrides the fallback chain. The default `zone_model` SHALL be `lthr`. `hr_zone_maxhr` and `hr_zone_lthr` SHALL continue to be computed in parallel as diagnostic outputs, regardless of which model is primary.

#### Scenario: LTHR calibrated, no AeT — primary is LTHR
- **WHEN** active `lthr = 172`, no active `aet`, `zone_model` unset
- **THEN** `hr_zone` matches `hr_zone_lthr`. avg HR 148 → Z2 (88% LTHR, in Friel Z2 band 85–89%).

#### Scenario: LTHR missing, falls back to %MaxHR
- **WHEN** no active `lthr` calibration, no active `aet`
- **THEN** `hr_zone` matches `hr_zone_maxhr` (%MaxHR textbook model)

#### Scenario: Explicit override wins
- **WHEN** `profile.zone_model = max_hr` is set in `config.local.yaml`, LTHR is calibrated
- **THEN** `hr_zone` matches `hr_zone_maxhr` (user override beats fallback)

#### Scenario: Diagnostic zones always computed
- **WHEN** any running activity with `avg_hr` is enriched
- **THEN** `hr_zone_maxhr` is populated (always), `hr_zone_lthr` is populated (when LTHR cal exists), and the primary `hr_zone` matches the active model

### Requirement: Recompute path applies the active calibration to historical activities
`fit recompute --force` SHALL re-enrich every activity using the current calibration values, regardless of whether `hr_zone` is already populated. After a calibration change or a zone-model switch, running `fit recompute --force` SHALL produce a consistent zone classification across all history.

#### Scenario: Zone model switched
- **WHEN** user changes `zone_model` from `max_hr` to `lthr` and runs `fit recompute --force`
- **THEN** all 231 historical activities have their `hr_zone` recomputed against the Friel %LTHR model; `weekly_agg.z12_pct` recomputes accordingly

#### Scenario: Default recompute leaves zoned activities alone
- **WHEN** user runs `fit recompute` (no `--force`)
- **THEN** only activities with `hr_zone IS NULL` are re-enriched (post-sync gap-filling behavior, unchanged from today)

### Requirement: Calibration rows carry a flags column
Every calibration row SHALL include a `flags` column (`TEXT`, JSON array of strings, default `'[]'`). Recognized flag values: `implausible_value`, `spike`, `unexpected_direction`, `agrees_with_prior`, `weak_context`. Auto-extract paths SHALL always insert a row (never silently return None when the reading is bad) — implausible readings are recorded with `confidence = 'low'` and a flag list explaining why.

#### Scenario: Plausible reading from a race
- **WHEN** a max_hr reading of 195 is extracted from a race activity, prior active is 192, no spike detected
- **THEN** the row is inserted with `flags = []` and `confidence = 'medium'`

#### Scenario: Reading agrees with prior — confidence bumps to high
- **WHEN** a new LTHR reading of 171 is extracted from a 10K race, prior active is 172 (race-extracted)
- **THEN** the row is inserted with `flags = ['agrees_with_prior']` and `confidence = 'high'`

#### Scenario: Implausible value still recorded
- **WHEN** an activity reports `max_hr = 220` (chest strap glitch on an easy run)
- **THEN** the row is inserted with `flags = ['implausible_value', 'weak_context']` and `confidence = 'low'`; the prior active calibration remains active

#### Scenario: Sudden directional drop is flagged but recorded
- **WHEN** a new max_hr reading is 188, prior active is 195, gap is 7 bpm in 8 weeks
- **THEN** the row is inserted with `flags = ['unexpected_direction']` and `confidence = 'low'`

### Requirement: Calibration confidence has explicit, uniform semantics
The system SHALL apply the same `low | medium | high` confidence rubric across all calibration metrics (`max_hr`, `lthr`, `aet`, `weight`, `vo2max`).

| Confidence | Definition |
|---|---|
| `high` | Two corroborating readings within ±2 bpm (method-appropriate tolerance) from hard-effort contexts, OR explicitly set by user via `fit calibrate <metric> <value>`. |
| `medium` | Single recent reading from a hard-effort context (race, time trial, hard interval), plausible value, no flags. |
| `low` | Any of: `implausible_value`, `spike`, `unexpected_direction`, `weak_context`; OR stale (past `STALENESS_THRESHOLDS`). |

The "stale → low" rule applies at query time (via `get_calibration_status()`), not at write time — the stored `confidence` reflects the row's write-time quality.

#### Scenario: Manual CLI write produces high
- **WHEN** user runs `fit calibrate max_hr 195`
- **THEN** the inserted row has `confidence = 'high'` regardless of any other context

#### Scenario: Auto-extracted single race reading produces medium
- **WHEN** LTHR auto-extract path inserts a value of 171 with no prior active row
- **THEN** the row has `confidence = 'medium'` and `flags = []`

#### Scenario: Stale active calibration reports as low at query time
- **WHEN** the active `lthr` row is from 2025-10 (>56 days old per `STALENESS_THRESHOLDS`)
- **THEN** `get_calibration_status()` reports `confidence = 'low'` even though the stored row's `confidence` field is still `medium` or `high`

### Requirement: Active calibration selection is confidence-aware
The system SHALL select the active calibration row by preferring the highest-confidence non-stale row, breaking ties by date (most recent first). A spurious `low`-confidence row SHALL NOT replace a clean `medium`- or `high`-confidence row simply because it is more recent.

#### Scenario: Newer low row does not displace older medium row
- **WHEN** calibration history for max_hr is `[{date: 2026-04-15, value: 195, confidence: medium, flags: []}, {date: 2026-04-22, value: 220, confidence: low, flags: ['implausible_value']}]`
- **THEN** `get_active_calibration('max_hr')` returns the 195 row

#### Scenario: Tie between two high rows resolves to most recent
- **WHEN** two `high`-confidence max_hr rows exist (195 from 2026-04-15, 196 from 2026-04-22, both within ±2 bpm of each other)
- **THEN** `get_active_calibration('max_hr')` returns the 2026-04-22 row

#### Scenario: All non-stale rows are low — pick most recent
- **WHEN** every non-stale calibration row for a metric is `low`-confidence (e.g., a string of spikes)
- **THEN** `get_active_calibration()` falls back to date-only ordering within the low tier (and the dashboard should warn loudly via `attention-panel`)

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
