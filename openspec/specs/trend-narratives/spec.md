## ADDED Requirements

### Requirement: "This Month" trend summary as pill badges
The system SHALL generate a rule-based monthly summary displayed as compact pill-style badges (not paragraph text): "Efficiency +8%" green, "VO2max flat" gray, "Z2 72% ↑" green, "Volume 28km/wk" blue. Expandable detail on click. Each metric has a minimum-data threshold (e.g., 4+ weeks for efficiency trend). Below threshold: "Keep logging — 3 more weeks until trends emerge."

#### Scenario: Sufficient data
- **WHEN** 6+ weeks of data exist with efficiency, VO2max, zone, and volume trends
- **THEN** Today tab shows 4 pill badges with direction arrows and color-coded status

#### Scenario: Insufficient data
- **WHEN** fewer than 4 weeks of data
- **THEN** fallback message: "Keep logging — N more weeks until trends emerge"

### Requirement: "Why" connectors linking correlations to experiences
The system SHALL find the N worst and best runs by efficiency, then check their preceding checkin data (sleep <6h, cycling >30km, alcohol >1) and sleep mismatches (Garmin hours vs subjective quality). Output: "Your 3 worst runs all followed <6h sleep nights." These runs SHALL be annotated on the Training Load chart via Chart.js annotation markers.

#### Scenario: Sleep pattern detected
- **WHEN** 3 of the 5 worst efficiency runs were preceded by <6h sleep
- **THEN** narrative: "Your 3 worst runs all followed <6h sleep nights"
- **AND** those runs are visually marked on the Training Load chart

#### Scenario: Cycling impact detected
- **WHEN** worst runs followed days with >30km cycling
- **THEN** narrative includes cycling as a factor

#### Scenario: Insufficient data
- **WHEN** fewer than 10 runs with checkin data
- **THEN** "Need 10+ runs with checkin data to detect patterns"

### Requirement: Week-over-week with phase context
WoW comparison SHALL annotate against the active phase targets: "Volume up 15% — Phase 1 target is ≤10%." Uses phase's weekly_km_range and z12_pct_target for context.

#### Scenario: Volume exceeds phase target increase
- **WHEN** volume increased 15% and phase target is ≤10% increase
- **THEN** WoW shows warning: "Volume up 15% — Phase 1 target is ≤10%"

### Requirement: Rolling 8-week correlation windows
Correlations SHALL be computed over a rolling 8-week window (not all-time) showing trend direction. Displayed as sparkline small-multiples grid (one per pair, not spaghetti chart). Incremental computation: only recompute if new data arrived for the window.

#### Scenario: Rolling window shows strengthening correlation
- **WHEN** alcohol→HRV correlation was r=-0.2 eight weeks ago and is now r=-0.5
- **THEN** sparkline shows downward trend with arrow, labeled "getting stronger"

#### Scenario: Less than 8 weeks of data
- **WHEN** fewer than 8 weeks of checkin data
- **THEN** show static correlation with note "Rolling window available after 8 weeks"

### Requirement: Race countdown narrative with taper model
Race countdown SHALL include phase position and objective progress. For the final 2-3 weeks: include taper rules (volume drop 40-60%, intensity stays, last quality session ~10 days out).

#### Scenario: Far from race
- **WHEN** 174 days to Berlin, Phase 1 active
- **THEN** "174 days to Berlin. Phase 1 of 4. 3/4 objectives on track."

#### Scenario: Taper period
- **WHEN** 14 days to race
- **THEN** "14 days to Berlin. Taper: volume drops 40-60%, last quality session in 4 days. Trust your training."

### Requirement: Z2 compliance remediation narrative
When Z2 compliance is below 50% for 3+ consecutive weeks, the system SHALL generate a specific remediation narrative with concrete pace/HR targets, not just flag the non-compliance. This addresses the most common training error for marathon runners.

#### Scenario: Chronic Z2 non-compliance
- **WHEN** Z2 compliance is 15% for 4 consecutive weeks and Z2 ceiling is 134bpm / 6:30/km
- **THEN** narrative: "Easy runs consistently too fast. Z2 ceiling: HR 134 / pace 6:30/km. Try run-walk if needed."

### Requirement: Walk-break detection for detrained runners
When Z2 runs show cardiac drift before km 5 (from .fit split data when available, or estimated from pace fade), the system SHALL suggest structured run-walk intervals as a training tool. Include exit criteria: graduate from run-walk when Z2 runs sustain <5% drift through km 8.

#### Scenario: Early drift detected
- **WHEN** a Z2 run shows HR drift >5% before km 5
- **THEN** narrative: "Consider run-walk intervals (e.g., 4min run / 1min walk) to build Z2 endurance without cardiac drift"

#### Scenario: Ready to graduate from run-walk
- **WHEN** last 3 Z2 runs sustained <5% drift through km 8
- **THEN** narrative: "Z2 endurance improving — try continuous Z2 running (drop walk breaks)"

### Requirement: Today tab visual hierarchy
The Today tab DOM order SHALL be: headline → **alerts** (safety first) → race countdown → milestone celebrations → objectives → "This Month" badges → phase compliance → journey timeline. Alerts are above race countdown because safety information takes priority over motivational content. Narratives beyond 2 items collapse via progressive disclosure (<details>).

#### Scenario: Multiple narratives
- **WHEN** there are 4 narrative items (trend, why-connector, WoW warning, walk-break suggestion)
- **THEN** first 2 show, remaining 2 behind "Show more" toggle

#### Scenario: Critical alert visibility
- **WHEN** there is a return-to-run volume cap alert and a race countdown
- **THEN** alert appears ABOVE the race countdown

### Requirement: Chart annotation collision handling
When multiple Chart.js annotations target the same or nearby data points (e.g., "worst run" + "heat affected" + "PB"), the system SHALL stack annotations vertically with 2px offset per layer. Maximum 3 annotations per point; beyond that, collapse into a summary tooltip "3 factors."

#### Scenario: Multiple annotations on same run
- **WHEN** a run is both "worst efficiency" and "heat affected"
- **THEN** two annotation markers stacked vertically, both visible without overlap

### Requirement: Sparkline axis consistency
All sparklines in the rolling correlation grid SHALL use a consistent y-axis range (-1.0 to +1.0) across all pairs. This allows visual comparison of correlation strength between pairs. Individual sparklines do NOT auto-scale to their own data range.

#### Scenario: Weak vs strong correlation visual comparison
- **WHEN** alcohol→HRV is r=-0.6 and sleep→efficiency is r=0.2
- **THEN** both sparklines use -1 to +1 y-axis, making the alcohol effect visually stronger
