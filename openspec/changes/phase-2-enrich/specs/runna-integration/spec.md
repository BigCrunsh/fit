## ADDED Requirements

### Requirement: Store Runna training plan
The system SHALL store the current Runna training plan in a `planned_workouts` table: date, workout_type (easy/long/tempo/intervals/rest), target_distance_km, target_zone, target_pace_range, notes. Plan data can be imported via manual CSV/JSON or a future Runna API.

#### Scenario: Import plan from CSV
- **WHEN** user runs `fit plan import <file.csv>`
- **THEN** planned workouts are loaded into the `planned_workouts` table

#### Scenario: View upcoming plan
- **WHEN** user runs `fit plan` or `fit status`
- **THEN** the next 7 days of planned workouts are displayed

### Requirement: Plan vs actual comparison per run
The system SHALL compare each actual activity to the planned workout for that date. Deviations are computed: distance delta, zone delta (planned Z2 but ran Z4), pace delta. Stored as fields on the activity or in a `plan_adherence` view.

#### Scenario: Planned easy, ran tempo
- **WHEN** Runna planned a Z2 easy 7km run and the actual run was Z4 at 12.5km
- **THEN** the plan adherence shows: "Zone: Z2→Z4 (deviated +2 zones), Distance: 7→12.5km (+79%)"

#### Scenario: Planned rest, actually ran
- **WHEN** Runna planned a rest day and the athlete ran
- **THEN** the adherence flags: "Rest day violation"

#### Scenario: Ran on plan
- **WHEN** actual run matches planned zone and distance within 10%
- **THEN** adherence shows: "On plan ✓"

### Requirement: Plan adherence in dashboard and coaching
The Training tab SHALL show plan adherence per run (on-plan / deviated with details). The coaching context SHALL include adherence summary so Claude can flag systematic deviations ("you've overridden 4 of 6 Runna easy runs with tempo efforts").

#### Scenario: Training tab shows adherence
- **WHEN** planned workouts and actual activities exist for the same dates
- **THEN** the run timeline visualization shows a plan indicator (green=on plan, red=deviated)

#### Scenario: Coaching context includes adherence
- **WHEN** Claude calls `get_coaching_context()`
- **THEN** the response includes plan adherence summary for the last 2 weeks
