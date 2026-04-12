# checkpoint-enrichment Specification

## Purpose
TBD - created by archiving change target-race-model. Update Purpose after archive.
## Requirements
### Requirement: Derived target times for checkpoint races
Each registered race before the target race SHALL have a derived_target_time computed via Riegel back-calculation: "to be on track for target_time at target_distance, you should run this distance in X." Computed at display time, not stored.

#### Scenario: 5K checkpoint for marathon target
- **WHEN** target is marathon sub-4:00 (14400s) and S25 5K is upcoming
- **THEN** derived_target_time = 14400 × (5.0/42.195)^(1/1.06) ≈ 22:30
- **AND** displayed as: "S25: your target 22:00 · on-track for marathon: 22:30"

#### Scenario: 10K checkpoint for HM target
- **WHEN** target is HM sub-1:47 (6420s) and Tierparklauf 10K is upcoming
- **THEN** derived_target_time = 6420 × (10.0/21.1)^(1/1.06) ≈ 44:15
- **AND** displayed as: "Tierparklauf: your target 45:00 · on-track for HM: 44:15"

### Requirement: Readiness signal from checkpoint result
When a checkpoint race is completed, the system SHALL show what the result means for the target race prediction.

#### Scenario: Checkpoint beats derived target
- **WHEN** S25 result is 21:45 (faster than derived 22:30)
- **THEN** show: "S25 result (21:45) → VDOT 47 → marathon projection improves to 3:48"

#### Scenario: Checkpoint misses derived target
- **WHEN** S25 result is 24:00 (slower than derived 22:30)
- **THEN** show: "S25 result (24:00) → VDOT 42 → marathon projection: 4:15. Consider adjusting target."

### Requirement: VDOT update from race result
Each completed race SHALL update the fitness profile's effective_vdot. More recent races weighted higher. Race VDOT preferred over Garmin VO2max when <8 weeks old.

#### Scenario: VDOT update after race
- **WHEN** S25 completed in 22:00
- **THEN** race VDOT = 46 stored with date
- **AND** effective_vdot recalculated (was 49 from Garmin, now blended toward 46)
- **AND** all target race projections update automatically

### Requirement: Checkpoint display on dashboard
Upcoming checkpoint races SHALL show on the Today tab with: race name, days remaining, user target time, derived target time (from target race), and gap between them.

#### Scenario: Checkpoint card
- **WHEN** S25 is 12 days away with user target 22:00 and derived target 22:30
- **THEN** Today tab shows: "S25 in 12d · target: 22:00 · marathon readiness: 22:30 · you're aiming faster than needed ✓"

