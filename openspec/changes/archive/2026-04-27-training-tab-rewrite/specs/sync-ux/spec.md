## MODIFIED Requirements

### Requirement: Sync pipeline decomposition
`run_sync()` SHALL be decomposed into composable pipeline stages: fetch, enrich, store, weather, aggregate, correlate, alert, plan_sync. Each stage is independently testable. New stages (Phase 2b .fit downloads, Phase 2c plan sync) plug in without increasing blast radius of existing stages. The aggregate stage SHALL continue to materialize `weekly_agg` rows by ISO week for historical queries. A new `compute_rolling_week(conn, end_date=None, window_days=7)` function SHALL be added to `analysis.py` to compute the same metric structure (run_km, run_count, z12_pct, z45_pct, ACWR) from raw `activities` data for any arbitrary 7-day window. All "current week" consumers (dashboard hero card, alerts, CLI status, MCP coaching) SHALL call `compute_rolling_week()` instead of reading the current ISO week from `weekly_agg`.

#### Scenario: Single stage failure
- **WHEN** weather fetch fails
- **THEN** other stages complete normally, weather failure logged as warning

#### Scenario: Rolling week query
- **WHEN** the dashboard hero card needs current-week metrics on a Wednesday
- **THEN** it calls `compute_rolling_week(conn)` which queries `activities` for the last 7 days and returns volume, run count, zone distribution, and ACWR — not `weekly_agg` for the current ISO week

#### Scenario: Historical queries still use weekly_agg
- **WHEN** consumers need historical weekly trends (e.g., ACWR chronic baseline)
- **THEN** they read completed ISO weeks from `weekly_agg` (fast, pre-materialized). The Volume Trend chart aggregates ISO-week-grouped totals from `activities` directly; "now" totals are surfaced by the hero card via `compute_rolling_week()`

### Requirement: Bug fixes
The sync pipeline SHALL include the following correctness fixes:
- ACWR year-boundary: ISO week 53 handling (prev_week += 52 wrong for 53-week years). Use `datetime.date.fromisocalendar()` for correct week arithmetic.
- Alert SQL: `all_runs_too_hard` query `WHERE >= MAX()` returns only 1 week. Fix to actually average 2 weeks.
- SpO2 threshold: change from <93% to <95% for sea-level. Make configurable via config.yaml.
- **Alert partial-week suppression removed**: The `iso.weekday < 5` guard in `alerts.py` that suppresses ACWR undertraining alerts before Thursday SHALL be removed. Alerts SHALL evaluate against the rolling 7-day window, firing whenever the threshold is met regardless of day of week.

#### Scenario: Week 53 ACWR
- **WHEN** current week is 2027-W01 and computing ACWR with 4 prior weeks
- **THEN** correctly references 2026-W52, 2026-W51, 2026-W50, 2026-W49 (not 2026-W00)

#### Scenario: ACWR undertraining alert on Tuesday
- **WHEN** rolling 7-day ACWR is 0.4 on a Tuesday
- **THEN** the undertraining alert fires immediately — no suppression until Thursday
