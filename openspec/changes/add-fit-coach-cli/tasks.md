# Tasks — add-fit-coach-cli

## 1. Shared core: context extraction (do FIRST — prove faithfulness)
- [x] `fit/coaching/__init__.py`
- [x] `fit/coaching/context.py`: move `_ctx_*` builders + `get_coaching_context` body from `mcp/server.py` → `assemble_coaching_context(conn) -> str` (verbatim output)
- [x] SSOT regression test: `assemble_coaching_context(conn)` output == the legacy MCP output on a fixture DB

## 2. Shared core: save + prompt
- [x] `fit/coaching/save.py`: move `save_coaching_notes` verbatim (validation + `coaching_history.json` archival + atomic temp-write/rename); takes the reports dir
- [x] `fit/coaching/prompt.py`: `COACHING_INSTRUCTIONS` = SKILL.md Steps 1–5 (drop Step 0 MCP preflight)

## 3. Runner (the only new logic)
- [x] `fit/coaching/runner.py`: `run_coach(conn, reports_dir, *, save, days, model, timeout)` — assemble → resolve claude bin (config `profile.claude_bin` → `which` → `~/.local/bin/claude`) → `subprocess.run([claude,'-p','--append-system-prompt',INSTRUCTIONS,'--output-format','json', context], capture_output=True, text=True, timeout=…)` → extract result text → parse insights JSON → validate → (save unless --no-save)
- [x] Fail closed: binary-missing / nonzero-exit / auth / timeout / unparseable / short-body → actionable message, **write nothing**
- [x] Tests (mocked subprocess, 2:1 unhappy:happy): happy save; --no-save; claude-missing; nonzero exit; bad JSON; short-body rejection; timeout; assert no coaching.json write on every failure

## 4. `fit coach` command
- [x] `fit coach` (top-level) wiring the runner; flags `--no-save`, `--json` (print envelope, implies --no-save), `--days N`, `--model NAME`, `--timeout S`, `--force` (skip freshness gate), `--verbose`
- [x] After save: suggest `fit report`; if `check_dashboard_freshness` flags stale data and not --force, warn + suggest `fit sync`

## 5. MCP cleanup (retire coaching, keep the 6 data tools)
- [x] Remove the stray `@mcp.tool()` on `_ctx_forecast` (dead — `conn` not JSON-callable)
- [x] Remove `save_coaching_notes` and `get_coaching_context` from `mcp/server.py` (or have the MCP import nothing coaching); the `_ctx_*`/assembly now live in `fit/coaching` (MCP imports if still referenced, else gone)
- [x] Keep the 6 data tools + the `.mcp.json` path unchanged (no re-registration); update the MCP server instruction text (drop the coaching workflow)

## 6. Skill stub + UI + docs
- [x] `.claude/skills/fit-coach/SKILL.md` → one-screen redirect stub ("coaching moved to `fit coach`; the MCP now serves the 6 data tools")
- [x] `cards.py` coaching-stale attention item: command `/fit-coach` → `fit coach` (+ detail text)
- [x] CLAUDE.md: quick-commands (`fit coach`); rewrite the MCP↔skill SSOT note → "coaching prompt + context live in `fit/coaching/`, CLI-owned"; `DATA_LINEAGE.md` coaching row

## 7. Specs + validate + archive
- [x] `coaching-signals` spec delta: ADD the `fit coach` requirement
- [x] `mcp-server` spec delta: MODIFY "Coaching workflow via 3 focused tools" → `check_dashboard_freshness` stays as a data-freshness tool; coaching context-assembly + notes-writing move to the `fit coach` CLI
- [x] `openspec validate add-fit-coach-cli --strict`; full test suite; `fit coach --no-save` smoke against the real claude CLI
- [x] archive
