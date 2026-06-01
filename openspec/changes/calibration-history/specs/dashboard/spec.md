## ADDED Requirements

### Requirement: Calibration history chart per metric on Profile tab
The Profile tab SHALL include a "Calibration History" section containing one Chart.js chart per metric (`lthr`, `max_hr`, `aet`, `weight`, `vo2max`). Each chart SHALL plot every calibration row over time as a point, regardless of whether the row is the currently active one.

Each chart SHALL:

- Style points by confidence: solid filled dot = `high`, hollow dot = `medium`, red ring outline = `low`
- Show a horizontal band marking the staleness threshold for that metric (`STALENESS_THRESHOLDS[metric]`); when the active row's date crosses the band the band background turns red
- Provide a tooltip on each point listing: date, value, method, confidence, flags (joined), source activity name (if any)
- Render via Chart.js with `type: 'time'` x-axis matching the rest of the dashboard

#### Scenario: Two LTHR readings render with confidence styling
- **WHEN** LTHR history contains two race-extracted readings (172 in 2025-10 with confidence=medium, 171 in 2026-04 with flags=['agrees_with_prior'] and confidence=high)
- **THEN** the chart shows two dots — the 2026-04 dot is solid filled (high), the 2025-10 dot is hollow (medium); tooltip on the second shows `method=race_extract, confidence=high, flags=['agrees_with_prior']`

#### Scenario: Implausible spike renders with red ring
- **WHEN** max_hr history contains a `low`-confidence row with flags `['implausible_value']` and a clean `medium` row
- **THEN** the chart shows the implausible row with a red ring outline; the active line (drawn between non-flagged rows) does not pass through it; tooltip lists the flags

#### Scenario: Active row crosses staleness threshold
- **WHEN** the active LTHR row is 224 days old, exceeding `STALENESS_THRESHOLDS['lthr']` (56 days)
- **THEN** the chart's staleness band renders in caution-red; the active row's point also gets a caution ring

#### Scenario: Missing metric chart
- **WHEN** `aet` has zero calibration rows
- **THEN** the AeT chart slot shows an empty-state card with the message "AeT not yet measured" and a link to drift-test instructions; no Chart.js canvas is created

### Requirement: CLI calibration history command
The CLI SHALL expose `fit calibrate history <metric>` printing a sparkline summary plus a tabular history of every calibration row for that metric. The table SHALL include: date, value, method, confidence, flags, source activity (if any).

#### Scenario: History for LTHR
- **WHEN** user runs `fit calibrate history lthr`
- **THEN** stdout shows a small ASCII sparkline followed by a rich Table with one row per calibration entry, sorted oldest first
