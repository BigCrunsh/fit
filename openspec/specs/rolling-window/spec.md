# rolling-window

## Purpose

Define how the dashboard, CLI, alerts, and coaching context use a rolling 7-day window (today minus 6 days through today) as the primary "week" concept, replacing ISO-week boundaries (Monday–Sunday) for "current week" metrics. The `weekly_agg` table remains the materialization layer for historical trends and ISO-week-aligned charts; rolling 7-day data is computed on-demand from raw `activities` via `compute_rolling_week()`.

## Requirements

### Requirement: Rolling 7-day window as the primary "week" concept
All dashboard sections, CLI output, alerts, and coaching context that reference "last 7 days" or "weekly" metrics SHALL use a rolling 7-day window (today minus 6 days through today) instead of ISO week boundaries (Monday-Sunday). Metrics and alerts SHALL NOT depend on a specific cutoff day. The rolling window ensures that: (1) Monday is not a dead dashboard — weekend training carries forward, (2) mid-week comparisons are always apples-to-apples, (3) no partial-week guards are needed in alert logic.

#### Scenario: Monday dashboard is not empty
- **WHEN** today is Monday and the runner did a long run Saturday and easy run Sunday
- **THEN** "last 7 days" metrics include both runs (they fall within the 7-day window)

#### Scenario: No day-of-week dependency
- **WHEN** the same data is viewed on Tuesday vs Thursday
- **THEN** the only difference is the 7-day window shifting by 2 days — no structural change in what is shown or how alerts fire

#### Scenario: WoW comparison is symmetric
- **WHEN** rolling 7d volume is compared to prior 7d (days -13 to -7)
- **THEN** both windows are exactly 7 days, always comparable regardless of what day it is

### Requirement: Rolling window for dashboard charts
The Volume Trend chart (which absorbs the Run Type Mix as a stacked-by-run-type breakdown) is the one chart exception to the rolling-window principle: it remains ISO-week aligned because per-run-type aggregation across overlapping rolling windows is expensive and offers little visual benefit. Chart x-axis labels SHALL show the ISO week's Sunday date (e.g., "Apr 12") rather than ISO week labels (e.g., "W15"). All non-chart "current week" surfaces (hero card, objectives, alerts, CLI, MCP) still use the rolling 7-day window — only the chart bins remain calendar-aligned.

#### Scenario: Volume chart bins are ISO-week aligned
- **WHEN** the Volume Trend chart renders on a Wednesday
- **THEN** each bar represents an ISO week (Mon-Sun); the current week's bar shows partial data (Mon-Wed) — the hero card above already shows the rolling 7-day total for "now" purposes

#### Scenario: X-axis labels are ISO dates, not week strings
- **WHEN** the Volume Trend chart renders
- **THEN** x-axis labels show the Sunday end date of each ISO week (e.g., "Apr 12"), not "W15"

### Requirement: Rolling window for CLI output
The `fit status` command SHALL display "Last 7 days" metrics (volume, run count, ACWR, zone distribution) using the rolling window. The label SHALL say "Last 7 days" not "Last 7 days". The `fit plan` command SHALL continue to show calendar-week aligned plan data since training plans are authored per calendar week.

#### Scenario: fit status on Monday
- **WHEN** `fit status` is run on Monday morning
- **THEN** the output shows metrics from the prior Tuesday through Monday, including weekend runs

#### Scenario: fit plan stays calendar-aligned
- **WHEN** `fit plan` shows upcoming workouts
- **THEN** workouts are grouped by their planned calendar week (Mon-Sun), matching how coaches author plans

### Requirement: Rolling window for alerts
Alert thresholds SHALL evaluate against rolling 7-day windows. The partial-week suppression logic (currently: "don't fire ACWR undertraining alert before Thursday") SHALL be removed. Alerts fire whenever the rolling window data meets the threshold, regardless of day of week.

#### Scenario: ACWR alert fires on Tuesday
- **WHEN** the rolling 7-day ACWR exceeds 1.5 on a Tuesday
- **THEN** the alert fires immediately — no waiting until Thursday/Friday

#### Scenario: No false undertraining on Monday
- **WHEN** today is Monday and the rolling 7-day window includes a full training week
- **THEN** undertraining alert evaluates against 7 days of data, not a "partial" 1-day window

### Requirement: Rolling window for coaching context (MCP)
The MCP coaching tools SHALL report "last 7 days" metrics using the rolling window. The current partial-week detection logic in `mcp/server.py` SHALL be removed. Coaching insights about training load, zone compliance, and volume SHALL always reflect the most recent 7 days.

#### Scenario: Coaching query on any day
- **WHEN** Claude asks for coaching context via MCP on a Wednesday
- **THEN** the response includes rolling 7-day volume, zone distribution, and ACWR — no "week in progress" caveats

### Requirement: weekly_agg as materialization layer, not source of truth
The `weekly_agg` table SHALL continue to exist and be populated by ISO week for historical trend queries (Volume Trend chart with 12+ weeks, ACWR history, streak computation). However, all "current week" or "last 7 days" queries SHALL compute from raw `activities` data using the rolling 7-day window, NOT read from `weekly_agg`. A new function `compute_rolling_week(conn, end_date=None, window_days=7)` SHALL query activities directly and return the same metric structure as a `weekly_agg` row.

#### Scenario: Current metrics from activities, not weekly_agg
- **WHEN** the hero card needs "last 7 days" volume and zone distribution
- **THEN** it calls `compute_rolling_week()` which queries `activities` for the last 7 days, not `weekly_agg` for the current ISO week

#### Scenario: Historical trends still use weekly_agg
- **WHEN** consumers need historical weekly trends (e.g., ACWR chronic baseline, weekly_agg-backed reports)
- **THEN** they read from `weekly_agg` for past ISO weeks (materialized, fast). The Volume Trend chart queries `activities` directly grouped by ISO week (equivalent result for completed weeks), and the current ISO week bar shows partial data — "now" totals are surfaced separately by the hero card via `compute_rolling_week()`

#### Scenario: weekly_agg still populated on sync
- **WHEN** `fit sync` runs
- **THEN** `compute_weekly_agg()` still materializes ISO week rows into `weekly_agg` for historical queries — no schema change needed

### Requirement: Plan adherence stays calendar-week aligned
Plan adherence (`compute_plan_adherence()`) SHALL continue to use calendar weeks (Monday-Sunday) because training plans are authored and assigned per calendar week. This is the one exception to the rolling-window principle — plan compliance is measured against the plan's own structure, not a sliding window.

#### Scenario: Plan adherence uses calendar week
- **WHEN** the plan adherence section shows 4 weeks of compliance
- **THEN** each row corresponds to an ISO week (W12, W13, W14, W15) matching how the plan was authored

#### Scenario: Hero card vs plan adherence use different windows
- **WHEN** today is Wednesday and the hero card shows rolling 7d volume of 25km
- **THEN** the plan adherence section shows the current calendar week (Mon-Wed so far) as "in progress" — these are intentionally different windows for different purposes
