# fitness-profile Specification

## Purpose
TBD - created by archiving change target-race-model. Update Purpose after archive.
## Requirements
### Requirement: 4-dimension fitness profile
The system SHALL track running fitness across four dimensions: aerobic capacity (VO2max, VDOT), threshold (LTHR, Z2 pace), economy (speed_per_bpm, cadence), and resilience (drift onset, pace fade). Each dimension has a current value, trend direction, and rate of change.

#### Scenario: Compute fitness profile
- **WHEN** `get_fitness_profile(conn)` is called
- **THEN** returns dict with four dimensions, each having: current_value, trend (improving/declining/flat), rate_per_month, data_points_count

#### Scenario: Insufficient data
- **WHEN** fewer than 4 weeks of running data exist
- **THEN** dimensions with insufficient data show "insufficient_data" status with note: "Need N more weeks"

### Requirement: VDOT from race results
The system SHALL compute VDOT from each completed race using Daniels tables. VDOT is the cross-distance fitness equivalent — a 22:00 5K and a 1:47 HM both correspond to a specific VDOT. Race VDOT is more reliable than Garmin's wrist-based VO2max.

#### Scenario: VDOT from 5K result
- **WHEN** S25 race result is 22:00 for 5.0km
- **THEN** VDOT computes to ~46, which projects to marathon 3:52

#### Scenario: VDOT from HM result
- **WHEN** Müggelsee HM result is 1:49:24 for 21.1km
- **THEN** VDOT computes to ~47, which projects to marathon 3:48

#### Scenario: Effective VDOT blends sources
- **WHEN** Garmin VO2max is 49 and most recent race VDOT is 46 (from 3 weeks ago)
- **THEN** effective_vdot is ~46 (race result preferred when <8 weeks old)
- **AND** dashboard shows both: "VDOT 46 (from S25) · Garmin VO2max 49"

### Requirement: Trend and rate computation
Each fitness dimension SHALL have a trend computed from the last 8 weeks of data. Rate of change = linear regression slope expressed per month.

#### Scenario: VO2max trend
- **WHEN** VO2max was 48 eight weeks ago and 49 now
- **THEN** trend = "improving", rate = +0.5/month

#### Scenario: Economy declining
- **WHEN** speed_per_bpm dropped from 1.10 to 1.05 over 4 weeks
- **THEN** trend = "declining", rate = -0.05/month

### Requirement: Resilience from split analysis
Resilience dimension SHALL track drift onset km (from cardiac drift analysis) and long run ceiling (longest distance without significant drift). Requires .fit file data — graceful degradation when unavailable.

#### Scenario: Resilience with splits
- **WHEN** most recent long run had drift onset at km 14
- **THEN** resilience current_value = 14km, trend from previous long runs

#### Scenario: Resilience without splits
- **WHEN** no .fit split data available
- **THEN** resilience shows "Enable fit sync --splits for resilience tracking"

