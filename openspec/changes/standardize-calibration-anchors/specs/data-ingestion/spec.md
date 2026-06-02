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

### Requirement: Calibration anchors change only on confirmation, surfaced at sync
The active calibration anchor SHALL NOT change automatically. After ingesting new data, `fit sync` SHALL compute each metric's policy suggestion via `get_calibration_anchor` and compare it to the current active value. When the suggestion differs from active beyond the per-metric "differs materially" threshold, the system SHALL raise a pending calibration suggestion. In an interactive (TTY) sync it SHALL prompt accept/reject inline; in a non-interactive sync it SHALL persist the suggestion as pending (surfaced by `fit status`, the dashboard attention panel, and `fit calibrate`) and SHALL NOT block. Accepting writes the active calibration (`method='confirmed'`, `confidence='high'`); rejecting leaves active unchanged. A suggestion ledger SHALL record a rejected value and suppress re-raising the same suggestion until the policy output changes materially from it.

#### Scenario: Interactive sync prompts and the athlete accepts
- **WHEN** a new road race lifts the VDOT policy suggestion to 40.4 while active VDOT is 35.8, and `fit sync` runs in a TTY
- **THEN** sync prompts "VDOT: suggest 40.4 … active 35.8. Accept? [y/N]"; on `y` it writes `{metric:'vdot', value:40.4, method:'confirmed', confidence:'high', active:1}`

#### Scenario: Headless sync persists a pending suggestion, never blocks
- **WHEN** the same suggestion arises during a cron/non-TTY sync
- **THEN** sync does not prompt or block; the suggestion is stored as pending and appears in `fit status` and the dashboard attention panel for later accept/reject

#### Scenario: A rejected suggestion is not re-raised until it changes
- **WHEN** the athlete rejects the VDOT 40.4 suggestion and the next sync recomputes the same ~40.4
- **THEN** no prompt is raised again; the ledger suppresses it until the policy output moves materially away from 40.4

#### Scenario: A slow trail race never lowers the anchor (no prompt)
- **WHEN** a slow trail half produces a VDOT estimate of 35.8 while the recency-decayed max is 40.4
- **THEN** the policy suggestion stays 40.4, no downward change is suggested, and no terrain tagging is required
