## ADDED Requirements

### Requirement: Full body composition import from FitDays CSV
The weight CSV importer SHALL parse body_fat_pct, muscle_mass_kg, visceral_fat from FitDays CSV alongside weight_kg. Column name detection (case-insensitive matching). Skip BMI (derivable), bone mass, body water, metabolic age, protein, subcutaneous fat (BIA noise — not actionable for marathon training).

#### Scenario: Full body comp parsed
- **WHEN** FitDays CSV has columns Date, Weight(kg), Body Fat(%), Muscle(kg), Visceral Fat
- **THEN** all values stored in body_comp table per row

#### Scenario: Weight-only CSV
- **WHEN** CSV only has Date and Weight columns
- **THEN** weight imported, body comp fields remain NULL

### Requirement: Body fat trend on dashboard
Add body fat % as a second y-axis line on the Body tab weight chart (faint, different color from weight). Include body comp trend in `get_coaching_context()`: "fat trending down + muscle stable = healthy cut."

#### Scenario: Body comp in coaching
- **WHEN** body_fat_pct decreased from 20.5% to 19.2% over 8 weeks while muscle_mass_kg stable
- **THEN** coaching context: "Body fat ↓1.3% with stable muscle — healthy composition change"

### Requirement: Apple Health explicitly out of scope
Do NOT build an Apple Health integration for body comp. The data originates from the FitDays scale — Apple Health is a middleman that loses data (no visceral fat in HealthKit). Apple Health has no API accessible from non-Apple platforms. Extending the FitDays CSV import directly gives more data with less effort.

#### Scenario: Apple Health not proposed
- **WHEN** evaluating body comp data sources
- **THEN** FitDays CSV is the path, not Apple Health (decision recorded, prevents re-proposal)
