## 1. Foundation & Tech Debt

- [x] 1.1 Fix `db.py` `executescript` auto-commit — parse SQL into individual statements, execute each with `conn.execute()` inside explicit transaction (phase-2-enrich 1.1)
- [x] 1.2 Add shared retry/backoff utility in `fit/garmin.py` — `_request_with_retry(func, max_retries=3)` handling 429 countdown, 401 re-auth prompt, 5xx exponential backoff (merges phase-1-gaps 1.1 auth handling + phase-2-enrich 1.2 retry utility)
- [x] 1.3 Add user-friendly auth error in `garmin.py` — catch garth auth failures, show exact re-auth command (merges phase-1-gaps 1.1 + phase-2-enrich 2.3)
- [x] 1.4 Design MCP response schema for Phase 2 additions upfront — correlations, plan adherence, splits in coaching context (phase-2-enrich 1.5)
- [x] 1.5 Refactor `get_coaching_context()` into composable sections: `_ctx_health()`, `_ctx_training()`, `_ctx_correlations()`, `_ctx_plan()`, `_ctx_splits()`, `_ctx_goals()` (phase-2-enrich 1.3, enables dashboard fixes)
- [ ] 1.6 Test: migration runner transaction safety verified, retry works on mock 429 (phase-2-enrich 1.6)

## 2. Sync & Data Pipeline

- [x] 2.1 Expand activity type fetch list — add "strength_training", "elliptical", "yoga" or use a catch-all approach (phase-1-gaps 1.2)
- [x] 2.2 Extract actual start hour from activity `startTimeLocal` in `garmin.py` and pass to hourly weather instead of hardcoded hour=8 (phase-1-gaps 1.3)
- [x] 2.3 LTHR auto-extraction: when a race candidate is detected in sync, prompt user or auto-save with method='race_extract', confidence='medium' (phase-1-gaps 1.4)
- [x] 2.4 Add non-running guard to `compute_speed_per_bpm` — return None if activity type is not running (phase-1-gaps 1.5)
- [x] 2.5 ACWR: require minimum 3 prior weeks (not 2) for computation, return None otherwise (phase-1-gaps 1.6)
- [x] 2.6 Replace print statements with Rich Progress bars — per-step tasks with item counts, suppress console logging during progress (phase-2-enrich 2.1)
- [x] 2.7 Add ETA display for `fit sync --full` based on date range and API response rate (phase-2-enrich 2.2)
- [x] 2.8 Test: progress bars render cleanly, no log interleave (phase-2-enrich 2.4)

## 3. MCP Server

- [x] 3.1 Add DB existence check in MCP server startup — return "fitness.db not found. Run `fit sync` first." instead of raw OperationalError (phase-1-gaps 3.1)
- [x] 3.2 Add LTHR detection source check to `data_health.py` (phase-1-gaps 3.2)
- [x] 3.3 Add automated goal creation logging — when goals are inserted via seed scripts, log to goal_log (phase-1-gaps 3.3)

## 4. fit status & CLI

- [x] 4.1 Wire `get_calibration_status()` into `fit status` — show max_hr, lthr, weight staleness + retest prompts (phase-1-gaps 2.1)
- [x] 4.2 Wire `check_data_sources()` into `fit status` — show active/stale/missing per source (phase-1-gaps 2.2)
- [x] 4.3 Show active training phase with compliance summary in `fit status` (phase-1-gaps 2.3)
- [x] 4.4 Show ACWR (with safety indicator) and consistency streak in `fit status` (phase-1-gaps 2.4)

## 5. Dashboard — Charts & Annotations

- [ ] 5.1 Implement or remove dashboard zoom toggle — currently no-op at line 270 of dashboard.html (merges phase-1-gaps dashboard scope + phase-2-enrich 1.4)
- [ ] 5.2 Inline or remove Google Fonts @import — vendor fonts or use system fallback for offline support (phase-1-gaps 4.1)
- [ ] 5.3 Add run type breakdown stacked chart to Training tab — easy/long/tempo/intervals/recovery per week, intensity palette (phase-1-gaps 4.2)
- [ ] 5.4 Extend event annotations to all time-series charts — weight, cadence, volume, not just efficiency + VO2 (phase-1-gaps 4.3)
- [ ] 5.5 Add calibration change and goal milestone events to `_get_event_annotations()` (phase-1-gaps 4.4)
- [ ] 5.6 Zone distribution chart: overlay active phase z12_pct_target and z45_pct_target as reference lines (phase-1-gaps 4.6)
- [ ] 5.7 Journey timeline: add current vs target metrics below each phase segment (phase-1-gaps 4.7)
- [ ] 5.8 Sleep chart: add average annotation lines for total sleep and deep sleep (phase-1-gaps 4.8)
- [ ] 5.9 Weight chart: add race target reference line from goals table and event annotations (phase-1-gaps 4.9)

