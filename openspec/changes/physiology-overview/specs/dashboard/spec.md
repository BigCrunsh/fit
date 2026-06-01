## ADDED Requirements

### Requirement: Your Physiology card on Overview tab
The Overview tab SHALL display a Physiology card showing the four physiological anchors (LTHR, MaxHR, AeT, VO2max) side-by-side. Each anchor SHALL display: current value, one-line description, days since last calibration, and a trend tag. The card SHALL be positioned at the top of the Overview tab and use the design-system surface tinting (accent-tinted, matching `.profile-group-box`).

#### Scenario: All four anchors calibrated
- **WHEN** all four anchors have active calibration rows
- **THEN** the card shows four columns, each with `value`, `unit`, `description`, `days-since-cal`, `trend-tag`

#### Scenario: AeT not yet measured
- **WHEN** no active `aet` calibration exists
- **THEN** the AeT column shows "Not measured" + a link to the drift-test instructions (anchor target `#aet-instructions`)

#### Scenario: LTHR is the primary anchor
- **WHEN** the active zone model is `lthr` (the default)
- **THEN** the LTHR column carries a "primary" badge; other anchors are styled as reference

#### Scenario: Trend tag — stable
- **WHEN** the active LTHR row's value is within ±2 bpm of all prior LTHR rows from the last 6 months
- **THEN** the trend tag shows "stable"

#### Scenario: Trend tag — directional change
- **WHEN** the active LTHR is 175 and the prior was 172 (3 bpm up over 8 weeks)
- **THEN** the trend tag shows "+3 bpm in 8w"

### Requirement: Daniels pace zones panel on Profile tab
The Profile tab SHALL include a Pace Zones panel showing the five Daniels training paces (E / M / T / I / R) derived from active LTHR and VO2max calibrations. Each row SHALL display the pace range (min/km), the zone label, and a one-line description.

#### Scenario: All paces derivable
- **WHEN** active calibrations include `lthr` and `vo2max`
- **THEN** five rows render (E, M, T, I, R) each with a min/km range computed via Daniels formulas

#### Scenario: LTHR missing
- **WHEN** no active `lthr` calibration exists
- **THEN** the panel shows "Calibrate LTHR to compute pace zones" with a link to `fit calibrate lthr`

#### Scenario: Stale LTHR warning
- **WHEN** the active LTHR calibration is past its staleness threshold
- **THEN** each pace row shows a "based on stale LTHR" caution badge; values still render

### Requirement: Concepts glossary on Overview tab
The Overview tab SHALL contain a collapsible `<details>` section labeled "Concepts" near the bottom, containing 2-line explanations of: MaxHR, LTHR, AeT, VO2max, VDOT, ACWR, Monotony, Strain, Cardiac Drift, Z2 ceiling, Effort Class, Run Type. The section SHALL be closed by default to avoid overwhelming the at-a-glance reading.

#### Scenario: Glossary expanded
- **WHEN** user clicks the Concepts summary
- **THEN** the section expands, showing 11 concept definitions in 2-column grid layout

#### Scenario: Concepts shown alongside per-chart toggles
- **WHEN** the dashboard is rendered
- **THEN** existing per-chart `def-toggle` popovers continue to function; the Concepts section is the canonical glossary, the popovers are contextual quick-references
