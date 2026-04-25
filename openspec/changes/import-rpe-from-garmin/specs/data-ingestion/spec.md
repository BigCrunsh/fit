## ADDED Requirements

### Requirement: Garmin activity detail provides per-activity RPE, feel, and compliance
The system SHALL fetch each running activity's detail (`api.get_activity(id)`) during sync and extract three values from `summaryDTO`: `directWorkoutRpe` (10/20/.../100), `directWorkoutFeel` (0/25/50/75/100), and `directWorkoutComplianceScore` (0-100). These SHALL be mapped to per-activity columns: `activities.rpe = directWorkoutRpe / 10` (1-10, NULL if Garmin field absent or NULL), `activities.feel = directWorkoutFeel / 25 + 1` (1-5, NULL passthrough), `activities.compliance_score = directWorkoutComplianceScore` (0-100, NULL passthrough).

#### Scenario: All three fields present in Garmin
- **WHEN** a running activity has `directWorkoutRpe = 30`, `directWorkoutFeel = 50`, `directWorkoutComplianceScore = 100` in `summaryDTO`
- **THEN** the activity row stores `rpe = 3`, `feel = 3`, `compliance_score = 100`

#### Scenario: Garmin has no RPE for the activity
- **WHEN** `summaryDTO` has no `directWorkoutRpe` key (or value is NULL)
- **THEN** `activities.rpe` is NOT modified during sync (NULL stays NULL, existing values are preserved)

#### Scenario: Non-running activities skip detail fetch
- **WHEN** an activity has `type = 'cycling'`
- **THEN** the system does NOT call `get_activity` for it and does NOT touch its rpe/feel/compliance fields

### Requirement: Sync refresh policy for RPE updates
The system SHALL refresh RPE/feel/compliance from Garmin for running activities ≤14 days old on every sync (catches user edits in Garmin Connect), and SHALL only fill NULL values for activities >14 days old (avoids unnecessary detail calls for stable historical data).

#### Scenario: Recent activity is re-fetched even if RPE already set
- **WHEN** a running activity is 5 days old, `activities.rpe = 5`, and `directWorkoutRpe` in Garmin is now `70`
- **THEN** sync updates `activities.rpe = 7` (refreshed)

#### Scenario: Old activity with non-NULL RPE is not re-fetched
- **WHEN** a running activity is 90 days old and `activities.rpe = 5`
- **THEN** sync does NOT call `get_activity` for it

#### Scenario: Old activity with NULL RPE is fetched
- **WHEN** a running activity is 90 days old and `activities.rpe IS NULL`
- **THEN** sync calls `get_activity` and fills any non-NULL Garmin values

### Requirement: fit backfill rpe command populates historical RPE/feel/compliance
The system SHALL provide `fit backfill rpe` that walks all running activities lacking RPE/feel/compliance and calls `api.get_activity(id)` for each, displaying a progress bar. The command SHALL respect the existing rate-limit retry logic (`_request_with_retry` handles 429 with 60s backoff). Re-running the command SHALL be idempotent (no double-fetches for fields already populated unless `--refresh` is passed).

#### Scenario: Backfill walks all unpopulated running activities
- **WHEN** the user runs `fit backfill rpe` and 600 running activities have NULL `rpe`/`feel`/`compliance_score`
- **THEN** the system fetches detail for each, populates available fields, and reports progress

#### Scenario: Backfill is idempotent
- **WHEN** the user runs `fit backfill rpe` twice in a row
- **THEN** the second invocation skips activities whose fields are already populated and exits quickly

#### Scenario: Backfill --refresh forces re-fetch
- **WHEN** the user runs `fit backfill rpe --refresh`
- **THEN** the system re-fetches detail for all running activities regardless of current values

## MODIFIED Requirements

### Requirement: Derived metrics are computed on insert
The system SHALL compute derived metrics for each activity via `lib/analysis.py` at insert time: `hr_zone` (Z1-Z5), `effort_class` (Recovery / Easy / Moderate / Hard / Very Hard — 5 levels matching 5 zones), `run_type` (auto-classified), and two aerobic efficiency values. `speed_per_bpm` is computed as `(distance_km * 1000 / duration_min) / avg_hr` — meters per minute per heartbeat (higher = more efficient, intuitive direction). `speed_per_bpm_z2` is the same but only for runs with avg HR in the Z2 range for pure aerobic trending. Non-running activities get NULL for efficiency fields. Additionally, sRPE (`rpe × duration_min`) is computed per running activity from `activities.rpe` directly (no longer joined from `checkins.rpe`). When `activities.rpe IS NULL`, sRPE is NULL.

#### Scenario: Running activity — speed_per_bpm always computed
- **WHEN** a running activity has `avg_hr = 165`, `distance_km = 10.0`, `duration_min = 52`
- **THEN** `speed_per_bpm` is `(10000/52) / 165 ≈ 1.17 m/min/bpm` (higher = better)

#### Scenario: Running activity — Z2 efficiency for easy runs
- **WHEN** a running activity has `avg_hr = 128` (within Z2: 115-134), `distance_km = 7.0`, `duration_min = 45`
- **THEN** `speed_per_bpm_z2` is `(7000/45) / 128 ≈ 1.22 m/min/bpm` (Z2-filtered for trending)

#### Scenario: Running activity — Z2 efficiency NULL for hard runs
- **WHEN** a running activity has `avg_hr = 165` (outside Z2 range)
- **THEN** `speed_per_bpm_z2` is NULL, but `speed_per_bpm` is still computed

#### Scenario: sRPE computed from activity-level RPE
- **WHEN** a running activity has `rpe = 7` and `duration_min = 50`
- **THEN** `srpe = 350.0` (computed at insert from the activity row, not from `checkins`)

#### Scenario: sRPE NULL when activity RPE missing
- **WHEN** a running activity has `rpe IS NULL`
- **THEN** `srpe` is NULL
