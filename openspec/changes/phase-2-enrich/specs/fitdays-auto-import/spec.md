## ADDED Requirements

### Requirement: Automated weight import from configured path
The system SHALL import weight + body composition data from a **configured file path** (not ~/Downloads/ scanning). Path set in `config.yaml` under `sync.weight_csv_path`. During `fit sync`, check if the file has new data (compare row count or hash against `import_log`). Import only dates not already in body_comp.

#### Scenario: New weight data detected
- **WHEN** `fit sync` runs and the configured CSV has 3 new measurements since last import
- **THEN** 3 new rows are inserted into body_comp, import_log entry created

#### Scenario: No new data
- **WHEN** CSV exists but all dates are already in body_comp
- **THEN** no import, no error

#### Scenario: File not found
- **WHEN** configured path does not exist
- **THEN** log warning, data health panel shows "weight CSV not found at [path]"

### Requirement: Import tracking via import_log table
An `import_log` table SHALL track all file imports: filename, file_hash, row_count, rows_imported, import_timestamp, source_type (weight_csv/runna_plan). Prevents duplicate imports and enables debugging.

#### Scenario: Duplicate import prevented
- **WHEN** the same CSV file (same hash) is processed twice
- **THEN** second import is skipped with log: "File already imported (hash matches)"

### Requirement: CSV format validation
The system SHALL validate the CSV header row before parsing. Pin expected column names and date format. Fail with clear error showing expected vs actual columns.

#### Scenario: Wrong CSV format
- **WHEN** CSV has columns "timestamp,mass_kg" instead of "Date,Weight(kg)"
- **THEN** error: "Unexpected columns: timestamp, mass_kg. Expected: Date, Weight(kg)"

### Requirement: Weight calibration auto-update
When new body_comp data is imported, the `calibration` table SHALL be automatically updated with the latest weight measurement.

#### Scenario: Calibration refreshed on import
- **WHEN** 3 new weight measurements are imported, latest is 77.8kg on Apr 10
- **THEN** weight calibration updated to 77.8, date=Apr 10, method='scale'
