## MODIFIED Requirements

### Requirement: Target race via goals.race_id
The system SHALL identify the target race via the `race_id` FK on active goals (existing mechanism, no schema change). `fit target set <race_id>` updates all active goals' race_id and triggers objective re-derivation.

#### Scenario: Set target race
- **WHEN** user runs `fit target set 36` (Berlin Marathon)
- **THEN** all active goals get `race_id = 36`, objectives re-derive from marathon requirements

#### Scenario: Switch target
- **WHEN** user runs `fit target set 35` (Müggelsee HM) while Berlin Marathon was target
- **THEN** all active goals get `race_id = 35`, auto-derived objectives recalculate for HM
- **AND** user-override objectives preserve their target_value

#### Scenario: Clear target
- **WHEN** user runs `fit target clear`
- **THEN** all active goals get `race_id = NULL`
- **AND** dashboard falls back to nearest future registered race

### Requirement: CLI commands for target management
- `fit target set <race_id>` — set target, derive objectives, show fitness profile summary
- `fit target show` — display target + fitness profile (4 dimensions) + objectives with gap/achievability
- `fit target clear` — remove target

#### Scenario: fit target show
- **WHEN** Berlin Marathon is target with 173 days remaining
- **THEN** output shows: race info, fitness profile (VDOT, economy, threshold, resilience), objectives with achievability (✓/⚠/✗), upcoming checkpoints with derived targets

### Requirement: Waypoint race display
Non-target registered races appear as checkpoint waypoints on the Today tab with derived target times from the target race. They are NOT dashboard objectives.

#### Scenario: Checkpoint waypoint
- **WHEN** S25 is 12 days away and target is Berlin Marathon sub-4:00
- **THEN** Today tab shows: "S25 in 12d · target: 22:00 · marathon readiness: 22:30"
