# data-ingestion — delta for wellness-early-warning

## ADDED Requirements

### Requirement: Sleep respiration capture
The system SHALL store the nightly sleep respiration average in a new `daily_health.avg_sleep_respiration` REAL column (migration 019, additive). During health sync, the system SHALL parse `avgSleepRespirationValue` from the Garmin respiration endpoint payload already fetched for the waking average (no additional API calls). The upsert SHALL preserve a previously stored value when a later fetch returns NULL for the field (COALESCE semantics, matching `avg_spo2`). The existing `avg_respiration` (waking average) column and its parsing SHALL remain unchanged.

#### Scenario: Sleep respiration parsed and stored
- **WHEN** the respiration payload contains `avgWakingRespirationValue: 15.0` and `avgSleepRespirationValue: 16.0`
- **THEN** the day's row stores `avg_respiration = 15.0` and `avg_sleep_respiration = 16.0`

#### Scenario: Missing sleep field leaves column NULL
- **WHEN** the respiration payload contains only `avgWakingRespirationValue`
- **THEN** `avg_sleep_respiration` is NULL for that day and no error is raised

#### Scenario: Re-sync with partial payload preserves stored value
- **WHEN** a day already has `avg_sleep_respiration = 16.0` and a re-sync fetch returns NULL for the field
- **THEN** the stored 16.0 is preserved

#### Scenario: Migration is additive
- **WHEN** migration 019 runs on an existing database
- **THEN** existing `daily_health` rows are unchanged with `avg_sleep_respiration` NULL
