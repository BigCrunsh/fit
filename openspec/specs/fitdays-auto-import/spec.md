# fitdays-auto-import Specification

## Purpose
TBD — normalized from archived change deltas; update Purpose.

## Requirements

### Requirement: Apple Health XML import as primary body comp source
Apple Health XML export (`Export.zip`) SHALL be the body comp source. `fit/apple_health.py` parses the Apple Health XML and extracts weight, body fat percentage, lean body mass, and BMI into `body_comp` with `source = 'apple_health'`. Records with the same date upsert via `ON CONFLICT(date)`, preserving prior fields with `COALESCE`.

#### Scenario: Apple Health import via CLI
- **WHEN** user runs `fit import-health ~/Downloads/Export.zip`
- **THEN** body comp data is parsed from the Apple Health XML and imported into the `body_comp` table; calibration table receives a fresh `weight` row from the latest measurement

#### Scenario: Re-import is idempotent on dates
- **WHEN** the same Apple Health export is imported twice
- **THEN** existing dates upsert with COALESCE — no duplicate rows, no NULLed fields

### Requirement: Sync pipeline warns when body comp is stale
The sync pipeline SHALL check the freshness of the latest body_comp row (>14 days = stale) and emit a console warning that points at the Apple Health re-export workflow. Sync itself does NOT auto-parse Apple Health on every run — the export is ~1 GB of XML, so parsing is on-demand via `fit import-health`.

#### Scenario: No body comp data
- **WHEN** `fit sync` runs and `body_comp` is empty
- **THEN** sync outputs: "No body comp data. Run 'fit import-health ~/Downloads/Export.zip' after exporting from the Apple Health app, or enter weight via 'fit checkin'."

#### Scenario: Stale body comp
- **WHEN** `fit sync` runs and latest body_comp row is >14 days old
- **THEN** sync outputs: "Body comp is N days old (last YYYY-MM-DD). Re-export Apple Health → Export.zip and run 'fit import-health ~/Downloads/Export.zip'."

### Requirement: Body fat trend on dashboard
Body fat % SHALL be plotted as a second y-axis line on the Body tab weight chart (faint, different color from weight). `get_coaching_context()` includes body comp trend: "fat trending down + lean mass stable = healthy cut."

#### Scenario: Body comp in coaching
- **WHEN** body_fat_pct decreased from 20.5% to 19.2% over 8 weeks while lean_body_mass_kg stable
- **THEN** coaching context: "Body fat ↓1.3% with stable lean mass — healthy composition change"


### Decision: FitDays CSV import removed (2026-05-31)
An earlier iteration of this capability accepted a FitDays scale CSV export (`sync.weight_csv_path`, `_auto_import_weight`). It proved unreliable — column names varied between FitDays app versions, the manual export step rarely got done, and Apple Health already aggregates the same scale data via HealthKit when the FitDays app is connected. The CSV importer and its config key were removed; Apple Health XML SHALL be the only body comp ingest path.

#### Scenario: FitDays config key rejected
- **WHEN** legacy `sync.weight_csv_path` is present in `config.local.yaml`
- **THEN** sync ignores it (no import path reads it) — the user is expected to migrate to `fit import-health`
