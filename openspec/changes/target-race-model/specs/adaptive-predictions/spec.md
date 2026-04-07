## MODIFIED Requirements

### Requirement: Prediction charts adapt to target distance
The Prediction Trend chart and Race Prediction table SHALL extrapolate to the target race distance (from `race_calendar WHERE is_target = 1`), not hardcoded 42.195km. Riegel formula uses target_km. VDOT scales from marathon equivalent.

#### Scenario: Marathon target
- **WHEN** target is Marathon (42.195km)
- **THEN** prediction trend shows marathon times, table shows "Marathon Target: 4:00:00"

#### Scenario: Half marathon target
- **WHEN** target is Half Marathon (21.1km)
- **THEN** prediction trend shows HM times, table shows "Halbmarathon Target: 1:47:00", Riegel extrapolates all races to 21.1km

#### Scenario: Target time annotation
- **WHEN** target is Marathon with target_time 4:00:00
- **THEN** prediction trend chart shows horizontal line at 4:00:00 (240 min) labeled "Target 4:00:00"

### Requirement: Pacing strategy adapts to target distance
The race-day pacing strategy SHALL generate splits appropriate for the target distance, not hardcoded marathon (9 × 5km). HM: 4 × 5km + 1.1km. 10K: 2 × 5km.

#### Scenario: HM pacing strategy
- **WHEN** target is HM sub-1:47
- **THEN** pacing shows 5 segments, HR ceilings for HM effort, fueling for HM duration

### Requirement: Prediction summary in race card adapts
The compact prediction in the Race Anchor Card SHALL show the range for the target distance, not always marathon.

#### Scenario: HM prediction range
- **WHEN** target is HM and Riegel predictions range from 1:42-1:55
- **THEN** Race Anchor Card shows "Prediction: 1:42–1:55"

### Requirement: Rename predict_marathon_time to predict_race_time
The function SHALL be renamed and accept `target_km` parameter. Default remains 42.195 for backward compatibility. All callers updated.

#### Scenario: Backward compatibility
- **WHEN** called without target_km
- **THEN** predicts marathon time (42.195km) as before
