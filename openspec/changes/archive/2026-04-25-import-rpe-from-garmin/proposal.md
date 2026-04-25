## Why

RPE (Rate of Perceived Exertion) is currently captured in the daily check-in flow and stored per-day in the `checkins` table, then cross-written to all running activities on that date. This breaks down on multi-run days (e.g., morning intervals + evening race) where each session has very different effort, and forces a separate manual entry step that duplicates data the user already enters in Garmin Connect.

Garmin exposes per-activity RPE, "feel", and plan-compliance scores via the activity detail endpoint. Importing these directly removes the duplicate entry, fixes the multi-activity ambiguity, and unlocks two additional signals (feel, compliance) the system does not currently capture.

## What Changes

- **BREAKING**: Remove RPE prompt from `fit checkin run`. RPE is no longer collected via daily check-in.
- Add `feel` (INTEGER 1-5) and `compliance_score` (INTEGER 0-100) columns to `activities` table.
- Repurpose existing `activities.rpe` column: now sourced from Garmin import, not from check-in cross-write.
- During `fit sync`, after fetching the activity list, call `api.get_activity(id)` for each running activity and extract `directWorkoutRpe`, `directWorkoutFeel`, `directWorkoutComplianceScore` from `summaryDTO`.
- Re-fetch detail for activities ≤14 days old (catches user edits in Garmin); fill-NULL-only beyond.
- Add backfill command to populate RPE/feel/compliance for all existing running activities.
- `compute_srpe()` reads directly from `activities.rpe` (no longer joins `checkins.rpe`).
- Remove sRPE computation trigger from `fit checkin` (still runs in `fit sync`).
- Surface RPE, feel, and compliance in dashboard per-run cards.
- Keep `checkins.rpe` column intact for legacy data — no destructive migration.

## Capabilities

### New Capabilities

(none — extends existing capabilities)

### Modified Capabilities

- `data-ingestion`: sync flow gains a per-activity detail-fetch step for running activities to extract RPE/feel/compliance.
- `daily-checkin`: post-run check-in no longer prompts for or records RPE.
- `dashboard`: per-run cards in the last-7-days section surface the new RPE/feel/compliance fields.

## Impact

- **Code**: `fit/garmin.py` (new extraction function), `fit/sync.py` (detail-fetch step), `fit/checkin.py` (remove RPE prompt + cross-write), `fit/analysis.py` (sRPE source), `fit/cli.py` (backfill command, checkin list output), `fit/report/sections/cards.py` and `fit/report/templates/dashboard.html` (display new fields).
- **Schema**: new migration adding `feel` and `compliance_score` to `activities`.
- **Tests**: extend `test_garmin.py` (extraction), `test_sync.py` (detail-fetch step), `test_checkin.py` (remove RPE tests), `test_analysis.py` (sRPE from activities), `test_training_cards.py` (display).
- **Data**: backfill walks all existing running activities (~600 calls, respects existing rate-limit retry) — one-time cost.
- **External APIs**: adds 1 detail call per running activity per sync (default `--days 7` → ≤7 calls).
