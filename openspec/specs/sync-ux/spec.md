## ADDED Requirements

### Requirement: Sync pipeline decomposition
`run_sync()` SHALL be decomposed into composable pipeline stages: fetch, enrich, store, weather, aggregate, correlate, alert, plan_sync. Each stage is independently testable. New stages (Phase 2b .fit downloads, Phase 2c plan sync) plug in without increasing blast radius of existing stages.

#### Scenario: Single stage failure
- **WHEN** weather fetch fails
- **THEN** other stages complete normally, weather failure logged as warning

### Requirement: Weather API retry
`weather.py` SHALL use a shared `_request_with_retry` wrapper (same pattern as garmin.py) for Open-Meteo API calls. Handles transient errors, rate limits.

#### Scenario: Transient 503 from Open-Meteo
- **WHEN** first request returns 503
- **THEN** retry with exponential backoff, succeed on retry 2

### Requirement: End-to-end integration test
A test SHALL verify the full pipeline: sync with race-anchored goals → produces correct dashboard narratives. Tests the chain: sync layer → model layer → narrative layer → dashboard output.

#### Scenario: Integration test
- **WHEN** test runs sync with mock Garmin data + race_calendar + goals
- **THEN** generated dashboard HTML contains race countdown, objective progress, trend narrative

### Requirement: Generator refactor
`generator.py` (860+ lines) SHALL be refactored into a `fit/report/sections/` package: engine.py (core generator), cards.py (status cards, milestone cards), charts.py (chart generation), predictions.py (race prediction section). Each module independently testable.

#### Scenario: Modular generation
- **WHEN** dashboard is generated
- **THEN** each section is produced by its own module, main generator orchestrates

### Requirement: sRPE pipeline stage
The sync pipeline SHALL include an `enrich_srpe` stage that retroactively joins unmatched checkin RPE to same-day activities (assigning to highest training_load if multiple). This stage also triggers from `fit checkin` after saving, ensuring sRPE is computed regardless of whether sync or checkin happens first.

#### Scenario: sRPE computed during sync
- **WHEN** sync finds an activity on a day with a checkin that has RPE=7
- **THEN** sRPE computed and stored on the activity

#### Scenario: sRPE computed during checkin
- **WHEN** user runs `fit checkin` with RPE=6 and there's already a synced run today
- **THEN** sRPE computed immediately after checkin save

### Requirement: Bug fixes
- ACWR year-boundary: ISO week 53 handling (prev_week += 52 wrong for 53-week years). Use `datetime.date.fromisocalendar()` for correct week arithmetic.
- Alert SQL: `all_runs_too_hard` query `WHERE >= MAX()` returns only 1 week. Fix to actually average 2 weeks.
- SpO2 threshold: change from <93% to <95% for sea-level. Make configurable via config.yaml.

#### Scenario: Week 53 ACWR
- **WHEN** current week is 2027-W01 and computing ACWR with 4 prior weeks
- **THEN** correctly references 2026-W52, 2026-W51, 2026-W50, 2026-W49 (not 2026-W00)

## Post-Phase 2 Additions

### Requirement: Doctor expects 17 tables
`fit doctor` SHALL check for 17 tables (was 14): the original 14 plus `race_calendar`, `activity_splits`, and `planned_workouts`. Schema version check SHALL expect 9 migrations.

#### Scenario: All 17 tables present
- **WHEN** `fit doctor` runs after all migrations applied
- **THEN** table check passes with 17/17 tables found

#### Scenario: Missing new tables
- **WHEN** `fit doctor` runs and activity_splits table is missing
- **THEN** output shows: "Missing tables: activity_splits. Run migrations to fix."

### Requirement: Sync pipeline surfaces warnings to console
The sync pipeline SHALL surface warnings directly to console output (stdout/stderr), not just to the log file. Users running `fit sync` interactively should see warnings about missing config, failed API calls, stale data, and body comp source availability without needing to check sync.log.

#### Scenario: Weather API failure shown on console
- **WHEN** Open-Meteo API fails during sync
- **THEN** console shows: "Warning: Weather fetch failed (will retry next sync)" in addition to logging

#### Scenario: Body comp warning on console
- **WHEN** no body comp source is configured
- **THEN** console shows the body comp source warning (not just logged silently)
