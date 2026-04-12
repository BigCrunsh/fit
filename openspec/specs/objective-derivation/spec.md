# objective-derivation Specification

## Purpose
TBD - created by archiving change target-race-model. Update Purpose after archive.
## Requirements
### Requirement: Auto-derive objectives from target race
When a target race is set, the system SHALL auto-derive training objectives based on target_time, distance, and current fitness using Daniels VDOT tables and training science heuristics.

#### Scenario: Marathon sub-4:00 objectives
- **WHEN** target is Marathon (42.195km) with target_time 4:00:00
- **THEN** derived objectives: VO2max ≥ 50 (Daniels inverse), peak volume 50-60km/wk, long run 30-32km, consistency 12 weeks, Z2 ≥ 80%

#### Scenario: Half marathon sub-1:47 objectives
- **WHEN** target is Half Marathon (21.1km) with target_time 1:47:00
- **THEN** derived objectives: VO2max ≥ 52 (Daniels inverse for HM pace), peak volume 40-50km/wk, long run 18-21km, consistency 8 weeks, Z2 ≥ 80%

#### Scenario: 10K sub-45:00 objectives
- **WHEN** target is 10K (10.0km) with target_time 0:45:00
- **THEN** derived objectives: VO2max ≥ 48, peak volume 30-40km/wk, long run 12-15km, consistency 6 weeks

### Requirement: User override support
Users SHALL be able to override any auto-derived objective value. Overrides persist when the target race changes. The auto-derived value is always stored alongside the override for comparison.

#### Scenario: Override weight target
- **WHEN** system derives "Weight: no auto-target" and user sets weight target to 75kg
- **THEN** goal has `target_value = 75`, `derivation_source = 'manual'`, `is_override = 0` (manual goals aren't overrides, they're user-created)

#### Scenario: Override VO2max target
- **WHEN** system derives VO2max ≥ 50 and user changes to 52
- **THEN** goal has `target_value = 52`, `auto_value = 50`, `is_override = 1`

#### Scenario: Target change preserves overrides
- **WHEN** target changes from Marathon sub-4 to HM sub-1:47
- **THEN** VO2max auto_value recalculates to 52, but user's `target_value = 52` is preserved (already matches). Consistency auto-recalculates from 12 to 8 weeks (not overridden, so target_value also updates).

### Requirement: Daniels inverse VDOT lookup
The system SHALL compute the minimum VO2max needed for a given target time and distance by inverting the Daniels VDOT table. Uses the same `_VDOT_TABLE` already in analysis.py.

#### Scenario: Inverse lookup
- **WHEN** target is marathon 4:00:00 (14400s)
- **THEN** inverse lookup finds VO2max ≈ 50 (closest entry where marathon_seconds ≤ 14400)

### Requirement: Objective display shows derivation source
The dashboard objectives section SHALL indicate whether each objective is auto-derived or user-set. Auto-derived objectives show the source (e.g., "from Daniels table for sub-4:00").

#### Scenario: Mixed objectives display
- **WHEN** objectives include auto-derived VO2max and manual weight
- **THEN** VO2max shows "auto · Daniels sub-4:00" label, weight shows "manual" label

