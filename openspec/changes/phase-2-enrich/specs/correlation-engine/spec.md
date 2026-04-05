## ADDED Requirements

### Requirement: Cross-domain correlation analysis
The system SHALL compute correlations between subjective inputs (alcohol, sleep quality, hydration, eating, RPE) and objective outcomes (next-day HRV, readiness, RHR, cardiac efficiency, pace). Correlations SHALL be time-lagged where appropriate (yesterday's alcohol → today's HRV). Results stored in a `correlations` table with: metric_pair, lag_days, correlation_coefficient, sample_size, last_computed.

#### Scenario: Alcohol → next-day HRV
- **WHEN** 10+ checkins with alcohol data and matching next-day HRV exist
- **THEN** the system computes the correlation between alcohol (drinks) and next-day HRV (lag=1), stores the result

#### Scenario: Weight → pace trend
- **WHEN** 10+ weeks of weight and running pace data exist
- **THEN** the system computes the correlation between weekly avg weight and weekly avg pace

#### Scenario: Temperature → cardiac drift
- **WHEN** 10+ runs have per-activity weather (temp_at_start_c) and speed_per_bpm data
- **THEN** the system computes the correlation between temperature and efficiency loss

#### Scenario: Insufficient data
- **WHEN** fewer than 10 data points exist for a correlation pair
- **THEN** the correlation is marked as "insufficient_data" with the current sample count

### Requirement: Correlation results surfaced in dashboard and coaching
The Fitness tab SHALL display a correlation summary panel showing the strongest positive and negative correlations with their effect sizes. The coaching context (`get_coaching_context()`) SHALL include top correlations so Claude can reference them in analysis.

#### Scenario: Dashboard correlation panel
- **WHEN** correlations have been computed
- **THEN** the Fitness tab shows "Alcohol → HRV: r=-0.45 (strong negative, n=15)" with color-coded strength

#### Scenario: Coaching context includes correlations
- **WHEN** Claude calls `get_coaching_context()`
- **THEN** the response includes the top 5 correlations by absolute strength

### Requirement: fit correlate command
`fit correlate` SHALL recompute all correlations from current data and display a summary table. Run after sync or on demand.

#### Scenario: Compute and display
- **WHEN** user runs `fit correlate`
- **THEN** all correlation pairs are computed and a ranked table is displayed in the terminal
