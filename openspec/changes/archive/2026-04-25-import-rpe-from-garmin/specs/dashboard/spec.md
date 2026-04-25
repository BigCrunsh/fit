## ADDED Requirements

### Requirement: Per-run cards display RPE, feel, and compliance from Garmin
The dashboard's last-7-days run cards SHALL display the Garmin-imported `rpe` (1-10), `feel` (1-5), and `compliance_score` (0-100) for each running activity when present. The fields SHALL render in the activity detail line alongside training_load, with `—` placeholders when NULL. Feel SHALL be rendered as a 5-point label (e.g., "Bad/Poor/Neutral/Good/Great") for readability, while RPE and compliance render as numeric values.

#### Scenario: Activity has all three fields populated
- **WHEN** a run has `rpe = 7`, `feel = 4`, `compliance_score = 95`
- **THEN** the card displays `RPE 7 · Feel: Good · Compliance 95%` alongside other metrics

#### Scenario: Activity has none of the fields populated
- **WHEN** a run has `rpe`, `feel`, and `compliance_score` all NULL
- **THEN** the card displays `RPE — · Feel — · Compliance —` (or omits these labels entirely; rendering MUST be consistent across runs)

#### Scenario: Partial fields populated
- **WHEN** a run has `rpe = 5` but `feel` and `compliance_score` are NULL
- **THEN** the card displays the available value and `—` for missing ones (no visual gap or layout shift)
