# Phase 2a: Data Story + Quick Wins

## 1. Phase 1 Tech Debt

- [ ] 1.1 Fix `db.py` `executescript` auto-commit — parse SQL into individual statements, execute each with `conn.execute()` inside explicit transaction
- [ ] 1.2 Add shared retry/backoff utility in `fit/garmin.py` — `_request_with_retry(func, max_retries=3)` handling 429 (countdown), 401 (re-auth), 5xx (exponential backoff)
- [ ] 1.3 Refactor `get_coaching_context()` into composable sections: `_ctx_health()`, `_ctx_training()`, `_ctx_correlations()`, `_ctx_plan()`, `_ctx_splits()`, `_ctx_goals()`
- [ ] 1.4 Implement or remove dashboard zoom toggle (currently no-op at line 270 of dashboard.html)
- [ ] 1.5 Design MCP response schema for Phase 2 additions upfront (correlations, plan adherence, splits in coaching context)
- [ ] 1.6 Test: migration runner transaction safety verified, retry works on mock 429

## 2. Sync UX

- [ ] 2.1 Replace print statements with Rich Progress bars — per-step tasks with item counts, suppress console logging during progress
- [ ] 2.2 Add ETA display for `fit sync --full` based on date range and API response rate
- [ ] 2.3 Improve auth error message with exact re-auth command
- [ ] 2.4 Test: progress bars render cleanly, no log interleave

## 3. Correlation Engine

- [ ] 3.1 Add migration 005: `correlations` table (metric_pair, lag_days, spearman_r, pearson_r, p_value, sample_size, confidence, status, last_computed, data_count_at_compute) + `alerts` table (date, type, message, data_context JSON, acknowledged)
- [ ] 3.2 Implement `fit/correlations.py` — Spearman rank (via rank transform + numpy.corrcoef, no scipy). Predefined pairs: alcohol→HRV (lag 1), alcohol→RHR (lag 1), alcohol→sleep_quality (lag 0), sleep_duration+quality→HR-at-pace (lag 1), weight→RPE (weekly), temp→speed_per_bpm (lag 0), water→HRV (lag 1). Use differenced values for trended metrics. Min n=20 for reporting, n=30 for coaching.
- [ ] 3.3 Implement `fit/alerts.py` — threshold rules engine: all-runs-too-hard (Z2<50% 2wk), volume ramp guard, readiness gate, long run projection, alcohol+HRV drop. Runs after sync, stores in alerts table.
- [ ] 3.4 Implement `fit correlate` CLI — compute all correlations, skip unchanged pairs (data_count_at_compute), display ranked table. Also auto-run at end of `fit sync`.
- [ ] 3.5 Add correlation panel to Coach tab — diverging bar chart (plain language labels), scatter plot drill-down (progressive disclosure), before/after comparison bars, data freshness indicator
- [ ] 3.6 Add alert output to Today tab headline and coaching context
- [ ] 3.7 Test: Spearman on ordinal data, differencing, minimum sample sizes, alert rules, dashboard rendering

## 4. Fitdays Auto-Import

- [ ] 4.1 Add `sync.weight_csv_path` config field (explicit path, not ~/Downloads/ scanning)
- [ ] 4.2 Add migration 005 (extend): `import_log` table (filename, file_hash, row_count, rows_imported, import_timestamp, source_type)
- [ ] 4.3 Implement auto-import in `fit sync` — check configured path, validate CSV header, import new dates only, log to import_log, auto-update weight calibration
- [ ] 4.4 Investigate Fitdays API for direct integration (spike — document findings)
- [ ] 4.5 Test: auto-detect, duplicate prevention via hash, calibration refresh, wrong CSV format error

## 5. Individual Goal Tracking

- [ ] 5.1 Implement `fit goal add` — interactive CLI: name, type (race/metric/habit), target_value, target_unit, target_date
- [ ] 5.2 Implement `fit goal list` — show all active goals with current progress (VO2max 49/51 = 96%, streak 4/8 weeks = 50%)
- [ ] 5.3 Implement `fit goal complete <id>` — mark as achieved, log to goal_log
- [ ] 5.4 Add goal progress to Today tab — progress bars/values for each active goal
- [ ] 5.5 Add goal progress to `fit status` output
- [ ] 5.6 Test: goal CRUD, progress computation for race/metric/habit types

