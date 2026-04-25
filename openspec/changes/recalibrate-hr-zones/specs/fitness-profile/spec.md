## ADDED Requirements

### Requirement: Calibration rows record value, confidence, and flags
The system SHALL store every calibration reading in the `calibration` table with a `flags TEXT` column (JSON array of tag strings) describing why the row received its confidence level. Implausible, anomalous, or weak-context readings SHALL be recorded (not rejected) so they appear in calibration history; their confidence SHALL be `low` and the flag list SHALL explain why. Recognized flags: `implausible_value`, `spike`, `unexpected_direction`, `agrees_with_prior`, `weak_context`.

#### Scenario: Plausible reading from a hard effort
- **WHEN** a max_hr reading of 195 is extracted from a race activity, prior active is 192, no spike detected
- **THEN** the row is inserted with `flags = []` and `confidence = 'medium'`

#### Scenario: Reading agrees with prior — confidence bumps to high
- **WHEN** a new LTHR reading of 171 is extracted, prior active is 172 (race-extracted, within ±2)
- **THEN** the row is inserted with `flags = ['agrees_with_prior']` and `confidence = 'high'`

#### Scenario: Implausible value still recorded
- **WHEN** an activity reports `max_hr = 220` (chest strap glitch on an easy run)
- **THEN** the row is inserted with `flags = ['implausible_value', 'spike', 'weak_context']` and `confidence = 'low'`; the prior active calibration remains active

#### Scenario: Sudden directional drop is flagged but recorded
- **WHEN** a new max_hr reading is 188, prior active is 195, gap is 7 bpm in 8 weeks
- **THEN** the row is inserted with `flags = ['unexpected_direction']` and `confidence = 'low'`

### Requirement: Calibration confidence has explicit, uniform semantics
The system SHALL apply the same `low | medium | high` confidence rubric across all calibration metrics (`max_hr`, `lthr`, `aet`, `weight`, `vo2max`).

| Confidence | Definition |
|---|---|
| `high` | Two corroborating readings within ±2 bpm (or method-appropriate tolerance) from hard-effort contexts, OR explicitly set by user via `fit calibrate <metric> <value>`. |
| `medium` | Single recent reading from a hard-effort context (race, time trial, hard interval), plausible value, no flags. |
| `low` | Any of: `implausible_value`, `spike`, `unexpected_direction`, `weak_context`, or stale (past `STALENESS_THRESHOLDS`). |

#### Scenario: Manual CLI write produces high confidence
- **WHEN** the user runs `fit calibrate max_hr 195`
- **THEN** the inserted row has `confidence = 'high'` (manual override always high)

#### Scenario: Auto-extracted single race reading produces medium
- **WHEN** the LTHR auto-extract path inserts a value of 171 with no prior active row
- **THEN** the row has `confidence = 'medium'` and `flags = []`

#### Scenario: Stale active calibration drops to low
- **WHEN** the active `lthr` row is from 2025-10 (>56 days old per `STALENESS_THRESHOLDS`)
- **THEN** `get_calibration_status()` reports the metric as `confidence = 'low'` and surfaces a retest prompt

### Requirement: Active calibration selection is confidence-aware
The system SHALL select the active calibration row by preferring the highest-confidence non-stale row, breaking ties by date (most recent first). A spurious low-confidence row SHALL NOT replace a clean medium- or high-confidence row simply because it is more recent.

#### Scenario: Newer low row does not displace older medium row
- **WHEN** calibration history for max_hr is `[{date: 2026-04-15, value: 195, confidence: medium, flags: []}, {date: 2026-04-22, value: 220, confidence: low, flags: ['implausible_value','spike']}]`
- **THEN** `get_active_calibration('max_hr')` returns the 195 row

#### Scenario: Tie between two high rows resolves to most recent
- **WHEN** two `high`-confidence max_hr rows exist (195 from 2026-04-15, 196 from 2026-04-22)
- **THEN** `get_active_calibration('max_hr')` returns the 2026-04-22 row

### Requirement: max_hr calibration auto-refreshes from observed activity max
The system SHALL scan running activities during sync and insert a new `max_hr` calibration row when `max(activities.max_hr)` exceeds the active calibration value by more than 1 bpm, OR when a sustained drop is observed (newer reading lower than active by >2 bpm — flagged as `unexpected_direction`). Method SHALL be `race_extract` if the source activity is a race, else `activity_max`. Confidence SHALL be derived from the rubric (Requirement: Calibration confidence has explicit, uniform semantics).

#### Scenario: New max from race auto-bumps calibration
- **WHEN** active max_hr is 192, a race activity records `max_hr = 195`
- **THEN** sync inserts a new calibration row `{value: 195, method: 'race_extract', confidence: 'medium', flags: []}` and the active calibration becomes 195

#### Scenario: Below-active activity max does not refresh
- **WHEN** active max_hr is 195 and a steady run records `max_hr = 188`
- **THEN** sync does NOT insert a calibration row (within 1 bpm tolerance window for noise; no new high)

### Requirement: AeT calibration metric anchors the primary HR zone model
The system SHALL track an `aet` (aerobic threshold) calibration metric in the `calibration` table alongside `max_hr` and `lthr`. AeT SHALL be sourced empirically from HR-drift testing on steady-pace long runs (drift <5% over the run = pace below AeT, 5–7% = at AeT, >7% = above AeT). The primary `hr_zone` classification SHALL anchor Z2 ceiling at the active AeT value rather than at a fixed `% MaxHR` or `% LTHR` boundary. `hr_zone_maxhr` and `hr_zone_lthr` remain available as diagnostic outputs for the dashboard's model-comparison view.

