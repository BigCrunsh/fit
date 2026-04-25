## ADDED Requirements

### Requirement: Interactive daily check-in CLI
The system SHALL provide a `fit checkin` CLI command that interactively prompts for daily wellness inputs and stores them via INSERT ON CONFLICT into the `checkins` table. Inputs SHALL be split across three moments: morning (sleep quality, legs, energy), post-run (session notes only), and evening (hydration, eating, alcohol, alcohol detail, water). RPE is NOT prompted in any check-in moment — it is sourced per-activity from Garmin during sync.

#### Scenario: Morning check-in collects readiness fields
- **WHEN** user runs `fit checkin morning`
- **THEN** the system prompts for sleep quality, legs, energy, and notes; saves to `checkins` row for today

#### Scenario: Post-run check-in collects session notes only
- **WHEN** user runs `fit checkin run` after a running activity
- **THEN** the system displays the activity's name, distance, HR zone, and aerobic TE for context, then prompts for session notes only (no RPE prompt)

#### Scenario: Evening check-in collects recovery fields
- **WHEN** user runs `fit checkin evening`
- **THEN** the system prompts for hydration, eating, alcohol (with optional detail), and water liters; saves to `checkins` row for today

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
