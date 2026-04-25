## REMOVED Requirements

### Requirement: RPE captures perceived workout effort
**Reason**: RPE is now sourced per-activity from Garmin Connect (`directWorkoutRpe` on `summaryDTO`), eliminating duplicate manual entry and correctly attributing different effort to multiple runs on the same day.

**Migration**: Users enter RPE in Garmin Connect (on the watch post-run, or in the Connect app) instead of via `fit checkin run`. The post-run check-in still prompts for session notes; RPE is no longer collected. Historical `checkins.rpe` values remain in the database but are no longer used by sRPE or any other downstream computation. Run `fit backfill rpe` to populate historical activity RPE from Garmin.

## MODIFIED Requirements

### Requirement: Interactive daily check-in CLI
The system SHALL provide a `fit checkin` CLI command that interactively prompts for daily wellness inputs and stores them via INSERT ON CONFLICT into the `checkins` table. Inputs SHALL be split across three moments: morning (sleep quality, legs, energy), post-run (session notes only), and evening (hydration, eating, alcohol, alcohol detail, water). RPE is NOT prompted in any check-in moment — it is sourced per-activity from Garmin during sync.

#### Scenario: Morning check-in collects readiness fields
- **WHEN** user runs `fit checkin morning`
- **THEN** the system prompts for sleep quality, legs, energy, and notes; saves to `checkins` row for today

#### Scenario: Post-run check-in collects session notes only
- **WHEN** user runs `fit checkin run` after a running activity
- **THEN** the system displays the activity's name, distance, HR zone, and aerobic TE for context, then prompts for session notes only (no RPE prompt)

#### Scenario: Evening check-in collects recovery fields
- **WHEN** user runs `fit checkin evening`
- **THEN** the system prompts for hydration, eating, alcohol (with optional detail), and water liters; saves to `checkins` row for today