## 6. Dashboard — Status Cards & Headlines

- [ ] 6.1 Status cards: add VO2max peak reference + 4-week delta, weight race target + 4-week delta, sleep card REM hours (phase-1-gaps 4.5)
- [ ] 6.2 Headline engine: check sleep_quality='Poor' as recovery trigger alongside readiness < 50 (phase-1-gaps 4.10)
- [ ] 6.3 Week-over-week card: detect incomplete current week (today != Sunday), label "Week in progress" (phase-1-gaps 4.11)
- [ ] 6.4 Race prediction: add confidence explanation and note about post-gap fitness adjustment (phase-1-gaps 4.12)
- [ ] 6.5 Metric definitions: make remaining generic definitions contextual — sleep, stress, cadence reference actual values (phase-1-gaps 4.13)

## 7. Correlation Engine

- [ ] 7.1 Add migration 005: `correlations` table + `alerts` table (phase-2-enrich 3.1)
- [ ] 7.2 Implement `fit/correlations.py` — Spearman rank via rank transform + numpy.corrcoef, predefined pairs with lag, differencing for trended metrics, min n=20/30 thresholds (phase-2-enrich 3.2)
- [ ] 7.3 Implement `fit/alerts.py` — threshold rules engine: all-runs-too-hard, volume ramp guard, readiness gate, long run projection, alcohol+HRV drop (phase-2-enrich 3.3)
- [ ] 7.4 Implement `fit correlate` CLI — compute all correlations, skip unchanged pairs, display ranked table, auto-run at end of `fit sync` (phase-2-enrich 3.4)
- [ ] 7.5 Add correlation panel to Coach tab — diverging bar chart, scatter drill-down, before/after bars, freshness indicator (phase-2-enrich 3.5)
- [ ] 7.6 Add alert output to Today tab headline and coaching context (phase-2-enrich 3.6)
- [ ] 7.7 Test: Spearman on ordinal data, differencing, minimum sample sizes, alert rules, dashboard rendering (phase-2-enrich 3.7)

## 8. Fitdays Auto-Import

- [ ] 8.1 Add `sync.weight_csv_path` config field — explicit path, not ~/Downloads/ scanning (phase-2-enrich 4.1)
- [ ] 8.2 Add migration 005 (extend): `import_log` table (phase-2-enrich 4.2)
- [ ] 8.3 Implement auto-import in `fit sync` — check configured path, validate CSV header, import new dates only, log to import_log, auto-update weight calibration (phase-2-enrich 4.3)
- [ ] 8.4 Investigate Fitdays API for direct integration — spike, document findings (phase-2-enrich 4.4)
- [ ] 8.5 Test: auto-detect, duplicate prevention via hash, calibration refresh, wrong CSV format error (phase-2-enrich 4.5)

## 9. Individual Goal Tracking

- [ ] 9.1 Implement `fit goal add` — interactive CLI: name, type (race/metric/habit), target_value, target_unit, target_date (phase-2-enrich 5.1)
- [ ] 9.2 Implement `fit goal list` — show all active goals with current progress (phase-2-enrich 5.2)
- [ ] 9.3 Implement `fit goal complete <id>` — mark as achieved, log to goal_log (phase-2-enrich 5.3)
- [ ] 9.4 Add goal progress to Today tab — progress bars/values for each active goal (phase-2-enrich 5.4)
- [ ] 9.5 Add goal progress to `fit status` output (phase-2-enrich 5.5)
- [ ] 9.6 Test: goal CRUD, progress computation for race/metric/habit types (phase-2-enrich 5.6)

## 10. fit doctor & Documentation

- [ ] 10.1 Implement `fit doctor` — validate schema version, all tables exist, no orphaned data, correlation freshness, plan import recency, weight staleness, calibration status, data source health (phase-2-enrich 6.1)
- [ ] 10.2 Test: all-healthy scenario, various failure scenarios (phase-2-enrich 6.2)
- [ ] 10.3 Update spec: document that env vars are placeholder-substitution, not general key override — this is by-design (phase-1-gaps 5.1)
- [ ] 10.4 Note in CLAUDE.md: logging uses single sync.log, design says per-module but implementation uses one file (phase-1-gaps 5.2)
