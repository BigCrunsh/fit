## MODIFIED Requirements

### Requirement: Coaching workflow via 3 focused tools
The MCP server SHALL expose **`check_dashboard_freshness()`** as a read-only data-freshness tool —
returns last sync date, last report date, and coaching age, evaluated on a **weekly cadence**
(coaching is fresh if `report_date` is within the last 7 days, stale if older). It does NOT compare
against last sync date (syncs do not invalidate coaching notes).

The MCP server SHALL NOT own the coaching workflow. Coaching-context assembly and coaching-note
writing are no longer MCP responsibilities: they move to the `fit coach` CLI and the shared
`fit/coaching/` core (see the `coaching-signals` capability). The MCP therefore exposes only its
read-only data tools (`execute_sql_query`, `get_health_summary`, `get_run_context`,
`explore_database_structure`, `get_table_details`, `check_dashboard_freshness`) for free-form
exploration; it no longer registers `get_coaching_context` or `save_coaching_notes`.

#### Scenario: Freshness check reflects weekly cadence
- **WHEN** Claude calls `check_dashboard_freshness()` and coaching notes are 3 days old but 2 syncs have occurred since
- **THEN** response reports coaching as "fresh (3 days ago)" — NOT stale

#### Scenario: Stale coaching prompts weekly review
- **WHEN** Claude calls `check_dashboard_freshness()` and coaching notes are 9 days old
- **THEN** response reports coaching as "stale (9 days ago — weekly review recommended)"

#### Scenario: The MCP no longer exposes coaching tools
- **WHEN** a Claude client lists the fit MCP tools
- **THEN** only the 6 read-only data tools are present; `get_coaching_context` and `save_coaching_notes` are absent (coaching is produced by `fit coach`)

## REMOVED Requirements

### Requirement: Coaching context includes correlations and alerts
**Reason**: The coaching-context assembly moves out of the MCP into `fit/coaching/context.py`, consumed by the `fit coach` CLI. The content (correlations + active alerts) is preserved there and is re-specified under the `coaching-signals` capability's `fit coach` requirement.
**Migration**: A regression test asserts `assemble_coaching_context()` reproduces the prior `get_coaching_context()` output byte-for-byte, so the relocated context is unchanged.

### Requirement: Save coaching notes validates insight body content
**Reason**: The notes writer (and its validation: type ∈ {warning,critical,positive,info,target}, title/body present, body ≥ 20 chars) moves to `fit/coaching/save.py`, called by `fit coach`. The MCP no longer writes coaching notes.
**Migration**: The validation logic is moved verbatim; `reports/coaching.json` format is unchanged.

### Requirement: get_coaching_context() includes today's run and plan
**Reason**: Moved into `fit/coaching/context.py` (today's run, the plan, previous-coaching continuity), consumed by `fit coach`.
**Migration**: Behaviour preserved verbatim; guarded by the byte-for-byte context regression test.

### Requirement: save_coaching_notes() archives previous notes
**Reason**: The archival (prior `coaching.json` → `coaching_history.json`) moves to `fit/coaching/save.py`.
**Migration**: Archival logic moved verbatim; behaviour unchanged.

### Requirement: Plan adherence in coaching context
**Reason**: Moved into `fit/coaching/context.py` (plan-adherence summary), consumed by `fit coach`.
**Migration**: Behaviour preserved verbatim; guarded by the context regression test.
