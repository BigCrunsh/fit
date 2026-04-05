## ADDED Requirements

### Requirement: SQLite schema defines all fitness data tables
The system SHALL create and maintain a SQLite database at the path specified in config (`sync.db_path`, default `~/.fit/fitness.db`). The schema SHALL define 10 tables (`activities`, `daily_health`, `checkins`, `body_comp`, `weather`, `goals`, `training_phases`, `goal_log`, `calibration`, `weekly_agg`) and 2 views (`v_run_days`, `v_all_training`) as specified in `migrations/001_schema.sql`.

#### Scenario: Fresh database initialization
- **WHEN** `fit sync` runs and no database file exists
- **THEN** the system creates the database and applies all migrations in order (001, 002, 003, 004)

#### Scenario: Existing database with pending migrations
- **WHEN** `fit sync` runs and the database exists but new migrations are available
- **THEN** the system applies only the pending migrations without affecting existing data

### Requirement: Three-layer config system
The system SHALL load configuration in three layers with later layers overriding earlier ones: `config.yaml` (committed template with `${VAR}` placeholders) → `config.local.yaml` (gitignored personal values) → environment variables (`FIT_*` prefix). A `get_config()` helper in `lib/config.py` SHALL merge all three layers and return the resolved config.

#### Scenario: Config loading with all layers present
- **WHEN** `config.yaml` has `profile.name: "${FIT_USER_NAME}"`, `config.local.yaml` has `profile.name: "Christoph"`, and `FIT_USER_NAME` env var is not set
- **THEN** `get_config()` returns `profile.name` as `"Christoph"` (local overrides template)

#### Scenario: Environment variable overrides local config
- **WHEN** `config.local.yaml` has `profile.name: "Christoph"` and `FIT_USER_NAME=Other` is set
- **THEN** `get_config()` returns `profile.name` as `"Other"` (env overrides local)

#### Scenario: Template placeholder without override
- **WHEN** `config.yaml` has `profile.name: "${FIT_USER_NAME}"` and neither `config.local.yaml` nor env var provides a value
- **THEN** `get_config()` raises an error indicating the required config value is missing

### Requirement: Garmin Connect sync pulls health metrics and activities
The system SHALL connect to Garmin Connect via the `garminconnect` library using auth tokens from the configured `garmin_token_dir`. `fit sync` SHALL pull daily health metrics into `daily_health` and activities into `activities` for the configured date range (default: last 7 days, configurable via `--days` flag, or full history via `--full`).

#### Scenario: Default sync pulls last 7 days
- **WHEN** user runs `fit sync` without flags
- **THEN** the system syncs health metrics and activities for the last 7 days and reports counts per data type

#### Scenario: Full sync pulls all available history
- **WHEN** user runs `fit sync --full`
- **THEN** the system syncs all available health metrics and activities from Garmin Connect

#### Scenario: Sync is idempotent via proper upsert
- **WHEN** `fit sync` runs twice for the same date range
- **THEN** existing records are updated via `INSERT ... ON CONFLICT DO UPDATE SET` (not `INSERT OR REPLACE`, which would delete derived metrics). Only raw Garmin fields are updated; derived fields are preserved.

#### Scenario: Garmin auth tokens are missing or expired
- **WHEN** the configured `garmin_token_dir` has no valid tokens
- **THEN** the system reports a clear error message with instructions to authenticate

### Requirement: Activities include all types with Move IQ support
The system SHALL sync all activity types from Garmin (running, cycling, swimming, hiking, walking, etc.), not just running. Activities auto-detected by Garmin Move IQ SHALL be stored with `subtype = 'auto_detected'`. Manually started activities SHALL have `subtype = 'manual'`.

#### Scenario: Move IQ cycling activity is synced
- **WHEN** Garmin has an auto-detected cycling activity
- **THEN** the activity is stored with `type = 'cycling'` and `subtype = 'auto_detected'`

#### Scenario: Manual running activity is synced
- **WHEN** Garmin has a user-started running activity
- **THEN** the activity is stored with `type = 'running'` and `subtype = 'manual'`

