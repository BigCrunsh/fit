## MODIFIED Requirements

### Requirement: Auto-sync planned workouts from Garmin Calendar
The system SHALL sync planned workouts by fetching Garmin Calendar items via `/calendar-service/year/{y}/month/{m}`. Filter for workout-type items. Parse Runna naming convention ("W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)") to extract: week number, day (Mo/Di/Mi/Do/Fr/Sa/So), workout type (Dauerlauf/Tempo/Intervalle/Langer Lauf), target distance. Fetch structured segments via `get_workout_by_id()` for warmup/intervals/cooldown detail. The manual trigger is `fit plan sync-calendar` (named for what it does — pull Runna workouts from the Garmin Calendar, not re-sync activities); `fit plan sync` remains a hidden, deprecated alias that forwards to it for one release.

Garmin Calendar API is undocumented — implement as "best effort." CSV fallback (task 6.5) SHALL be equally robust, not an afterthought.

#### Scenario: Runna workout synced
- **WHEN** `fit sync` runs and Garmin Calendar has "W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)" on 2026-04-15
- **THEN** planned_workouts row: date=2026-04-15, workout_type=intervals, target_distance_km=7.5, plan_week=2, plan_day=Mi

#### Scenario: Garmin API unavailable
- **WHEN** Garmin Calendar returns an error
- **THEN** plan sync skipped with warning, existing planned_workouts preserved

#### Scenario: Deprecated `fit plan sync` alias still works
- **WHEN** user runs `fit plan sync` (the former subcommand name)
- **THEN** it behaves identically to `fit plan sync-calendar` and prints a one-line deprecation notice
