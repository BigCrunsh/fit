## ADDED Requirements

### Requirement: Parse .fit files for per-km split data
The system SHALL download and parse Garmin .fit files for running activities, extracting per-km (or per-lap) data: split distance, split time, split pace, avg HR per split, avg cadence per split, elevation gain per split. Data stored in an `activity_splits` table linked to the activity ID.

#### Scenario: .fit file downloaded and parsed
- **WHEN** `fit sync` runs and a new running activity has a .fit file available via Garmin API
- **THEN** the .fit file is downloaded, parsed, and per-km splits are stored in `activity_splits`

#### Scenario: No .fit file available
- **WHEN** an activity has no downloadable .fit file (e.g., Move IQ auto-detected)
- **THEN** `activity_splits` has no rows for that activity (graceful skip)

### Requirement: Cardiac drift detection per run
The system SHALL compute cardiac drift for each run: compare avg HR of first half vs second half at similar pace. A drift > 5% indicates dehydration, heat stress, or insufficient aerobic base.

#### Scenario: Significant cardiac drift
- **WHEN** a 10km run shows avg HR 145 in first 5km and 158 in last 5km at similar pace
- **THEN** cardiac drift is flagged: "HR drift +9% — possible dehydration or heat effect"

#### Scenario: No drift
- **WHEN** HR is stable across splits
- **THEN** no drift flag

### Requirement: Per-run split visualization in dashboard
The Fitness tab (or a run detail view) SHALL display per-km splits for a selected run: pace per km, HR per km, cadence per km, elevation per km. This enables "where did I fade?" analysis.

#### Scenario: Split chart for long run
- **WHEN** a long run with 18 splits is selected
- **THEN** a chart shows pace and HR per km, highlighting where the fade began

### Requirement: Split data in coaching context
`get_coaching_context()` SHALL include split analysis for the most recent long run (if available): drift percentage, fade point, split consistency.

#### Scenario: Coaching references splits
- **WHEN** Claude generates coaching notes and the last long run has split data
- **THEN** insights can reference: "HR drifted 12% after km 14 — your aerobic base can't sustain this distance yet"
