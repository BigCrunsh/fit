# target-race-lifecycle Specification

## Purpose
TBD - created by archiving change target-race-model. Update Purpose after archive.
## Requirements
### Requirement: Target race via goals.race_id
The system SHALL identify the target race via the `race_id` FK on active goals (existing mechanism, no schema change). `fit objective set <race_id>` updates all active goals' race_id and triggers objective re-derivation. The DB table stays `goals`; the user-facing command and noun are "objective".

#### Scenario: Set target race
- **WHEN** user runs `fit objective set 36` (Berlin Marathon)
- **THEN** all active goals get `race_id = 36`, objectives re-derive from marathon requirements

#### Scenario: Switch target
- **WHEN** user runs `fit objective set 35` (Müggelsee HM) while Berlin Marathon was target
- **THEN** all active goals get `race_id = 35`, auto-derived objectives recalculate for HM
- **AND** user-override objectives preserve their target_value

#### Scenario: Clear target
- **WHEN** user runs `fit objective clear`
- **THEN** all active goals get `race_id = NULL`
- **AND** dashboard falls back to nearest future registered race

#### Scenario: Deprecated `fit target` alias still works
- **WHEN** user runs `fit target set 36` (the former command name)
- **THEN** it behaves identically to `fit objective set 36` and prints a one-line deprecation notice pointing at `fit objective`

### Requirement: CLI commands for target management
The CLI SHALL provide three objective-management commands (the group is `fit objective`; `fit target` remains a hidden, deprecated alias group that forwards to it for one release):
- `fit objective set <race_id>` — set target, derive objectives, show fitness profile summary
- `fit objective show` — display target + fitness profile (4 dimensions) + objectives with gap/achievability
- `fit objective clear` — remove target

#### Scenario: fit objective show
- **WHEN** Berlin Marathon is target with 173 days remaining
- **THEN** output shows: race info, fitness profile (VDOT, economy, threshold, resilience), objectives with achievability (✓/⚠/✗), upcoming checkpoints with derived targets

#### Scenario: Deprecated alias hidden from help
- **WHEN** user runs `fit --help`
- **THEN** `objective` is listed and `target` is NOT (the alias is hidden), but `fit target …` still runs with a deprecation notice

### Requirement: Waypoint race display
Non-target registered races SHALL appear as checkpoint waypoints on the Today tab with derived target times from the target race. They MUST NOT be treated as dashboard objectives.

#### Scenario: Checkpoint waypoint
- **WHEN** S25 is 12 days away and target is Berlin Marathon sub-4:00
- **THEN** Today tab shows: "S25 in 12d · target: 22:00 · marathon readiness: 22:30"

