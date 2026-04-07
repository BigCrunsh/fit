## ADDED Requirements

### Requirement: Target race as organizing anchor
The system SHALL identify a target race from `race_calendar` (next registered by date) and orient the entire dashboard around it. All objectives, phases, and predictions reference this race. `get_target_race(conn)` returns the anchor race.

#### Scenario: Target race identified
- **WHEN** race_calendar has a registered race on 2026-09-27 (Berlin Marathon)
- **THEN** `get_target_race()` returns that race with name, date, distance, target_time

#### Scenario: No registered races
- **WHEN** race_calendar has no registered races
- **THEN** dashboard falls back to showing objectives without a race anchor

### Requirement: Objectives linked to target race
Goals table SHALL have a `race_id` FK linking objectives to a specific race. `_goal_progress()` SHALL read ALL targets from the goals table (not hardcoded values). When the target race changes, some objectives carry over (weight, consistency), some are race-specific.

#### Scenario: Goal progress from DB
- **WHEN** goals table has VO2max target_value=51 and current VO2max is 49
- **THEN** `_goal_progress()` shows 49/51 (96%) — read from DB, not hardcoded

#### Scenario: Hardcoded values eliminated
- **WHEN** user changes VO2max target from 51 to 52 via `fit goal`
- **THEN** dashboard immediately reflects 49/52 without code changes

### Requirement: Race countdown headline
The dashboard headline SHALL be race-anchored: "{Race Name}: {days} days — Phase {N} of {total} — prediction: {time}". This replaces the current readiness-only headline as the primary display.

#### Scenario: Race countdown with phase
- **WHEN** Berlin Marathon is 174 days away and Phase 1 is active
- **THEN** headline shows "Berlin Marathon: 174 days — Phase 1 of 4 — prediction: 3:52"

#### Scenario: Taper phase headline
- **WHEN** race is 14 days away and taper phase is active
- **THEN** headline shows "Berlin Marathon: 14 days — Taper — trust your training"

### Requirement: Milestone and PB tracking
The system SHALL detect and celebrate: new longest run, new best efficiency, streak milestones (4, 8, 12 weeks), VO2max peaks. Displayed as celebration cards on Today tab.

#### Scenario: New longest run
- **WHEN** a run's distance exceeds all previous runs
- **THEN** Today tab shows "🎉 New longest run: 22.0km (prev: 21.2km)"

### Requirement: Schema migration via table rebuild
SQLite `ALTER TABLE ADD COLUMN` does not enforce FK constraints. Migration 007 SHALL use table rebuild (create new table, copy data, drop old, rename) for goals.race_id. Same approach for race_calendar.activity_id FK enforcement.

#### Scenario: FK enforced after rebuild
- **WHEN** goals.race_id references a non-existent race_calendar.id
- **THEN** SQLite raises a foreign key constraint error (with PRAGMA foreign_keys=ON)

### Requirement: Consolidated Phase 2a schema migration
Migration 007 SHALL consolidate ALL Phase 2a schema changes into ONE migration: goals.race_id, activities.srpe, weekly_agg.monotony, weekly_agg.strain, weekly_agg.cycling_km, weekly_agg.cycling_min. This avoids modifying the same table across multiple migrations.

#### Scenario: Single migration covers all changes
- **WHEN** migration 007 runs
- **THEN** goals, activities, and weekly_agg all have their new columns in one transaction

## Post-Phase 2 Additions

### Requirement: Race CRUD via CLI
The `fit races` command SHALL be a Click group with subcommands for full CRUD operations on the `race_calendar` table.

**`fit races add`** — interactive CLI prompting for: name, date, distance (with aliases: 5k, 10k, half, marathon mapped to km), status (planned/registered/completed/dns/dnf), target_time, and result_time (for completed races).

**`fit races update <id>`** — edit any field of an existing race by ID.

**`fit races delete <id>`** — delete a race with confirmation prompt. Unlinks associated goals (sets `goals.race_id = NULL`) and activities (sets `race_calendar.activity_id = NULL`) before deletion.

**`fit races list`** — shows all races with their IDs visible, enabling CRUD operations.

#### Scenario: Add a race interactively
- **WHEN** user runs `fit races add`
- **THEN** CLI prompts for name, date, distance (accepting "half" → 21.1km, "marathon" → 42.195km, "10k" → 10.0km, "5k" → 5.0km), status, target_time
- **AND** race is inserted into race_calendar

#### Scenario: Update a race
- **WHEN** user runs `fit races update 3` and changes target_time
- **THEN** race_calendar row 3 is updated with the new target_time

#### Scenario: Delete a race with linked goals
- **WHEN** user runs `fit races delete 2` and race 2 has goals linked via race_id
- **THEN** confirmation prompt shown, goals.race_id set to NULL, race deleted

#### Scenario: Race list shows IDs
- **WHEN** user runs `fit races list`
- **THEN** output table includes an ID column for each race

### Requirement: get_target_race() priority logic
`get_target_race(conn)` SHALL use the following priority to determine the anchor race: (1) race linked to an active goal via `goals.race_id`, (2) longest distance among upcoming registered races, (3) nearest upcoming registered race by date.

#### Scenario: Goal-linked race takes priority
- **WHEN** goal has race_id=2 (10K) and race_id=3 (marathon) is also registered
- **THEN** `get_target_race()` returns race 2 (goal-linked)

#### Scenario: No goal-linked race, longest distance wins
- **WHEN** no goals have race_id set, but two races are registered (10K on Jun 1, marathon on Sep 27)
- **THEN** `get_target_race()` returns the marathon (longest distance)

#### Scenario: Same distance, nearest wins
- **WHEN** two half marathons are registered (Jun 1 and Sep 27), no goal link
- **THEN** `get_target_race()` returns Jun 1 (nearest)