### Requirement: SpO2 data is synced into daily health
The system SHALL pull nightly SpO2 readings from Garmin via `api.get_spo2_data(date)` and store the average in `daily_health.avg_spo2`.

#### Scenario: SpO2 data available for a date
- **WHEN** the Garmin device has Pulse Ox enabled and recorded data for a given date
- **THEN** `daily_health.avg_spo2` is populated with the average SpO2 value

#### Scenario: SpO2 data not available
- **WHEN** the Garmin device has Pulse Ox disabled or no data exists
- **THEN** `daily_health.avg_spo2` remains NULL for that date (no error)

### Requirement: HR zones computed in parallel from both max HR and LTHR models
The system SHALL compute zones from BOTH models on every activity: (1) **hr_zone_maxhr**: standard 5-zone model (Z1 <60%, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 90-100% of max HR) — always computed since max HR is required. (2) **hr_zone_lthr**: Friel model (Z1 <85%, Z2 85-89%, Z3 90-94%, Z4 95-99%, Z5 100%+ of LTHR) — computed when a valid LTHR calibration exists, NULL otherwise. The `hr_zone` field is an alias for the preferred model per config (`profile.zone_model`), used as the default in queries and dashboard display. Effort class uses 5 levels matching 5 zones: Recovery (Z1), Easy (Z2), Moderate (Z3), Hard (Z4), Very Hard (Z5), derived from the primary `hr_zone`.

#### Scenario: Both models computed when LTHR is calibrated
- **WHEN** max HR is 192, LTHR is 172, and an activity has `avg_hr = 155`
- **THEN** `hr_zone_maxhr` is `"Z4"` (155/192 = 81%), `hr_zone_lthr` is `"Z3"` (155/172 = 90%), `hr_zone` follows preferred model

#### Scenario: Only max HR model when no LTHR calibration
- **WHEN** max HR is 192 and no LTHR calibration exists
- **THEN** `hr_zone_maxhr` is computed, `hr_zone_lthr` is NULL, `hr_zone` = `hr_zone_maxhr`

#### Scenario: Z5 classified as Very Hard
- **WHEN** an activity has `avg_hr = 180` in Z5 territory
- **THEN** `effort_class` is `"Very Hard"` (Z4 and Z5 are distinct training stimuli)

#### Scenario: Z1 classified as Recovery
- **WHEN** an activity has `avg_hr = 110` in Z1 territory
- **THEN** `effort_class` is `"Recovery"` (Z1 and Z2 are distinct)

### Requirement: Zone classification is frozen at insert time with max_hr_used
Each activity SHALL store `max_hr_used` and `lthr_used` (the calibration values at insert time) for backward compatibility. This enables backward compatibility: if max HR is updated (e.g., from 192 to 188 after a year of aging or re-testing), historical activities keep their original zone classification. Only new activities use the new max HR. A `fit recompute-zones` command MAY be added later for intentional re-classification, but `fit sync` SHALL NOT recompute zones for existing activities on upsert.

#### Scenario: Zone computed with current max HR
- **WHEN** a new activity is inserted and config has `profile.max_hr = 192`
- **THEN** `max_hr_used = 192` is stored on the activity alongside the computed `hr_zone`

#### Scenario: Max HR changes, historical zones preserved
- **WHEN** config `profile.max_hr` changes from 192 to 188 and `fit sync` runs for overlapping dates
- **THEN** existing activities retain their original `hr_zone` and `max_hr_used = 192`; only truly new activities get zones computed with `max_hr_used = 188`

#### Scenario: Upsert preserves existing derived metrics
- **WHEN** `fit sync` upserts an activity that already exists in the DB
- **THEN** raw Garmin fields (HR, pace, distance) are updated, but `hr_zone`, `effort_class`, `speed_per_bpm`, `speed_per_bpm_z2`, `max_hr_used`, `lthr_used`, and `run_type` are preserved from the original insert

