## 1. Schema migration

- [x] 1.1 Create `migrations/013_activity_rpe_feel_compliance.sql` adding `feel INTEGER` and `compliance_score INTEGER` columns to `activities` (both nullable). (Initially numbered 012, renumbered to 013 due to a pre-existing 012 in the live DB schema_version.)
- [x] 1.2 Verify migration runs cleanly against an existing DB and via the test fixture chain.

## 2. Garmin extraction

- [x] 2.1 Add `fetch_activity_rpe(api, activity_id) -> dict` to `fit/garmin.py` that calls `api.get_activity(id)` and returns `{"rpe": int|None, "feel": int|None, "compliance_score": int|None}` extracted from `summaryDTO`.
- [x] 2.2 Apply the mapping `rpe = directWorkoutRpe / 10`, `feel = directWorkoutFeel / 25 + 1`, `compliance_score = directWorkoutComplianceScore`. Treat missing keys and NULL values as None passthrough.
- [x] 2.3 Wrap the API call with `_request_with_retry` for 429/5xx handling.

## 3. Sync integration

- [x] 3.1 In `fit/sync.py` `run_sync()`, after the bulk activity fetch, iterate running activities. For each, decide refresh policy: re-fetch if activity ≤14 days old; fill-NULL-only if older.
- [x] 3.2 For activities meeting the policy, call `fetch_activity_rpe` and `UPDATE activities SET rpe = COALESCE(?, rpe), feel = COALESCE(?, feel), compliance_score = COALESCE(?, compliance_score) WHERE id = ?` (preserves existing values when Garmin returns NULL).
- [x] 3.3 For activities ≤14 days old with non-NULL Garmin values, overwrite (force-refresh): `UPDATE activities SET rpe = ?, feel = ?, compliance_score = ? WHERE id = ?` only when at least one Garmin value is non-NULL.
- [x] 3.4 Add per-activity progress reporting (rich Progress) for the detail-fetch step.
- [x] 3.5 Move the sRPE recompute trigger so it runs after the RPE detail-fetch step in `fit sync` (it already runs there; verify ordering after the new step).

## 4. Backfill command

- [x] 4.1 Add `fit backfill rpe` Click command in `fit/cli.py` that walks all running activities lacking `rpe`/`feel`/`compliance_score` and calls `fetch_activity_rpe` for each.
- [x] 4.2 Add `--refresh` flag to force re-fetch even when fields are already populated.
- [x] 4.3 Display rich Progress bar with activity count and current activity name.
- [x] 4.4 Document the 14-day refresh window in the command's `--help` text.

## 5. sRPE source switch

- [x] 5.1 Update `compute_srpe()` in `fit/analysis.py` to read `rpe` directly from `activities.rpe` instead of joining `checkins.rpe`. Compute `srpe = rpe * duration_min` for any running activity with non-NULL rpe.
- [x] 5.2 Remove the sRPE trigger from `fit/checkin.py` `_save_checkin` (lines around 185-194). sRPE is now triggered only from `fit sync`.
- [x] 5.3 Verify no other code path reads `checkins.rpe` for sRPE computation; update or remove if found.

## 6. Remove RPE from check-in

- [x] 6.1 In `fit/checkin.py` `run_post_run`, remove the RPE prompt block (the cur_rpe/Prompt.ask/data["rpe"] section). Keep activity context display and session notes prompt.
- [x] 6.2 Remove the `rpe` field from `_save_checkin`'s data dict and the cross-write `UPDATE activities SET rpe = ?` block.
- [x] 6.3 Update `_save_checkin`'s INSERT statement: keep the `rpe` column listed (legacy compatibility) but always pass NULL for new check-ins.
- [x] 6.4 Update `fit/cli.py` `checkin list` (around line 198) to either drop the RPE column from the table view or source it from `activities.rpe` joined by date.

## 7. Dashboard display

- [x] 7.1 Update `fit/report/sections/cards.py` `_last_7_days_runs` to select `rpe`, `feel`, `compliance_score` from `activities`.
- [x] 7.2 Add the three fields to each run dict (`rpe`, `feel_label` derived from 1-5 → Bad/Poor/Neutral/Good/Great, `compliance_score`).
- [x] 7.3 Update `fit/report/templates/dashboard.html` per-run card to render `RPE N · Feel: <label> · Compliance N%` next to existing metrics, with `—` for NULL.
- [x] 7.4 Verify rendering on the existing `~/.fit/reports/dashboard.html` using `fit report`.

## 8. Tests

- [x] 8.1 `tests/test_garmin.py`: add `test_fetch_activity_rpe_extracts_values` (all three fields present), `test_fetch_activity_rpe_missing_keys` (none present), `test_fetch_activity_rpe_partial` (only rpe present). 7 tests added covering all three fields, partial population, missing keys, missing summaryDTO, explicit nulls, and api returning None.
- [x] 8.3 `tests/test_checkin.py`: removed RPE-related tests for `run_post_run`; added `test_post_run_does_not_prompt_rpe`; verified `checkins.rpe` stays NULL on new check-ins; updated yesterday-gap test (run section is no longer auto-prompted).
- [x] 8.4 sRPE tests in `tests/test_coaching_metrics.py` updated to populate `activities.rpe` directly. Includes test for sRPE NULL when activity rpe missing.
- [x] 8.5 `tests/test_training_cards.py`: added `test_run_card_displays_rpe_feel_compliance`, `test_run_card_handles_null_rpe`, `test_run_card_partial_fields`, `test_run_card_feel_label_mapping`.
- [ ] 8.2 `tests/test_sync.py`: add `test_sync_fetches_detail_for_recent_running_activity`, `test_sync_skips_old_activity_with_rpe`, `test_sync_fills_null_for_old_activity_without_rpe`, `test_sync_skips_non_running_activity`. (Deferred — sync tests would require extensive mocking of the Garmin client across the entire pipeline; the integration was verified end-to-end via `fit sync --days 3` against real Garmin data.)
- [ ] 8.6 Add a CLI test for `fit backfill rpe` (mocking `fetch_activity_rpe`) verifying it walks unpopulated activities and respects `--refresh`. (Deferred — same reason; behavior verified by calling `fit backfill rpe --help` and via the live sync flow.)

## 9. Documentation & cleanup

- [x] 9.1 Update `CLAUDE.md` "Design Decisions That Prevent Mistakes" with: RPE/feel/compliance source = Garmin (not check-in); 14-day re-fetch window.
- [x] 9.2 Run `fit sync` once to verify end-to-end behavior on the real DB.
- [x] 9.3 Run `fit backfill rpe` once to populate historical activities (139 scanned, 108 updated, 31 new sRPE).
- [x] 9.4 Verify dashboard shows the new fields on real data.
- [x] 9.5 Run full test suite (`pytest tests/ -v`) — must stay green (770 passed).

## 10. Commit (logical units)

- [x] 10.1 Commit OpenSpec artifacts (proposal/design/specs/tasks).
- [x] 10.2 Commit migration + Garmin extraction (1.x + 2.x). [de18b78]
- [x] 10.3 Commit sync integration + sRPE source switch (3.x + 5.x). [8812a7a]
- [x] 10.4 Commit backfill command (4.x). [195b79b]
- [x] 10.5 Commit check-in changes (6.x). [bb77ebc]
- [x] 10.6 Commit dashboard display (7.x). [5a2c6d6]
- [x] 10.7 Commit docs updates (CLAUDE.md + README.md). [c97a99f]
