## ADDED Requirements

### Requirement: Store Runna training plan with versioning
The system SHALL store the current Runna training plan in a `planned_workouts` table: date, workout_type (easy/long/tempo/intervals/rest), target_distance_km, target_zone, target_pace_range, **structure** (JSON for multi-segment workouts: "4x1km at 5:00/km with 90s recovery"), plan_week, plan_phase, plan_version, imported_at, notes. Old plan versions are marked **superseded** (not deleted) to preserve history.

Unique constraint on **(date, plan_version)**.

#### Scenario: Import plan from CSV
- **WHEN** user runs `fit plan import <file.csv>`
- **THEN** planned workouts are loaded with a new plan_version, existing future dates from older versions marked superseded

#### Scenario: Plan CSV includes phase info
- **WHEN** CSV has columns: date, workout_type, target_distance_km, target_zone, plan_week, plan_phase, structure, notes
- **THEN** all fields are stored, enabling the system to distinguish base-building easy weeks from taper easy weeks

#### Scenario: Plan version history preserved
- **WHEN** a new plan CSV is imported for dates that already have a planned workout
- **THEN** old plan rows are marked `superseded`, new rows created with incremented plan_version

### Requirement: Plan validation before import
`fit plan validate <file>` SHALL dry-run the import: check for malformed rows, duplicate dates, missing required fields, unknown workout_type values. Report all errors before importing.

#### Scenario: Validation catches errors
- **WHEN** CSV has a row with unknown workout_type "speedwork"
- **THEN** validate reports: "Row 5: unknown workout_type 'speedwork' (expected: easy/long/tempo/intervals/rest)"

#### Scenario: Clean file passes validation
- **WHEN** CSV has no errors
- **THEN** validate reports: "OK: 28 workouts, 4 weeks, ready to import"

### Requirement: Plan vs actual comparison with weekly compliance score
The system SHALL compute per-run adherence (distance delta, zone delta, pace delta) and a **weekly plan compliance score** (0-100%): runs completed as prescribed / total planned runs × 100, weighted by deviation severity.

Detect **systematic intensity override**: when >60% of easy/recovery runs in a 3-week window were executed at Z3+, generate a specific alert.

Track **rest day compliance**: planned rest days vs actual rest days per week.

#### Scenario: Weekly compliance score
- **WHEN** week has 5 planned workouts, 3 executed on-plan, 1 deviated (wrong zone), 1 missed
- **THEN** compliance score = 60% (3/5 on-plan)

#### Scenario: Systematic intensity override detected
- **WHEN** 4 of 5 planned Z2 runs in the last 3 weeks were executed at Z3+
- **THEN** alert: "Systematic intensity override: 80% of easy runs executed too hard in 3 weeks"

#### Scenario: Rest day violation tracking
- **WHEN** 2 of 3 planned rest days in a week had activities
- **THEN** rest day compliance = 33% for the week

### Requirement: Plan adherence in dashboard and coaching
Training tab: overlay **plan indicators on run timeline** (green border=on-plan, red=deviated). Add **sparkline adherence row** (28 dots for 4 weeks: hollow=rest, green=on-plan, red=deviated, gray=unplanned).

Coaching context: include weekly compliance score, rest day compliance, and systematic override detection.

#### Scenario: Sparkline adherence view
- **WHEN** 4 weeks of plan + actual data exist
- **THEN** a compact row of 28 dots shows at-a-glance plan adherence above the run timeline

#### Scenario: Coaching context includes adherence
- **WHEN** Claude calls `get_coaching_context()`
- **THEN** response includes: "Plan compliance: 45% (last 2 weeks). 80% of easy runs overridden."