### Requirement: Derived metrics are computed on insert
The system SHALL compute derived metrics for each activity via `lib/analysis.py` at insert time: `hr_zone` (Z1-Z5), `effort_class` (Recovery / Easy / Moderate / Hard / Very Hard — 5 levels matching 5 zones), `run_type` (auto-classified), and two aerobic efficiency values. `speed_per_bpm` is computed as `(distance_km * 1000 / duration_min) / avg_hr` — meters per minute per heartbeat (higher = more efficient, intuitive direction). `speed_per_bpm_z2` is the same but only for runs with avg HR in the Z2 range for pure aerobic trending. Non-running activities get NULL for efficiency fields.

#### Scenario: Running activity — speed_per_bpm always computed
- **WHEN** a running activity has `avg_hr = 165`, `distance_km = 10.0`, `duration_min = 52`
- **THEN** `speed_per_bpm` is `(10000/52) / 165 ≈ 1.17 m/min/bpm` (higher = better)

#### Scenario: Running activity — Z2 efficiency for easy runs
- **WHEN** a running activity has `avg_hr = 128` (within Z2: 115-134), `distance_km = 7.0`, `duration_min = 45`
- **THEN** `speed_per_bpm_z2` is `(7000/45) / 128 ≈ 1.22 m/min/bpm` (Z2-filtered for trending)

#### Scenario: Running activity — Z2 efficiency NULL for hard runs
- **WHEN** a running activity has `avg_hr = 165` (outside Z2 range)
- **THEN** `speed_per_bpm_z2` is NULL, but `speed_per_bpm` is still computed

### Requirement: Run type auto-classification
The system SHALL auto-classify running activities into run types based on distance, pace, HR zone, and activity name patterns. Classification logic: `race` (name contains "race"/"HM"/"marathon"/"10k" or subtype indicates race), `long` (distance >= 75% of recent longest run or >= 15km), `intervals` (name contains "interval"/"fartlek" or high HR variance), `tempo` (Z3-Z4 dominant, sustained effort), `recovery` (Z1 dominant, short distance), `progression` (name contains "progressive"/"prog" or negative split pattern), `easy` (default for Z2 dominant runs). Run type MAY be overridden manually via MCP or Claude.

#### Scenario: Long run classification
- **WHEN** a running activity is 18km and the recent weekly longest run average is 12km
- **THEN** `run_type` is `"long"`

#### Scenario: Race classification from name
- **WHEN** a running activity name is "Half Marathon" or "Berlin HM"
- **THEN** `run_type` is `"race"`

#### Scenario: Easy run as default
- **WHEN** a running activity is Z2 dominant, 7km, no special name pattern
- **THEN** `run_type` is `"easy"`

#### Scenario: Tempo classification
- **WHEN** a running activity is Z3-Z4, sustained pace, name contains "Tempo"
- **THEN** `run_type` is `"tempo"`

### Requirement: Weather enrichment at daily and per-activity level
The system SHALL fetch daily weather from Open-Meteo (free, no API key) and store it in the `weather` table. Additionally, for each activity with a known start time and location, the system SHALL fetch hourly weather at the activity start hour and store `temp_at_start_c` and `humidity_at_start_pct` directly on the activity row. This enables per-activity weather context for cardiac drift analysis (e.g., morning long run at 8C vs afternoon run at 22C).

#### Scenario: Daily weather fetched for a run date
- **WHEN** `fit sync` processes a running activity on 2026-04-01 in Berlin
- **THEN** the `weather` table has a row for 2026-04-01 with temp, humidity, wind, precipitation, and conditions

#### Scenario: Per-activity hourly weather
- **WHEN** an activity has a start time of 07:30 and location (lat, lon)
- **THEN** `temp_at_start_c` and `humidity_at_start_pct` on the activity row are populated from Open-Meteo hourly data for that hour and location

#### Scenario: Activity without start time or location
- **WHEN** an activity has no start time or location (e.g., Move IQ auto-detected)
- **THEN** `temp_at_start_c` and `humidity_at_start_pct` remain NULL (daily weather table still populated)

#### Scenario: Weather already exists for date
- **WHEN** weather data already exists for a date
- **THEN** the existing record is preserved (no re-fetch unless `--full`)

