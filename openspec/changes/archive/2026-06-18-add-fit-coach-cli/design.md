# Design — add-fit-coach-cli

## Context

`fit coach` shells out to the **Claude Code CLI** (`~/.local/bin/claude`, v2.x — the interactive CLI
in headless `-p` mode, NOT a pip SDK). The coaching context is pre-assembled as text and passed in;
the reasoning instructions go in via `--append-system-prompt`; the result is parsed and saved to the
existing `reports/coaching.json` sidecar. The MCP keeps only its 6 read-only data tools.

## The shared core (`fit/coaching/`)

- **`context.py`** — `assemble_coaching_context(conn) -> str`: the `_ctx_profile/_ctx_health/
  _ctx_training/_ctx_correlations/_ctx_goals/_ctx_forecast/_ctx_plan/_ctx_previous_coaching`
  builders lifted verbatim from `mcp/server.py`, producing the same text `get_coaching_context`
  produces today. A regression test pins the output to the legacy MCP output on a fixture DB.
- **`prompt.py`** — `COACHING_INSTRUCTIONS`: the SKILL.md reasoning (Steps 1–5: triage hierarchy,
  zone-ceiling-from-config rule, forecast interpretation, severity calibration, the insights JSON
  shape). Step 0 (the MCP preflight) is dropped as obsolete.
- **`save.py`** — `save_coaching_notes(reports_dir, insights_json) -> str`: moved verbatim from the
  MCP (validation: type ∈ {warning,critical,positive,info,target}, title/body present, body ≥ 20
  chars; archives the prior `coaching.json` → `coaching_history.json`; atomic temp-write + rename).
- **`runner.py`** — `run_coach(conn, reports_dir, *, save, days, model, timeout) -> dict`: assemble
  → invoke claude → parse → (optionally) persist. The only piece with a subprocess + the only new
  logic.

## Invocation

```
claude -p --append-system-prompt <COACHING_INSTRUCTIONS> --output-format json <context_text>
```
`claude -p --output-format json` returns a result envelope (JSON object with the assistant's final
text under a `result` field). The runner: extracts that text → parses the embedded insights JSON
array → validates → saves. `--append-system-prompt` keeps the stable ~165-line reasoning out of the
dynamic user turn (the context). The MCP is **not** wired in via `--mcp-config`: the context is
pre-assembled (one-shot, deterministic, fast); free-form exploration stays in Desktop with the data
tools.

## Decisions

### Decision 1 — pre-assembled text, not live MCP tool-calling
The coach hands claude a complete context string, not DB access. Deterministic, fast, testable, and
it means `fit coach` has no dependency on the MCP being registered. **Anti-recommendation: pass
`--mcp-config` so claude queries live** — rejected: non-deterministic, slower, couples the command to
MCP registration, and the existing context already contains what the SKILL reasons over.

### Decision 2 — batch-then-print (not streaming) for v1
`--output-format json` and parse once. **Anti-recommendation: `stream-json`** — deferred: streaming
adds envelope-parsing complexity for a command that runs in seconds; revisit if latency annoys.

### Decision 3 — fail closed; never corrupt coaching.json
Every failure (binary missing, nonzero exit, auth/network, timeout, unparseable/short insights)
prints an actionable message and **writes nothing**. The save validation is reused, so a malformed
model response is rejected exactly as the MCP rejected it. Tested with a mocked subprocess at a 2:1
unhappy:happy ratio, asserting no write on every failure path.

### Decision 4 — coaching context window stays "all available" (dashboard parity)
`--days` exists but defaults to the current MCP behaviour (no day cap) so the coaching context equals
what the dashboard reasons over. Introducing a default cap would be a silent behaviour change.

### Decision 5 — MCP sheds coaching entirely (no thin wrapper)
Coaching notes come only from `fit coach`. `save_coaching_notes` and `get_coaching_context` are
removed from the MCP; the dead `_ctx_forecast` decorator is removed (bug fix). The 6 data tools and
the `.mcp.json` path are untouched → no Desktop re-registration. The only behaviour a Desktop user
could notice is the removed note-writer, covered by the SKILL.md redirect stub.

## Migration

1. Extract `context.py` + the SSOT regression test FIRST (prove the extraction is faithful before
   touching the MCP).
2. Move `save.py`; capture `prompt.py`; implement `runner.py` (mocked-subprocess tests).
3. Add `fit coach`; retire MCP coaching + fix the dead tool; SKILL.md → stub; update cards.py + docs.
4. Validate: `fit coach --no-save` against the real claude CLI; confirm coaching.json schema
   unchanged on a real save. Archive.

## Risks

- **claude CLI envelope shape.** `-p --output-format json` field names are read from `claude --help`
  / a live probe, not assumed; the runner tolerates the assistant text being the whole stdout if the
  envelope is absent. A parse failure fails closed (writes nothing).
- **claude not installed / not authed at runtime.** Resolve order: `config profile.claude_bin` →
  `shutil.which('claude')` → `~/.local/bin/claude`; a clear actionable error if none (naming the
  Claude Code CLI, not a pip package).
- **SSOT drift over time.** The byte-for-byte test guards the extraction now; `tidy-cli-surface` adds
  an optional `fit doctor` check that re-asserts it.
