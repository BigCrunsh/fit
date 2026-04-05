## ADDED Requirements

### Requirement: Interactive daily check-in CLI
`fit checkin` SHALL present an interactive terminal prompt collecting: hydration (Low / OK / Good), alcohol (drink count + optional detail text), leg freshness (Heavy / OK / Fresh), eating quality (Poor / OK / Good), water intake (liters), energy level (Low / Normal / Good), sleep quality (Poor / OK / Good — subjective, complements Garmin sleep data), RPE (Rate of Perceived Exertion, 1-10, optional — how hard did today's workout feel), optional weight (kg), and free-text notes. The CLI SHALL use Rich for formatted terminal output.

#### Scenario: Complete check-in with all fields
- **WHEN** user runs `fit checkin` and provides values for all fields
- **THEN** a row is inserted into the `checkins` table with the current date and all provided values, and a confirmation is displayed

#### Scenario: Check-in with skipped optional fields
- **WHEN** user runs `fit checkin` and presses enter to skip weight and notes
- **THEN** the row is inserted with `NULL` for skipped fields

#### Scenario: Weight provided in check-in
- **WHEN** user enters a weight value during `fit checkin`
- **THEN** the weight is stored in both `checkins` (as context) and `body_comp` (as a measurement with `source = 'checkin'`)

### Requirement: Check-in uses single-key input for categorical fields
Categorical fields (hydration, legs, eating, energy) SHALL accept single-key input: first letter of the option (e.g., `g` for Good, `h` for Heavy, `l` for Low). The CLI SHALL display the key mapping inline (e.g., `[L]ow / [O]K / [G]ood`).

#### Scenario: Single-key input for hydration
- **WHEN** the CLI prompts for hydration and user presses `g`
- **THEN** hydration is recorded as `"Good"`

#### Scenario: Single-key input for legs
- **WHEN** the CLI prompts for legs and user presses `f`
- **THEN** legs is recorded as `"Fresh"`

### Requirement: Check-in prevents duplicate entries per date
The system SHALL prevent multiple check-ins for the same date. If a check-in already exists for today, the CLI SHALL display the existing data and ask whether to overwrite.

#### Scenario: First check-in of the day
- **WHEN** user runs `fit checkin` and no check-in exists for today
- **THEN** the check-in is saved normally

#### Scenario: Duplicate check-in same day
- **WHEN** user runs `fit checkin` and a check-in already exists for today
- **THEN** the CLI shows the existing check-in values and prompts "Overwrite? [y/N]"

### Requirement: RPE captures perceived workout effort
The RPE field SHALL accept an integer 1-10 or be skipped (enter = skip, stored as NULL). If an activity exists for today, the CLI SHALL show the activity name and HR to help calibrate the RPE rating. The RPE value is stored in `checkins.rpe` and also written to the most recent activity's `activities.rpe` if one exists for today.

#### Scenario: RPE entered with activity today
- **WHEN** user enters RPE 7 and a running activity exists for today
- **THEN** `checkins.rpe = 7` AND `activities.rpe = 7` for today's activity

#### Scenario: RPE entered without activity today
- **WHEN** user enters RPE 3 and no activity exists for today (rest day)
- **THEN** `checkins.rpe = 3` (general day effort), no activity update

#### Scenario: RPE skipped
- **WHEN** user presses enter to skip RPE
- **THEN** `checkins.rpe` is NULL

### Requirement: Alcohol detail captures free text
The alcohol field SHALL capture both a numeric count and an optional free-text detail (e.g., "2 beers", "1 glass wine"). The count goes to `checkins.alcohol` and the detail to `checkins.alcohol_detail`.

#### Scenario: Alcohol with detail
- **WHEN** user enters `2 beers` for alcohol
- **THEN** `alcohol = 2.0` and `alcohol_detail = "2 beers"`

#### Scenario: Zero alcohol
- **WHEN** user enters `0` for alcohol
- **THEN** `alcohol = 0` and `alcohol_detail` is NULL

### Requirement: Backfill migration for historical check-ins
Migration `004_backfill_checkins.py` SHALL insert historical check-in data captured from Claude Chat sessions. The migration contains a hardcoded list of 5 historical check-ins with dates, hydration, alcohol, legs, eating, water, energy, and notes.

#### Scenario: Historical check-ins are backfilled
- **WHEN** migration 004 runs
- **THEN** 5 historical check-in rows are inserted into the `checkins` table

#### Scenario: Backfill is idempotent
- **WHEN** migration 004 runs twice
- **THEN** no duplicate rows are created (uses INSERT OR IGNORE on date primary key)