#### Scenario: AeT-anchored Z2 classification
- **WHEN** active `aet` calibration is 142 bpm and a running activity has `avg_hr = 140`
- **THEN** `hr_zone` is `Z2` (under AeT)

#### Scenario: AeT-anchored Z3 classification
- **WHEN** active `aet` calibration is 142 bpm and a running activity has `avg_hr = 148`
- **THEN** `hr_zone` is `Z3` (above AeT, below LTHR)

#### Scenario: AeT-anchored Z4 classification at LTHR
- **WHEN** active `aet` calibration is 142 bpm, active `lthr` is 172 bpm, and a running activity has `avg_hr = 173`
- **THEN** `hr_zone` is `Z4` (at/above LTHR)

#### Scenario: Diagnostic zones still computed
- **WHEN** any running activity is enriched
- **THEN** `hr_zone_maxhr` and `hr_zone_lthr` are populated alongside the AeT-anchored `hr_zone` so the dashboard can show all three for comparison

#### Scenario: AeT calibration absent — fall back to %MaxHR
- **WHEN** no active `aet` calibration row exists
- **THEN** `hr_zone` falls back to the %MaxHR model (current default behaviour) and the dashboard surfaces a "calibrate AeT" prompt

### Requirement: AeT auto-derives from steady-pace long runs
The system SHALL detect candidate runs for AeT estimation during sync (running activities ≥12km with per-km splits whose pace standard deviation falls below a "steady" threshold). For each candidate, the system SHALL compute first-half vs second-half avg HR (distance-weighted) to produce a drift percentage and either a direct AeT estimate (drift 5–7%) or a one-sided bound (drift <5% lower bound, drift >7% upper bound). The system SHALL bisect across recent candidates within an active window (e.g., 8 weeks) to maintain an active AeT calibration. Each derivation SHALL produce a calibration row with `method='drift_test'` and confidence per the uniform rubric.

#### Scenario: Steady long run with mid drift — direct estimate
- **WHEN** a 15km running activity has steady splits, first-half avg HR 138, second-half avg HR 144 (drift 4.3%)
- **THEN** the system records a calibration row `{metric: 'aet', value: > avg_hr_of_run, method: 'drift_test', flags: ['lower_bound']}` (TBD whether bound rows have a distinct flag)

#### Scenario: Two corroborating drift-test estimates within window
- **WHEN** two AeT direct estimates within the 8-week window land at 142 and 144 (within ±3 bpm tolerance)
- **THEN** the active aet calibration becomes their consolidated estimate with `confidence = 'high'`

#### Scenario: Single steady run — single estimate
- **WHEN** one steady-run drift estimate of 142 exists, no prior calibrations
- **THEN** the active aet calibration is 142 with `confidence = 'medium'`

#### Scenario: Run is not steady — no candidate
- **WHEN** a 15km activity has pace stdev > steady threshold (intervals or fartlek)
- **THEN** no AeT calibration row is produced; the activity is not a candidate

### Requirement: Calibration history is visualized per metric
The dashboard SHALL render a calibration history view per metric showing all recorded calibration rows over time. The view SHALL distinguish rows by confidence (high=solid dot, medium=hollow, low=red ring), surface flags on hover/tooltip, and annotate the staleness threshold band so the active row turns red when it crosses. A `fit calibrate history <metric>` CLI counterpart SHALL print a sparkline plus a tabular history.

#### Scenario: Two LTHR readings render with high confidence
- **WHEN** the LTHR history contains two race-extracted readings (172 in 2025-10, 171 in 2026-04, both `agrees_with_prior` after the second)
- **THEN** the chart shows two dots; the second is solid (high), tooltip shows method=`race_extract` and source activity name

#### Scenario: Implausible spike renders with red ring
- **WHEN** max_hr history contains a `low`-confidence row with flags `['implausible_value', 'spike']`
- **THEN** the chart shows that point with a red ring; tooltip lists the flags so the anomaly is visible without driving the active line

#### Scenario: Active row crosses staleness threshold
- **WHEN** the active LTHR row is older than `STALENESS_THRESHOLDS['lthr']` (56 days)
- **THEN** the chart band turns red and the dashboard shows the retest prompt

## MODIFIED Requirements

### Requirement: 4-dimension fitness profile
The system SHALL track running fitness across four dimensions: aerobic capacity (VO2max, VDOT), threshold (LTHR, AeT, Z2 pace), economy (speed_per_bpm, cadence), and resilience (drift onset, pace fade). Each dimension has a current value, trend direction, and rate of change. The threshold dimension SHALL surface AeT and LTHR as distinct values, with a sanity check warning when AeT > 90% × LTHR (indicates stale AeT relative to threshold gains).

#### Scenario: Compute fitness profile
- **WHEN** `get_fitness_profile(conn)` is called
- **THEN** returns dict with four dimensions, each having: current_value, trend (improving/declining/flat), rate_per_month, data_points_count

#### Scenario: Threshold dimension exposes AeT and LTHR independently
- **WHEN** active calibrations are `aet = 142` and `lthr = 172`
- **THEN** the threshold dimension reports both values; `aet/lthr` ratio is 0.826 (within typical 0.75–0.85 range, no warning)

#### Scenario: AeT staleness warning
- **WHEN** active `aet = 162` and active `lthr = 172` (ratio 0.94)
- **THEN** the threshold dimension flags AeT as likely stale and recommends a new drift test

#### Scenario: Insufficient data
- **WHEN** fewer than 4 weeks of running data exist
- **THEN** dimensions with insufficient data show "insufficient_data" status with note: "Need N more weeks"
