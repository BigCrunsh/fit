## ADDED Requirements

### Requirement: Sync writes informational VDOT estimate rows from races
The sync pipeline SHALL write an informational `vdot` calibration row (`method='race_estimate'`, `confidence='low'`, `active=0`, keyed idempotently by `source_activity_id`) for each completed race with a usable result time and distance, computing VDOT via the Daniels formula. These rows SHALL NOT become the active calibration on their own; they feed the VDOT aggregation policy and the VDOT calibration-history chart. A one-off `fit backfill vdot` SHALL populate these rows over race history (mirroring `fit backfill rpe`).

#### Scenario: Completed race produces an informational VDOT row
- **WHEN** sync processes a completed half-marathon of 1:47:00
- **THEN** a `{metric:'vdot', method:'race_estimate', confidence:'low', active:0, source_activity_id:<id>}` row is written, and re-syncing the same activity does not duplicate it

#### Scenario: Backfill populates VDOT history without changing the active anchor
- **WHEN** `fit backfill vdot` runs over the full race calendar
- **THEN** one informational `vdot` row per qualifying race is written; the active VDOT is still produced by `get_calibration_anchor` from the aggregation policy, unchanged by the backfill itself

#### Scenario: Race without a usable result is skipped
- **WHEN** a race row has status `dns` or a missing/zero result time and no Garmin time
- **THEN** no `vdot` estimate row is written for it
