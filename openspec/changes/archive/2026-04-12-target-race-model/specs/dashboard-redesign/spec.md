## ADDED Requirements

### Requirement: Metric cards replace most standalone charts
Metrics where a single number + context is sufficient SHALL be rendered as compact metric cards (value + action + sparkline + target), not as full Chart.js charts. Cards answer: what is it, where am I, where should I be, what should I do.

#### Scenario: Readiness as metric card
- **WHEN** readiness is 67
- **THEN** card shows: "READINESS 67 · Easy day · target: ≥75" with 7-day sparkline
- **AND** no standalone readiness chart exists (replaced by card)

#### Scenario: Volume as metric card
- **WHEN** this week's volume is 8km and phase target is 25-30km
- **THEN** card shows: "VOLUME 8km · 17km below target · ▁▃█ · 25-30km" with progress bar

#### Scenario: Body tab simplified
- **WHEN** Body tab renders
- **THEN** shows 4-5 metric cards (readiness, RHR, HRV, stress/battery, sleep hours) + 2-3 charts (weight trend, sleep composition, ACWR trend)
- **AND** NOT 6 separate full-size charts

### Requirement: 5-zone color palette used globally
All charts, cards, run timeline bars, zone distribution, and run type breakdowns SHALL use a consistent 5-zone palette with each zone having a distinct color.

#### Scenario: Zone distribution chart uses 5 colors
- **WHEN** zone distribution renders
- **THEN** shows 5 distinct bars: Z1 (light blue), Z2 (blue), Z3 (amber), Z4 (orange), Z5 (red)
- **AND** NOT grouped as Z1+Z2 / Z3 / Z4+Z5

#### Scenario: Run timeline bar colors match zone palette
- **WHEN** a Z2 run appears in the run timeline
- **THEN** the bar color matches the Z2 color in the zone distribution chart

### Requirement: Minimum readability standards
All Chart.js charts SHALL meet minimum contrast and size standards against the #07070c dark background.

#### Scenario: Font size
- **WHEN** any chart renders
- **THEN** default font size is 12px (not 10px)

#### Scenario: Line opacity
- **WHEN** any data line renders on a chart
- **THEN** opacity is at least 60% (not 20%)

#### Scenario: Dataset limit
- **WHEN** a chart would have 3+ competing datasets on the same y-axis
- **THEN** split into separate charts (max 2 datasets per chart)

#### Scenario: Weight chart gap handling
- **WHEN** weight data has a gap >30 days between measurements
- **THEN** the line does NOT connect across the gap

### Requirement: "So what?" context derived from target race objectives
Every metric card and chart caption SHALL derive its context (target, action recommendation) from the target race's auto-derived objectives, not from hardcoded values.

#### Scenario: Volume target from phase
- **WHEN** Phase 1 for marathon has weekly_km_min=25, weekly_km_max=30
- **THEN** volume card shows "target: 25-30km" (from DB, not hardcoded)

#### Scenario: VO2max target from Daniels
- **WHEN** target race is marathon sub-4:00 and Daniels says VO2max ≥50
- **THEN** VO2max card shows "49/50 · 2% to go" (target from derivation)

#### Scenario: No target race set
- **WHEN** no race has is_target=1
- **THEN** cards show values without targets, action says "Set a target: fit target set"

### Requirement: Charts only where time-series shape tells a story
Full Chart.js charts SHALL only be used for metrics where the trend shape over time is the primary insight: efficiency trend, prediction trend, weight trajectory, sleep composition, ACWR pattern.

#### Scenario: Efficiency chart justified
- **WHEN** efficiency chart renders
- **THEN** it shows the aerobic engine trend over months with clear "improving/declining" visual
- **AND** caption: "Your aerobic efficiency is [improving/declining/flat] — [X]% change over 4 weeks"

#### Scenario: Split analysis framing
- **WHEN** split analysis renders for the most recent long run
- **THEN** caption frames it as: "Aerobic ceiling test — your HR decoupled at km [X]. This is where your base building pays off."