### Requirement: Weekly aggregation is recomputed after sync
The system SHALL recompute `weekly_agg` rows for all weeks affected by the sync date range. Aggregation includes:
- **Running:** run count, total km, avg pace, avg HR, longest single run distance, avg cadence, easy run count, quality session count (tempo + intervals + race)
- **Cross-training:** non-running activity count and total duration (cycling, swimming, hiking, etc.)
- **Combined:** total training load (all types), total activities, training days count, **ACWR** (this week's load / avg of previous 4 weeks — safe range 0.8-1.3, danger above 1.5)
- **Recovery:** avg readiness, avg sleep, avg RHR, avg HRV, avg weight
- **Zone distribution by TIME:** minutes in Z1-Z5 (using duration_min per activity), plus z12_pct (Z1+Z2 time / total time) and z45_pct (Z4+Z5 time / total time) — compared to phase-specific targets, not blanket 80/20
- **Consistency:** consecutive weeks with 3+ runs (streak counter, reset on miss)

#### Scenario: Weekly aggregation after sync
- **WHEN** `fit sync` completes for dates in weeks W13 and W14
- **THEN** `weekly_agg` rows for `"2026-W13"` and `"2026-W14"` are recomputed with all fields

#### Scenario: Zone distribution computed by time
- **WHEN** week W13 has: a 60min Z2 run, a 45min Z3 run, and a 30min Z4 interval session
- **THEN** z2_min=60, z3_min=45, z4_min=30, z12_pct=44.4% (60/135), z45_pct=22.2% (30/135)

#### Scenario: Cross-training included in weekly totals
- **WHEN** week W13 has 2 runs and 3 auto-detected cycling activities (Move IQ)
- **THEN** run_count=2, cross_train_count=3, total_activities=5, total_load sums all 5

#### Scenario: Longest run tracked per week
- **WHEN** week W13 has runs of 7km, 10km, and 21km
- **THEN** longest_run_km=21.0

#### Scenario: ACWR computed from rolling 4-week load
- **WHEN** week W14 has total_load 250, and weeks W10-W13 have loads [100, 150, 200, 180] (avg 157.5)
- **THEN** acwr = 250 / 157.5 ≈ 1.59 (danger zone — spike warning)

#### Scenario: ACWR safe after gradual ramp
- **WHEN** week W14 has total_load 200, and weeks W10-W13 have loads [150, 160, 170, 180] (avg 165)
- **THEN** acwr = 200 / 165 ≈ 1.21 (safe range)

#### Scenario: ACWR with no prior weeks
- **WHEN** week W14 is the first week with data (no previous 4 weeks)
- **THEN** acwr is NULL (insufficient history)

#### Scenario: Consistency streak tracking
- **WHEN** weeks W10, W11, W12, W13 all have 3+ runs, and W14 has only 2
- **THEN** W13 consecutive_weeks_3plus=4, W14 consecutive_weeks_3plus=0

### Requirement: Backfill migration from legacy garmy database
Migration `002_backfill_garmy.py` SHALL read from `~/.garmy/health.db` and import: `daily_health_metrics` → `daily_health`, `run_activities` (running + cycling) → `activities`. Derived metrics SHALL be computed for all imported activities.

#### Scenario: Garmy backfill imports health and activities
- **WHEN** migration 002 runs and `~/.garmy/health.db` exists
- **THEN** all daily health metrics and activities are imported with derived metrics computed

#### Scenario: Garmy database does not exist
- **WHEN** migration 002 runs and `~/.garmy/health.db` does not exist
- **THEN** the migration completes with a warning (not an error), importing nothing

### Requirement: Backfill migration from Apple Health weight CSV
Migration `003_backfill_weight.py` SHALL read a weight CSV export from Apple Health (path configurable, default `~/Downloads/apple_health_weight.csv`) and import into the `body_comp` table with `source = 'fitdays'`.

#### Scenario: Weight CSV backfill
- **WHEN** migration 003 runs and the CSV file exists
- **THEN** weight data is imported into `body_comp` with dates and weights

#### Scenario: Weight CSV not found
- **WHEN** migration 003 runs and the CSV file does not exist
- **THEN** the migration completes with a warning, importing nothing

### Requirement: Training phases track planned vs actual over time
The `training_phases` table SHALL track phased milestones for each goal. Each phase has: a name (e.g., "Base Building"), date range, JSON targets (z2_pct, weekly_km_range, max_long_run_km, vo2max, weight_kg), JSON actuals (updated when phase ends), and a status (planned / active / completed / revised). Phases are never deleted — when a plan changes, the phase status is set to `revised` and a new phase is created, preserving the history of what was planned vs what happened.

#### Scenario: Create training phases for marathon goal
- **WHEN** a marathon goal exists and training phases are defined
- **THEN** phases are stored with comprehensive targets, e.g., Phase 1: `{"z12_pct_target": 90, "z45_pct_target": 0, "weekly_km_range": [25,30], "max_long_run_km": 12, "run_frequency": [3,4], "quality_sessions_per_week": 0, "rest_days_min": 2, "cross_train_min_per_week": 60, "acwr_range": [0.8, 1.2], "max_weekly_increase_pct": 10}`

#### Scenario: Phase completed with actuals
- **WHEN** Phase 1 ends and actual metrics are computed from weekly_agg
- **THEN** `actuals` is updated with real values (e.g., `{"z2_pct": 72, "weekly_km_avg": 22}`) and status is set to `completed`

#### Scenario: Phase revised mid-cycle
- **WHEN** Phase 2 targets are adjusted (e.g., weekly km target reduced due to injury)
- **THEN** the original Phase 2 is set to `status = 'revised'`, a new Phase 2 row is created with updated targets, and a `goal_log` entry records the change with `previous_value` and `new_value`

### Requirement: Goal log tracks all changes and milestones
The `goal_log` table SHALL be an append-only log of goal-related events: goal creation, goal updates, phase transitions (started, completed, revised), milestones achieved, and setbacks. Each entry has a date, type, description, and optional JSON for previous/new values. This creates a full narrative of the training journey over time.

#### Scenario: Goal created
- **WHEN** a Berlin Marathon goal is created
- **THEN** a `goal_log` entry is inserted with `type = 'goal_created'` and description "Berlin Marathon 2026: sub-4:00, Sep 27"

#### Scenario: Phase transition logged
- **WHEN** Phase 1 is marked as completed and Phase 2 becomes active
- **THEN** two `goal_log` entries: one `phase_completed` with actuals summary, one `phase_started` with Phase 2 targets

#### Scenario: Goal update logged with diff
- **WHEN** the marathon target pace changes from 5:41/km to 5:50/km
- **THEN** a `goal_log` entry with `type = 'goal_updated'`, `previous_value = {"target_pace": 341}`, `new_value = {"target_pace": 350}`, and a description explaining why

### Requirement: Calibration tracking with staleness warnings and active test prompts
The `calibration` table SHALL track the current and historical values of key physiological metrics: max_hr, lthr, weight, vo2max. Each calibration entry records: metric, value, method (lab_test / time_trial / race_extract / garmin_estimate / manual / scale), confidence (high / medium / low), date, optional source activity ID, and notes. Only the most recent calibration per metric is `active = 1`.

The system SHALL detect stale calibrations and prompt for active retesting:
- **Max HR**: stale if > 12 months old. Prompt: "Max HR was last validated 14 months ago. Consider verifying during your next race or hard interval session."
- **LTHR**: stale if > 8 weeks old. Prompt: "LTHR was last calibrated 10 weeks ago. Schedule a 30-minute time trial this week, or we can auto-extract from your next 10k+ race."
- **Weight**: stale if > 7 days since last measurement.
- **VO2max**: informational only (Garmin updates passively).

#### Scenario: LTHR auto-extracted from race
- **WHEN** `fit sync` imports a race activity (run_type = 'race', distance >= 10km)
- **THEN** the system computes candidate LTHR as avg HR of the second half of the race, creates a calibration entry with `method = 'race_extract'`, `confidence = 'medium'`, and prompts: "New LTHR estimate from your race: 170 bpm (current: 172). Accept? [y/N]"

#### Scenario: LTHR from time trial
- **WHEN** user runs `fit calibrate lthr` or logs a time trial via checkin
- **THEN** the system prompts for the 30-min TT result, computes LTHR as avg HR of last 20 min, creates a calibration entry with `method = 'time_trial'`, `confidence = 'high'`

#### Scenario: Stale LTHR warning in fit status
- **WHEN** `fit status` runs and LTHR calibration is > 8 weeks old
- **THEN** the output includes: "⚠️ LTHR: 172 bpm (calibrated Mar 1, 5 weeks ago) — schedule a 30-min time trial or run a 10k+ race for recalibration"

#### Scenario: Stale max HR warning in fit status
- **WHEN** `fit status` runs and max HR calibration is > 12 months old
- **THEN** the output includes: "⚠️ Max HR: 192 (last validated Oct 2025) — verify during your next hard race effort"

#### Scenario: Active test prompt at phase transition
- **WHEN** a training phase transitions (Phase 1 → Phase 2)
- **THEN** the system prompts: "New phase starting. Recommend calibration check: LTHR time trial (last done X weeks ago), weight check, max HR review."

### Requirement: Data source health check on init and in dashboard
The system SHALL check the availability and freshness of all data sources during `fit sync` and display a **data source health panel** in the dashboard and `fit status`. For each source, show: status (active / stale / missing / not enabled), last data date, and action needed.

Data sources to check:
- **Garmin health metrics**: active if data within last 3 days
- **Garmin activities**: active if synced within last 7 days
- **SpO2**: check if `daily_health.avg_spo2` has non-NULL values in last 7 days. If all NULL: "SpO2 not detected — enable Pulse Ox on your Garmin (Settings → Health & Wellness → Pulse Oximeter → During Sleep)"
- **LTHR detection**: check if Garmin has ever provided a lactate threshold estimate. If not: "Garmin LTHR detection may not be enabled — check Settings → Physiological Metrics → Lactate Threshold"
- **HRV Status**: check if `daily_health.hrv_status` has values. If NULL: "HRV Status may not be enabled — check Settings → Health & Wellness → HRV Status (needs 3 weeks to establish baseline)"
- **Training Readiness**: check if `daily_health.training_readiness` has values
- **Move IQ**: check if any activities have `subtype = 'auto_detected'`
- **Weight**: last measurement date from body_comp
- **Check-ins**: days since last check-in
- **Calibration**: staleness per metric (max_hr, lthr, weight)

#### Scenario: SpO2 not enabled
- **WHEN** the last 14 days of daily_health all have `avg_spo2 = NULL`
- **THEN** the data health panel shows: "SpO2: Not detected. Enable Pulse Ox on Garmin → Settings → Health & Wellness → Pulse Oximeter → During Sleep"

#### Scenario: All sources healthy
- **WHEN** all data sources have recent data and calibrations are current
- **THEN** the data health panel shows all green checkmarks

#### Scenario: Stale check-in
- **WHEN** the last check-in was 5 days ago
- **THEN** the data health panel shows: "Check-ins: Stale (last: 5 days ago). Run `fit checkin` daily for best coaching insights."

### Requirement: fit status shows quick overview with calibration, data health, and active phase
`fit status` SHALL display: total counts per table, last sync timestamp, **calibration status** (max_hr, lthr, weight with staleness warnings and retest prompts), **data source health** (active/stale/missing per source with Garmin setting instructions), active goals with targets, current training phase (name, targets, multi-dimensional compliance), ACWR safety, and consistency streak.

#### Scenario: Status with data and active phase
- **WHEN** user runs `fit status` and the database has data with an active training phase
- **THEN** the system displays counts, calibration status (with warnings if stale), data source health, goals, current phase, ACWR, and streak

#### Scenario: Status with empty database
- **WHEN** user runs `fit status` and the database is empty
- **THEN** the system displays zero counts and suggests running `fit sync`