## 6. fit doctor

- [ ] 6.1 Implement `fit doctor` — validate: schema version, all tables exist, no orphaned data, correlation freshness, plan import recency, weight staleness, calibration status, data source health
- [ ] 6.2 Test: all-healthy scenario, various failure scenarios

---

# Phase 2b: Deep Analysis + Plan

## 7. .fit File Analysis

- [ ] 7.1 Add `fitparse` to optional dependencies (`[analysis]` extra in pyproject.toml)
- [ ] 7.2 Add migration 006: `activity_splits` table (activity_id, split_num, distance_km, time_sec, pace_sec_per_km, avg_hr, avg_cadence, elevation_gain_m, avg_speed_m_s, time_above_z2_ceiling_sec, start_distance_m, end_distance_m). Add `fit_file_path`, `splits_status` columns to activities.
- [ ] 7.3 Add `sync.download_fit_files` config toggle (default false) and `sync.max_fit_downloads: 20`
- [ ] 7.4 Implement `fit/fit_file.py` — download .fit via garminconnect (using retry wrapper), parse with fitparse, extract per-km splits, handle per-file failures (splits_status=failed, continue)
- [ ] 7.5 Implement rolling 1km cardiac drift detection — find drift_onset_km where HR decouples. Constant-pace filter: flag inconclusive if pace CV > 15%.
- [ ] 7.6 Implement pace variability (CV across splits) and cadence drift metrics
- [ ] 7.7 Integrate into `fit sync --splits` — download, parse, compute drift for new running activities
- [ ] 7.8 Add split visualization to Training tab (collapsible) — dual-axis bar+line (pace bars zone-colored + HR line), elevation profile background, fade point annotation, cardiac drift gauge card. Most recent long run only.
- [ ] 7.9 Add split analysis to `get_coaching_context()` — drift_onset_km, drift_pct, pace_cv, cadence_drift
- [ ] 7.10 Bundle test .fit fixture in tests/fixtures/, test full pipeline: parse → splits → drift → DB
- [ ] 7.11 Add `fit splits --backfill` for historical .fit processing (separate from sync)

## 8. Runna Training Plan Integration

- [ ] 8.1 Add migration 006 (extend): `planned_workouts` table (date, workout_type, target_distance_km, target_zone, target_pace_range, structure JSON, plan_week, plan_phase, plan_version, imported_at, status, notes). Unique constraint on (date, plan_version).
- [ ] 8.2 Implement `fit plan validate <file>` — dry-run: check format, unknown types, duplicate dates, missing fields
- [ ] 8.3 Implement `fit plan import <file>` — CSV import with versioning (mark old as superseded), log to import_log
- [ ] 8.4 Implement `fit plan` — show next 7 days of planned workouts
- [ ] 8.5 Implement plan adherence computation — per-run: zone/distance/pace deltas. Weekly compliance score (0-100%). Systematic intensity override detection (>60% easy runs overridden in 3 weeks). Rest day compliance.
- [ ] 8.6 Add plan indicators to run timeline (green/red border) + sparkline adherence row (28 dots for 4 weeks)
- [ ] 8.7 Add plan adherence to `get_coaching_context()` — weekly score, rest compliance, override detection
- [ ] 8.8 Test: import with versioning, validation errors, adherence computation, override detection

## 9. Coaching Signals + Run Story

- [ ] 9.1 Implement Run Story narrative generator — synthesize splits + correlations + previous-night checkin + weather into a paragraph for the most recent long run. Display on Coach tab.
- [ ] 9.2 Implement milestone/PB tracking — detect: new longest run, new best efficiency, streak milestones, VO2max peak. Store in goal_log, display on Today tab.
- [ ] 9.3 Implement heat acclimatization tracker — temperature-adjusted efficiency metric, project Berlin race day drift
- [ ] 9.4 Test: Run Story generation, milestone detection, heat projection

## 10. Documentation + Tests

- [ ] 10.1 Update README: correlations, Runna import, .fit analysis, `fit goal`, `fit doctor`, alerts
- [ ] 10.2 Update CLAUDE.md: new tables, new CLI commands, MCP schema changes, correlation methodology
- [ ] 10.3 Add comprehensive tests for all Phase 2 modules (correlations, alerts, plan adherence, splits, goals)
- [ ] 10.4 Verify all tests pass, ruff clean, CI green
