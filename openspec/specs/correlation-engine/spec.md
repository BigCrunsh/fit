## MODIFIED Requirements

### Requirement: Rolling correlation windows
The existing static correlation computation SHALL be extended with rolling 8-week windows showing "this correlation is getting stronger/weaker." Displayed as sparkline small-multiples grid (one per pair, consistent y-axis -1.0 to +1.0). Incremental computation: store `window_end_date` and `data_hash` per pair per window. On recompute, skip if hash unchanged.

ALL pairs require minimum n≥15 data points AND minimum |r|≥0.2 before surfacing in coaching context or narratives. Below threshold: computed and stored but not displayed.

#### Scenario: Rolling window computed
- **WHEN** 8+ weeks of checkin + health data exist with n≥15 points
- **THEN** each correlation pair shows an 8-week sparkline with trend arrow

#### Scenario: Incremental skip
- **WHEN** data_hash for a pair's rolling window is unchanged since last compute
- **THEN** that pair's rolling computation is skipped

#### Scenario: Weak correlation suppressed
- **WHEN** a pair has |r|=0.12 with n=20
- **THEN** computed and stored but not shown in coaching or dashboard

### Requirement: Cycling correlation pair
Add correlation: previous-day cycling_km → next-day run efficiency (speed_per_bpm). Uses lag=1.

#### Scenario: High cycling → low efficiency
- **WHEN** days with >25km cycling precede runs with lower-than-average speed_per_bpm
- **THEN** correlation is negative, flagged in coaching context

### Requirement: SpO2 correlation pair (optional)
Consider adding: SpO2 → training_readiness. Validate whether it's a useful signal for this specific user before surfacing.

#### Scenario: SpO2 correlates with readiness
- **WHEN** n≥20 data points and Spearman r > 0.3
- **THEN** include in correlation display with note "SpO2 may predict readiness for you"

#### Scenario: No correlation found
- **WHEN** r < 0.15 with n≥20
- **THEN** do not display (not a useful signal for this user)
