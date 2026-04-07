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

## Post-Phase 2 Additions

### Requirement: Apple Health XML import as primary body comp source
The previous "Apple Health out of scope" decision is SUPERSEDED. FitDays CSV export proved unreliable in practice. Apple Health XML export (`Export.zip`) is now the recommended primary body comp source. A new module `fit/apple_health.py` SHALL parse the Apple Health XML export and extract weight, body fat, muscle mass, and visceral fat data.

#### Scenario: Apple Health import via CLI
- **WHEN** user runs `fit import-health ~/Downloads/Export.zip`
- **THEN** body comp data is parsed from the Apple Health XML and imported into the `body_comp` table

#### Scenario: Auto-import during sync
- **WHEN** `sync.apple_health_export` is configured in config.yaml with a path to Export.zip
- **THEN** `fit sync` automatically imports new body comp data from that file

### Requirement: Sync pipeline warns when no body comp source configured
The sync pipeline SHALL check whether any body comp source is configured and warn if none is found. The warning SHALL list the 3 available options.

#### Scenario: No body comp source
- **WHEN** `fit sync` runs and neither `sync.weight_csv_path` nor `sync.apple_health_export` is configured and no manual body_comp rows exist
- **THEN** sync outputs a warning: "No body comp source configured. Options: (1) fit import-health ~/Downloads/Export.zip, (2) sync.apple_health_export in config, (3) sync.weight_csv_path for FitDays CSV"

### Requirement: FitDays CSV deprecated in favor of Apple Health
FitDays CSV export is unreliable (inconsistent column names, manual export steps). Apple Health is the recommended path. FitDays CSV import continues to work but documentation and warnings guide users toward Apple Health.

#### Scenario: FitDays CSV still works
- **WHEN** user has `sync.weight_csv_path` configured
- **THEN** CSV import continues to function, but sync logs an info message: "Consider switching to Apple Health import for more reliable body comp data"
