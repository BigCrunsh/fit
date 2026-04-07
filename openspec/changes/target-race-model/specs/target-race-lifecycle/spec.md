## ADDED Requirements

### Requirement: Target race flag on race_calendar
The system SHALL support marking exactly one race in `race_calendar` as the target via `is_target = 1`. All other races have `is_target = 0`. `get_target_race()` reads this flag directly.

#### Scenario: Set target race
- **WHEN** user runs `fit target set 36` (Berlin Marathon)
- **THEN** `race_calendar` row 36 has `is_target = 1`, all others have `is_target = 0`

#### Scenario: Exactly-one constraint
- **WHEN** user runs `fit target set 35` (Müggelsee HM) while Berlin Marathon is target
- **THEN** Berlin Marathon `is_target` becomes 0, Müggelsee HM becomes 1

#### Scenario: Clear target
- **WHEN** user runs `fit target clear`
- **THEN** all `is_target = 0`, dashboard falls back to nearest future registered race

### Requirement: CLI commands for target management
The system SHALL provide `fit target set <race_id>`, `fit target show`, `fit target objectives`, and `fit target clear`.

#### Scenario: fit target show
- **WHEN** Berlin Marathon is target with target_time 4:00:00
- **THEN** output shows race name, date, distance, target time, days remaining, and derived objectives

#### Scenario: fit target set triggers objective derivation
- **WHEN** user runs `fit target set 36`
- **THEN** objectives auto-derive (VO2max, volume, consistency, Z2 targets) and display in summary

### Requirement: Migration 010 adds is_target and objective metadata
Migration SHALL add `is_target` to race_calendar and `derivation_source`, `auto_value`, `is_override` to goals. Backfill sets current target from existing goal FK linkage. Existing goals marked as `derivation_source = 'manual'`.

#### Scenario: Migration preserves existing state
- **WHEN** migration 010 runs with goals linked to race_id 36
- **THEN** race_calendar row 36 gets `is_target = 1`, existing goals keep their values with `derivation_source = 'manual'`

### Requirement: Waypoint race display
Non-target registered races SHALL appear as compact waypoint pills on Today tab and as milestone markers on the journey timeline, but NOT in the Objectives section.

#### Scenario: Waypoints after target set
- **WHEN** Berlin Marathon is target and S25, Tierparklauf, Müggelsee are registered
- **THEN** S25/Tierparklauf/Müggelsee appear as waypoint pills with days countdown, not as objective cards
