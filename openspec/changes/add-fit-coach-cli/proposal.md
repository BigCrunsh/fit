## Why

Coaching today is split across two sources that must be kept in sync by hand: the MCP server
assembles the data context (`get_coaching_context` + the `_ctx_*` builders) and the `/fit-coach`
**skill** (`.claude/skills/fit-coach/SKILL.md`) holds the reasoning. CLAUDE.md explicitly flags this
as a drift contract ("the MCP and the coaching skill … are a contract, not independent files").
Running coaching also requires being inside a Claude client with the MCP registered.

Moving coaching into a `fit coach` CLI command that shells out to the headless `claude` CLI collapses
both sources into **one CLI-owned source of truth** — the context-assembly and the coaching prompt
live together in `fit/coaching/`, consumed by the command directly. It removes the drift contract,
makes coaching runnable from the terminal, and (the user's explicit ask) lets the MCP shed its
coaching responsibility while **keeping its 6 data-access tools** for free-form exploration.

Review also found two latent defects in the MCP coaching path: `_ctx_forecast` is wrongly
`@mcp.tool()`-decorated and **dead** (its `conn` argument can't be supplied over JSON — no client can
call it), and `get_coaching_context` is an *undecorated* plain function (the SKILL.md Step-0
preflight that tells the user to confirm it "exists as a tool" is already stale). So retiring the MCP
coaching path is mostly extract-and-rewire plus one bug fix.

## What Changes

- **New `fit/coaching/` package** — the shared core: `context.py` (the `_ctx_*` builders +
  `assemble_coaching_context(conn)`, lifted verbatim from `mcp/server.py`), `prompt.py`
  (`COACHING_INSTRUCTIONS` = the SKILL.md reasoning, Steps 1–5), `save.py` (the notes writer, moved
  verbatim — validation + `coaching_history.json` archival + atomic write), `runner.py` (the
  `claude -p` subprocess + parse + persist).
- **New `fit coach` command** — assembles the context, feeds it + `COACHING_INSTRUCTIONS` to
  `claude -p … --output-format json`, parses the result, prints the analysis, and saves notes to
  `reports/coaching.json` (the existing sidecar — **no schema migration**). Flags: `--no-save`,
  `--json`, `--days N`, `--model`, `--timeout`, `--force`. Every failure path (claude missing / auth
  / network / timeout / bad JSON / invalid insights) **writes nothing** — coaching.json is never
  corrupted.
- **MCP sheds coaching entirely** — remove the dead `@mcp.tool()` on `_ctx_forecast`; remove
  `save_coaching_notes` and `get_coaching_context` from the MCP (coaching notes now come only from
  `fit coach`). The **6 data-access tools stay** (`execute_sql_query`, `get_health_summary`,
  `get_run_context`, `explore_database_structure`, `get_table_details`, `check_dashboard_freshness`),
  and the committed `.mcp.json` path is unchanged, so Desktop/Code registrations don't churn.
- **Retire `SKILL.md`** to a one-screen redirect stub pointing at `fit coach` (keep the file so
  `/fit-coach` lands on the redirect, not a 404).
- **Docs/UI**: `cards.py` attention item `/fit-coach` → `fit coach`; CLAUDE.md quick-commands + the
  MCP↔skill SSOT note rewritten ("coaching prompt + context live in `fit/coaching/`, CLI-owned").

## Impact

- **One source of truth for coaching** — the drift contract is gone; the prompt and the context are
  one package. A regression test asserts `assemble_coaching_context()` reproduces the current MCP
  output byte-for-byte, so the extraction is provably faithful.
- **Coaching runs from the terminal** — `fit coach`, no Claude client required (just the `claude`
  CLI, already installed).
- **No schema/DB change, no MCP re-registration** — coaching.json stays a sidecar; the 6 data tools
  and the `.mcp.json` path are untouched.
- **Code**: new `fit/coaching/` package; `fit/cli.py` (`fit coach`); `mcp/server.py` (retire
  coaching, fix the dead tool); `.claude/skills/fit-coach/SKILL.md` → stub; `cards.py`; docs.
- **Specs**: `coaching-signals` (ADD the `fit coach` requirement); `mcp-server` (MODIFY the coaching
  requirement — `check_dashboard_freshness` stays as a data tool, coaching moves to the CLI).

Affected capabilities: **coaching-signals** (+ a **mcp-server** trim). Composes with the holistic CLI
tidy (`tidy-cli-surface`), which ships after this.
