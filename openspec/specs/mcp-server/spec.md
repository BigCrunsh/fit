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

**`check_dashboard_freshness()`** — returns last sync date, last report date, and coaching age. Coaching freshness SHALL be evaluated on a **weekly cadence**: coaching is fresh if `report_date` is within the last 7 days, stale if older than 7 days. The comparison against last sync date is removed — syncs do not invalidate coaching notes. This reflects the coaching model: Claude conversations are on-demand (pre-run, post-run, ad-hoc), but coaching notes are a weekly review artifact.

**`get_coaching_context()`** — queries the DB and returns a structured data summary for Claude to reason about: ACWR + safety status, calibration staleness, data source health, active phase targets vs actuals (compliance), zone distribution by time, run type breakdown, speed_per_bpm trends, cadence trends, RPE predicted vs actual patterns, sleep quality mismatches, race predictions, consistency streak. Does NOT generate insights — Claude does the analysis after reading this context. The partial-week ACWR flag SHALL be removed (replaced by rolling 7-day window from the `rolling-window` capability — ACWR is always based on a full 7-day window).

**`save_coaching_notes(insights_json)`** — accepts a JSON string of insights and writes to `reports/coaching.json`. JSON format: `{"generated_at": "ISO8601", "report_date": "YYYY-MM-DD", "insights": [{"type": "warning|critical|positive|info|target", "title": "...", "body": "..."}]}`. Writes atomically (write to temp file, then rename). This is the only tool with a filesystem side effect.

#### Scenario: Full coaching workflow in Claude Chat
- **WHEN** user asks Claude Chat for coaching analysis
- **THEN** Claude calls `check_dashboard_freshness()`, then `get_coaching_context()`, reasons about the data, optionally calls `execute_sql_query()` for deeper investigation, then calls `save_coaching_notes()` with its analysis

#### Scenario: Freshness check reflects weekly cadence
- **WHEN** Claude calls `check_dashboard_freshness()` and coaching notes are 3 days old but 2 syncs have occurred since
- **THEN** response reports coaching as "fresh (3 days ago)" — NOT stale

#### Scenario: Stale coaching prompts weekly review
- **WHEN** Claude calls `check_dashboard_freshness()` and coaching notes are 9 days old
- **THEN** response reports coaching as "stale (9 days ago — weekly review recommended)"

#### Scenario: No partial-week ACWR flag
- **WHEN** Claude calls `get_coaching_context()` on a Tuesday
- **THEN** ACWR is computed from the rolling 7-day window and reported without a "partial week" caveat

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

### Requirement: Coaching context includes correlations and alerts
The `get_coaching_context()` tool SHALL include 5 sections: (1) **Profile** — zone boundaries from config (both max_hr and LTHR models), calibration staleness, explicit Z2 ceiling so Claude never defaults to incorrect thresholds, (2) **Health** — ACWR with safety classification (safe/caution/danger using config thresholds), 7-day avg RHR/sleep/HRV/readiness, consistency streak, (3) **Training** — 4-week zone distribution, active training phase with targets, run type breakdown (4 weeks), speed_per_bpm trend with 4-week vs previous-4-week delta, (4) **Correlations** — top 5 computed correlations by absolute Spearman r with sample size and confidence, plus up to 3 recent unacknowledged alerts, (5) **Goals** — active goals with target dates.

#### Scenario: Coaching context with correlations
- **WHEN** Claude calls `get_coaching_context()` and correlations have been computed
- **THEN** the returned context includes top correlations sorted by |r| with format "metric_pair r=+0.35 (n=42, high)"

#### Scenario: Coaching context with active alerts
- **WHEN** Claude calls `get_coaching_context()` and 2 alerts fired this week
- **THEN** the returned context includes "Active alerts (2): [first 80 chars of each message]"

#### Scenario: Coaching context zone boundary emphasis
- **WHEN** Claude calls `get_coaching_context()`
- **THEN** the context explicitly states "IMPORTANT: Easy runs must stay below {Z2_ceiling} bpm (Z2 ceiling), NOT 150 bpm"

### Requirement: Save coaching notes validates insight body content
`save_coaching_notes()` SHALL validate that every insight has a `body` field with at least 20 characters. Insights with missing or too-short body text are rejected with a descriptive error explaining that each insight must contain full analysis paragraphs with specific numbers and actionable recommendations, not just titles.

#### Scenario: Insight with empty body rejected
- **WHEN** Claude calls `save_coaching_notes()` with an insight that has a title but no body
- **THEN** the tool returns an error listing the invalid insight and explaining the body requirement

## Post-Phase 2 Additions

### Requirement: get_coaching_context() includes today's run and plan
`get_coaching_context()` SHALL include: (1) today's completed run (if any) with distance, pace, HR, zone, run_type, (2) the full week's plan (next 10 days of planned_workouts), (3) previous coaching summary (titles from last session's coaching.json for continuity). The partial-week ACWR flag is removed — ACWR uses a rolling 7-day window and is always based on complete data.

#### Scenario: Today's run included
- **WHEN** Claude calls `get_coaching_context()` and a run was completed today
- **THEN** context includes today's run details (distance, pace, HR, zone, run_type)

#### Scenario: Plan included
- **WHEN** Claude calls `get_coaching_context()` and planned_workouts exist for next 10 days
- **THEN** context includes each planned workout (date, type, target distance, target zone)

#### Scenario: Previous coaching summary
- **WHEN** coaching.json exists from a prior session
- **THEN** context includes: "Previous coaching (Apr 5): [insight titles from last session]"

### Requirement: save_coaching_notes() archives previous notes
`save_coaching_notes()` SHALL archive the previous coaching.json to `coaching_history.json` (append) before overwriting with new notes. This preserves coaching history for trend analysis.

#### Scenario: Previous notes archived
- **WHEN** Claude calls `save_coaching_notes()` and coaching.json already exists
- **THEN** existing coaching.json content is appended to coaching_history.json, then coaching.json is overwritten with new notes

#### Scenario: First coaching session
- **WHEN** Claude calls `save_coaching_notes()` and no coaching.json exists
- **THEN** coaching.json is created directly, no archival needed

### Requirement: Plan adherence in coaching context
`get_coaching_context()` SHALL include plan adherence data: weekly compliance percentage, list of missed workouts (date + type), intensity override pattern (% of easy runs executed too hard), and readiness-based recommendation for today's planned workout.

#### Scenario: Plan adherence summary
- **WHEN** Claude calls `get_coaching_context()` and planned_workouts + activities exist
- **THEN** context includes: "Plan adherence: 75% compliance, 1 missed (Tue tempo), 40% intensity override on easy runs"

#### Scenario: Readiness recommendation
- **WHEN** readiness=35 and today's plan is Intervals
- **THEN** context includes: "Readiness gate: 35 < 40 threshold. Recommend swapping Intervals to easy Dauerlauf"
