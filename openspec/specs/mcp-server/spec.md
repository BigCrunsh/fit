# mcp-server Specification

## Purpose
TBD — normalized from archived change deltas; update Purpose.
## Requirements
### Requirement: MCP server exposes fitness.db to Claude
The MCP server (`mcp/server.py`) SHALL expose `fitness.db` as a set of tools accessible from Claude Chat and Claude Code. It SHALL use the MCP SDK and connect to the database at the path specified in config (`sync.db_path`). The server replaces the legacy `garmy-localdb` MCP server entirely.

#### Scenario: Server starts and connects to database
- **WHEN** the MCP server is started
- **THEN** it connects to `fitness.db` and registers all tools

#### Scenario: Database file does not exist
- **WHEN** the MCP server starts and `fitness.db` does not exist
- **THEN** the server reports a clear error with instructions to run `fit sync` first

### Requirement: SQL query tool for ad-hoc analysis
The server SHALL expose an `execute_sql_query(query)` tool that accepts SELECT statements and returns results. Only SELECT queries SHALL be allowed — INSERT, UPDATE, DELETE, DROP, and other mutating statements SHALL be rejected.

#### Scenario: Valid SELECT query
- **WHEN** Claude calls `execute_sql_query("SELECT date, avg_hr FROM activities WHERE type='running' ORDER BY date DESC LIMIT 5")`
- **THEN** the tool returns the 5 most recent running activities with date and avg_hr

#### Scenario: Mutating query is rejected
- **WHEN** Claude calls `execute_sql_query("DELETE FROM activities")`
- **THEN** the tool returns an error: "Only SELECT queries are allowed"

#### Scenario: Query with syntax error
- **WHEN** Claude calls `execute_sql_query("SELCT * FROM activities")`
- **THEN** the tool returns the SQLite error message

### Requirement: Health summary tool for quick overview
The server SHALL expose a `get_health_summary(days)` tool that returns a summary of recent health metrics: avg RHR, avg sleep, avg HRV, avg readiness, latest weight, and run count for the specified number of days.

#### Scenario: Health summary for last 7 days
- **WHEN** Claude calls `get_health_summary(7)`
- **THEN** the tool returns aggregated health metrics for the past 7 days

#### Scenario: No data for requested period
- **WHEN** Claude calls `get_health_summary(7)` and no data exists for the last 7 days
- **THEN** the tool returns a message indicating no data is available for the period

### Requirement: Run context tool for single-run analysis
The server SHALL expose a `get_run_context(date)` tool that returns the full `v_run_days` view row for a specific date, joining activity data with health, check-in, weather, and body composition data.

#### Scenario: Run context for a date with all data
- **WHEN** Claude calls `get_run_context("2026-04-01")` and a run exists on that date
- **THEN** the tool returns the complete joined row including pace, HR, sleep, hydration, weather, and weight

#### Scenario: No run on requested date
- **WHEN** Claude calls `get_run_context("2026-04-02")` and no running activity exists
- **THEN** the tool returns a message indicating no run was found for that date

#### Scenario: Multiple runs on same date
- **WHEN** Claude calls `get_run_context("2026-04-01")` and two runs exist
- **THEN** the tool returns all matching rows

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

### Requirement: Schema exploration tools
The server SHALL expose `explore_database_structure()` (lists all tables and views with row counts) and `get_table_details(table_name)` (returns column names, types, and sample data for a specific table).

#### Scenario: Explore database structure
- **WHEN** Claude calls `explore_database_structure()`
- **THEN** the tool returns a list of all tables and views with their row counts

#### Scenario: Get table details for activities
- **WHEN** Claude calls `get_table_details("activities")`
- **THEN** the tool returns column definitions and a few sample rows from the activities table

#### Scenario: Invalid table name
- **WHEN** Claude calls `get_table_details("nonexistent")`
- **THEN** the tool returns an error indicating the table does not exist

