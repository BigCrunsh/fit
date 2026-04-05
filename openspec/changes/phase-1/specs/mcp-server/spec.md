## ADDED Requirements

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
The coaching workflow SHALL be split into 3 separate MCP tools with clear responsibilities:

**`check_dashboard_freshness()`** — returns last sync date, last report date, and last coaching date. Simple status check, no side effects.

**`get_coaching_context()`** — queries the DB and returns a structured data summary for Claude to reason about: ACWR + safety status, calibration staleness, data source health, active phase targets vs actuals (compliance), zone distribution by time, run type breakdown, speed_per_bpm trends, cadence trends, RPE predicted vs actual patterns, sleep quality mismatches, race predictions, consistency streak. Does NOT generate insights — Claude does the analysis after reading this context.

**`save_coaching_notes(insights_json)`** — accepts a JSON string of insights and writes to `reports/coaching.json`. JSON format: `{"generated_at": "ISO8601", "report_date": "YYYY-MM-DD", "insights": [{"type": "warning|critical|positive|info|target", "title": "...", "body": "..."}]}`. Writes atomically (write to temp file, then rename). This is the only tool with a filesystem side effect.

#### Scenario: Full coaching workflow in Claude Chat
- **WHEN** user asks Claude Chat for coaching analysis
- **THEN** Claude calls `check_dashboard_freshness()`, then `get_coaching_context()`, reasons about the data, optionally calls `execute_sql_query()` for deeper investigation, then calls `save_coaching_notes()` with its analysis

#### Scenario: Stale dashboard detected
- **WHEN** Claude calls `check_dashboard_freshness()` and report is older than last sync
- **THEN** Claude recommends running `fit report` first before generating coaching notes

#### Scenario: Coaching notes written atomically
- **WHEN** Claude calls `save_coaching_notes()` with valid JSON
- **THEN** `reports/coaching.json` is fully written (temp file + rename, not partial)

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
