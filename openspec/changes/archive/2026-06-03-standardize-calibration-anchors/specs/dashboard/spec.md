## ADDED Requirements

### Requirement: Dashboard reads one standardized VDOT anchor
The dashboard's VDOT Trend section and Pace Zones table SHALL both obtain VDOT from `get_calibration_anchor(conn, 'vdot')` — a single value — so they never disagree. Pace Zones SHALL derive Daniels paces from that same active VDOT and never from the optimistic raw Garmin VO2max. (The marathon *forecast* is out of scope here — it is re-sourced by the separate `marathon-durability-model` change, which consumes the same anchor.)

#### Scenario: VDOT section and Pace Zones agree
- **WHEN** the active VDOT anchor is 40
- **THEN** the VDOT Trend section headline and the Pace Zones table both reflect VDOT 40 (no split between 49 / 35.7 / the windowed value)

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

### Requirement: Model assumptions are stated on the dashboard
Sections whose numbers depend on a model SHALL state the model and its key assumptions in their definition popover (`def-box`), so the athlete can judge the figure. The VDOT Trend and Pace Zones sections SHALL note they are **Daniels-based** and assume **population-average running economy** (VDOT is a performance index, not a measured VO₂max). The Marathon Prediction section SHALL note it is **Riegel-based** (power law, default fatigue exponent 1.06; personalized exponent = durability) and that a distorted long race overstates fade.

#### Scenario: VDOT/pace sections disclose the Daniels economy assumption
- **WHEN** the VDOT Trend or Pace Zones definition popover is opened
- **THEN** it states the model is Daniels and that paces/VDOT assume population-average economy, with the athlete's real economy tracked in Aerobic Efficiency

#### Scenario: Marathon Prediction discloses the Riegel/durability assumption
- **WHEN** the Marathon Prediction definition popover is opened
- **THEN** it states the forecast is Riegel-based with a fatigue exponent (default 1.06, personalizable), and that the short-vs-long-race gap is durability
