# Design — tidy-cli-surface

## Alias mechanism (one pattern for every rename)

Each renamed command keeps a **hidden, deprecated alias** at the old name that prints a one-line
notice to stderr and forwards to the new command, so existing scripts/muscle-memory keep working
for one release. In click:

```python
@group.command("old-name", hidden=True)
@click.pass_context
def _old_name_alias(ctx, **kwargs):
    console.print("[yellow]`fit old-name` is deprecated — use `fit new-name`.[/yellow]")
    ctx.forward(new_command)        # forwards parsed args/opts to the canonical command
```

`ctx.forward` re-dispatches with the same params, so the alias needs the same options as its target
(or none, for arg-forwarding). Tests assert: the old name still runs and warns; the new name is
canonical; both produce the same effect.

## The five tidies

1. **`calibrate-history` → `calibrate --history`.** Add a `--history` flag to `calibrate`; when set,
   it renders the reading trail (the current `calibrate-history` body) instead of confirming a
   value. `calibrate-history` becomes the hidden alias forwarding with `--history`.
2. **`splits --backfill` → `sync --splits --backfill`.** `sync` gains a `--backfill` flag (valid
   only with `--splits`) that runs the bulk split-processing the `splits` command does today. `fit
   splits --activity-id` (one-off replay) is retained; `fit splits --backfill` warns + still runs.
3. **`plan sync` → `plan sync-calendar`.** Rename the subcommand; register a hidden `sync` subcommand
   alias. Help text names Runna/Garmin Calendar.
4. **`target` → `objective`.** Rename the group and its `set`/`show`/`clear` subcommands; register a
   hidden `target` group whose subcommands forward to `objective`. DB table stays `goals`; update
   the dashboard "Set a target race with `fit target set`" prompts → `fit objective set`.
5. **`doctor` SSOT-drift check.** A lightweight check that `fit.coaching.context.assemble_coaching_
   context` imports and is callable — guards the `add-fit-coach-cli` extraction from silent breakage.

## Decisions

### Decision 1 — hidden aliases, one release, then remove
Deprecate, don't break. Aliases are `hidden=True` (absent from `--help`) so the surface reads clean,
but they still work and warn. A follow-up change removes them once muscle memory has migrated.

### Decision 2 — DB table stays `goals`
`fit objective` is the user-facing rename only; the `goals` table, `derive_objectives()`, and all
internal references are unchanged (CLAUDE.md: "DB table stays `goals`, user-facing text says
objectives"). This is a CLI + docs rename, not a schema change.

### Decision 3 — ships after add-fit-coach-cli, target→objective last
The coaching move is the priority; the renames are independent churn. Within B, land the low-risk
tidies first and `target → objective` (the biggest break, most docs touched) last.

## Risks

- **`ctx.forward` param mismatch.** The alias must declare the same options as its target or forward
  cleanly; tested per alias.
- **Stale doc/prompt references to `fit target`.** Grep README, CLAUDE.md, GLOSSARY, templates, and
  cards for `fit target` and update every user-facing occurrence; the spec deltas cover the
  capability requirements.
