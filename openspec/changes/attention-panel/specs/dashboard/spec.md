## ADDED Requirements

### Requirement: Needs Your Attention panel on Overview tab
The Overview tab SHALL display a "Needs Your Attention" panel listing all pending user actions, aggregated from data freshness checks, calibration staleness, coaching review age, and missing data sources. The panel SHALL be positioned at the top of the Overview tab (above the race countdown card) and SHALL NOT render when there are zero attention items (no celebration / empty-state card; absence is the signal).

Each row SHALL display: severity icon (🔴/🟡/🔵), one-line description in imperative voice, optional inline command in a `<code class="value-pill">` element, and an optional tooltip explaining what changes after the action.

The panel SHALL cap visible items at 5; surplus rows collapse into a "+N more" expandable link.

#### Scenario: All sources fresh, no attention items
- **WHEN** all calibrations are within staleness threshold, coaching.json is <7 days old, latest checkin is from today, Apple Health export is <14 days old, and AeT is calibrated
- **THEN** the panel does not render at all

#### Scenario: Multiple stale items rendered by severity
- **WHEN** LTHR is 224 days stale (warning), AeT not measured (info), Apple Health export is 30 days old (warning), latest checkin is 3 days old (info)
- **THEN** the panel renders 4 rows ordered: 2 warning rows first (LTHR retest, Apple Health re-export), then 2 info rows (AeT drift test, checkin reminder)

#### Scenario: Same fact deduplicated across sources
- **WHEN** LTHR is stale according to both `calibration.is_stale('lthr')` and `data_health.check_data_sources()` (which both check the same row)
- **THEN** the panel renders ONE row for LTHR staleness, not two

#### Scenario: Overflow into "+N more"
- **WHEN** 8 attention items would render
- **THEN** the panel shows the top 5 by severity, and a "+3 more" expander; clicking expands to all 8

### Requirement: Alerts list is severity-sorted
The existing alerts list on the Overview tab SHALL render alerts ordered by severity (critical → warning → info), with most-recent-first within a severity tier. Each alert dict returned by `run_alerts()` SHALL include an explicit `severity` field, replacing today's implicit severity inferred from alert type.

#### Scenario: Critical alert renders above warning
- **WHEN** today's alerts include `acwr_spike_danger` (critical) and `all_runs_too_hard` (warning)
- **THEN** the ACWR spike renders above All Runs Too Hard

#### Scenario: Same-severity tie broken by date
- **WHEN** two warning alerts fired (one yesterday, one this morning)
- **THEN** this morning's alert renders first

#### Scenario: Each alert type maps to a fixed severity
- **WHEN** `run_alerts()` returns any alert
- **THEN** the alert dict contains a `severity` field with value `critical`, `warning`, or `info` — never absent, never `None`

### Requirement: Race countdown shows prediction confidence
The race countdown card on the Overview tab SHALL include a one-line "Prediction confidence" note inside the Prediction Trend header row. Confidence is computed from the freshness/availability of the prediction's input anchors:

- **high**: LTHR fresh (<56 days), VO2max fresh (<90 days), ≥2 race data points in last 12 months
- **medium**: any one anchor is stale OR <2 race data points
- **low**: LTHR stale AND VO2max stale, OR no race data points

#### Scenario: All anchors fresh
- **WHEN** LTHR calibrated 30 days ago, VO2max from a race 20 days ago, 3 races logged in last 12 months
- **THEN** the note reads "Prediction confidence: high"

#### Scenario: One anchor stale
- **WHEN** LTHR is 224 days stale, VO2max is recent, races are recent
- **THEN** the note reads "Prediction confidence: medium — LTHR last calibrated 224 days ago"

#### Scenario: No race data available
- **WHEN** no race_calendar entries with `result_time` in the last 12 months
- **THEN** the note reads "Prediction confidence: low — no recent race data"
