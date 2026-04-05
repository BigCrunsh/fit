## ADDED Requirements

### Requirement: Automated weight + body composition import
The system SHALL automatically import weight and body composition data from Fitdays scale measurements. The import pipeline supports: (1) Apple Health CSV export (existing, improved with auto-detection of file location), (2) direct Fitdays cloud API if available, (3) manual entry via `fit checkin` (existing). All sources upsert into `body_comp` with appropriate `source` tag.

#### Scenario: Apple Health CSV auto-detect
- **WHEN** `fit sync` runs and a weight CSV exists at a known location (~/Downloads/ or configured path)
- **THEN** new weight measurements are imported into body_comp automatically

#### Scenario: Fitdays API import
- **WHEN** Fitdays API credentials are configured and `fit sync` runs
- **THEN** recent weight + body fat + muscle mass measurements are pulled and stored

#### Scenario: No new weight data
- **WHEN** no new weight measurements are available from any source
- **THEN** the data health panel shows weight staleness warning as before

### Requirement: Weight calibration auto-update
When new weight data is imported, the calibration table SHALL be automatically updated with the latest measurement, keeping the weight calibration fresh.

#### Scenario: Weight calibration refreshed
- **WHEN** a new body_comp measurement is imported
- **THEN** the weight calibration entry is updated with the new value and date
