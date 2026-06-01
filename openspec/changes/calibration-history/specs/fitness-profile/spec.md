## ADDED Requirements

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
