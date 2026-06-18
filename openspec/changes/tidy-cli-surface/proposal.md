## Why

The holistic CLI review (done while adding `fit coach`) found the 19-command surface is mostly
justified, but a handful of names/groupings hurt clarity, and one name diverges from the domain
language the glossary mandates. Folding these tidies in now — while the CLI is already being
touched — keeps the surface coherent. Each rename is **breaking** (muscle memory, scripts, the
Desktop registration is untouched), so each ships with a **hidden deprecated alias** that still
works (with a one-line notice) for one release.

## What Changes

- **`fit calibrate-history <metric>` → `fit calibrate <metric> --history`.** Viewing the reading
  trail and confirming a new value are one workflow; two commands split it. `calibrate-history`
  stays as a hidden deprecated alias that delegates.
- **`fit splits --backfill` → `fit sync --splits --backfill`.** `sync` already owns `--splits`
  (downloading .fit files); the bulk backfill belongs there. `fit splits --activity-id <id>` (the
  one-off replay) is **retained**; `fit splits --backfill` warns and still runs for one release.
- **`fit plan sync` → `fit plan sync-calendar`.** It pulls Runna workouts from the Garmin Calendar,
  not a re-sync of activities — the name now says so. Hidden `sync` alias retained.
- **`fit target` → `fit objective` (`set`/`show`/`clear`).** The glossary's one mandated rename:
  "Objective" is the athlete-facing term (the dashboard already says "objectives"; the DB table
  stays `goals`). `fit target [set|show|clear]` stays as a hidden deprecated alias group. Ships
  last (biggest break). README / CLAUDE.md / GLOSSARY examples + the dashboard "Set a target …"
  prompts update to `fit objective set`.
- **`fit doctor` SSOT-drift check** — assert `assemble_coaching_context` still imports/builds (a
  lightweight guard that the coaching extraction from `add-fit-coach-cli` stays wired).

No change to the other 13 commands (`sync`, `forecast`, `auth`, `mcp`, `checkin`, `races`,
`backfill`, `effort`, `report`, `recompute`, `correlate`, `import-health`, `status`) — all justified
by distinct responsibilities.

## Impact

- **Clearer surface, glossary-conformant naming** — one workflow per concept; the athlete-facing
  command matches the athlete-facing noun ("objective").
- **No silent breakage** — every renamed command keeps a hidden alias for one release that delegates
  and prints a deprecation notice; tests assert old-name-still-works-and-warns + new-name-canonical.
- **No DB/schema change** — the `goals` table is unchanged; this is CLI-surface + docs only.
- **Code**: `fit/cli.py` (the renames + aliases); the dashboard "Set a target" prompt strings;
  README / CLAUDE.md / GLOSSARY examples.
- **Specs**: `target-race-lifecycle` (MODIFY → `fit objective`, `fit target` deprecated),
  `fit-file-analysis` (MODIFY → `fit sync --splits --backfill`), `runna-integration` (MODIFY →
  `fit plan sync-calendar`).

Affected capabilities: **target-race-lifecycle**, **fit-file-analysis**, **runna-integration**.
Follows `add-fit-coach-cli`.
