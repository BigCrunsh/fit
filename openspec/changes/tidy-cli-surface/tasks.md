# Tasks — tidy-cli-surface

## 1. calibrate --history convenience (calibrate-history KEPT)
- [x] Add `--history` flag to `fit calibrate` (delegates to the reading-trail renderer for its 3 metrics)
- [x] **Decision change:** `calibrate-history` is KEPT (not deprecated) — it accepts a broader metric set (aet/vo2max/weight) that `calibrate` can't set, so a forced merge would break those view-only metrics. `--history` is an ergonomic shortcut for the calibratable metrics; the standalone command remains for the rest.
- [x] Test: `calibrate <metric> --history` shows the trail; `calibrate-history` still present

## 2. splits --backfill → sync --splits --backfill
- [x] `sync` gains `--backfill` (valid with `--splits`) running the bulk split-processing
- [x] `splits --backfill` → deprecation warning, still runs one release; `splits --activity-id` retained
- [x] Test: `sync --splits --backfill` path; `splits --backfill` warns

## 3. plan sync → plan sync-calendar
- [x] Rename `plan sync` → `plan sync-calendar` (help names Runna/Garmin Calendar)
- [x] Hidden `sync` subcommand alias (warns, forwards)
- [x] Test: `plan sync-calendar` canonical; `plan sync` still works + warns

## 4. target → objective (set/show/clear) — ships last
- [x] Rename the `target` group → `objective` (set/show/clear)
- [x] Hidden `target` group (set/show/clear) forwarding to `objective` (warns)
- [x] Update dashboard "Set a target race with `fit target set`" prompts → `fit objective set` (cards/templates)
- [x] Update README, CLAUDE.md quick-commands, GLOSSARY examples → `fit objective`
- [x] Test: `objective set/show/clear` canonical; `target …` still works + warns

## 5. doctor SSOT-drift check
- [x] `fit doctor` asserts `fit.coaching.context.assemble_coaching_context` imports + is callable (guards the add-fit-coach-cli extraction)

## 6. Specs + validate + archive
- [x] `target-race-lifecycle` delta: MODIFY → `fit objective` canonical, `fit target` deprecated alias
- [x] `fit-file-analysis` delta: MODIFY → `fit sync --splits --backfill` (splits --backfill deprecated)
- [x] `runna-integration` delta: MODIFY → `fit plan sync-calendar`
- [x] `openspec validate tidy-cli-surface --strict`; full test suite; `fit --help` reads clean (aliases hidden)
- [x] archive
