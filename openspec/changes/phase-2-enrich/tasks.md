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
