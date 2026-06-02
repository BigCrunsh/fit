## ADDED Requirements

### Requirement: Dashboard reads one standardized VDOT anchor everywhere
The dashboard's VDOT Trend section, Pace Zones table, and marathon forecast SHALL all obtain VDOT from `get_calibration_anchor(conn, 'vdot')` — a single value. The forecast SHALL NOT use raw Garmin VO2max while the VDOT section shows a different anchor. Pace Zones SHALL derive Daniels paces from that same active VDOT.

#### Scenario: Forecast, VDOT section, and Pace Zones agree
- **WHEN** the active VDOT anchor is 40
- **THEN** the VDOT Trend section headline, the Pace Zones table, and the marathon forecast all reflect VDOT 40 (no three-way split between 49 / 35.7 / 35.8)

#### Scenario: Pace Zones never built from the optimistic Garmin estimate
- **WHEN** Garmin VO2max is 49 but the active VDOT anchor is 40
- **THEN** the Easy/Marathon/Threshold paces are computed from 40, not 49

### Requirement: Calibration History visualizes all four anchors over time
The Profile-tab Calibration History SHALL render a time-series chart for each of `vdot`, `lthr`, `max_hr`, `aet`: observations plotted over time, the active value highlighted, and bounds/confidence encoded per the existing marker rubric. VDOT SHALL have a history chart (it previously had none).

#### Scenario: VDOT history chart appears
- **WHEN** the Profile tab renders and `vdot` has ≥2 informational rows (race estimates and/or Garmin)
- **THEN** a VDOT time-series chart appears in Calibration History with the active VDOT highlighted

#### Scenario: Each anchor shows its own series
- **WHEN** Calibration History renders
- **THEN** VDOT, LTHR, MaxHR and AeT each have a series; none is silently omitted when it has data
