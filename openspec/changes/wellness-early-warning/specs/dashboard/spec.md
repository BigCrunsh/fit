# dashboard — delta for wellness-early-warning

## ADDED Requirements

### Requirement: Respiration chart on Readiness tab
The Readiness tab SHALL display a respiration time-series chart when respiration data exists: sleep respiration as the primary line, waking respiration as a secondary muted line, and a horizontal annotation band at the personal baseline ± the configured deviation delta sourced from the shared wellness snapshot (same values the alert rules use). The chart SHALL follow the repo chart conventions: `type: 'time'` x-axis with ISO date labels, design-system palette colors, and annotation band fill at 40+ hex opacity. When no respiration data exists in the window, the chart SHALL be omitted entirely (no empty chart box).

#### Scenario: Chart rendered with both series and baseline band
- **WHEN** the last 30 days contain waking and sleep respiration values and a baseline is defined
- **THEN** the Readiness tab includes a respiration chart with two series and a baseline ± delta band

#### Scenario: No respiration data omits the chart
- **WHEN** `daily_health` has no respiration values in the window
- **THEN** the dashboard renders without a respiration chart box

#### Scenario: Baseline undefined renders series without band
- **WHEN** respiration values exist but fewer than 14 baseline observations are available
- **THEN** the chart renders the series without a baseline band
