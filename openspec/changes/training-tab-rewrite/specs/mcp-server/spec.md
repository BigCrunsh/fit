## MODIFIED Requirements

### Requirement: Coaching workflow split into 3 MCP tools
The coaching workflow SHALL be split into 3 separate MCP tools with clear responsibilities:

**`check_dashboard_freshness()`** — returns last sync date, last report date, and coaching age. Coaching freshness SHALL be evaluated on a **weekly cadence**: coaching is fresh if `report_date` is within the last 7 days, stale if older than 7 days. The comparison against last sync date is removed — syncs do not invalidate coaching notes. This reflects the coaching model: Claude conversations are on-demand (pre-run, post-run, ad-hoc), but coaching notes are a weekly review artifact.

**`get_coaching_context()`** — unchanged. Returns structured data summary for Claude to reason about. The partial-week ACWR flag SHALL be removed (replaced by rolling 7-day window from the `rolling-window` capability — ACWR is always based on a full 7-day window).

**`save_coaching_notes(insights_json)`** — unchanged. Accepts insights JSON and writes to `reports/coaching.json`.

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
