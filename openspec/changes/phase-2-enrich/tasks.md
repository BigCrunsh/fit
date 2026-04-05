## 1. Sync UX (quick win)

- [ ] 1.1 Replace print statements in `fit sync` with Rich Progress bars — per-step tasks (health, activities, SpO2, weather, enrichment, weekly_agg) with item counts
- [ ] 1.2 Add ETA display for `fit sync --full` based on date range and API response rate
- [ ] 1.3 Add retry with countdown for API rate limits (429 responses)
- [ ] 1.4 Improve auth error message: show exact re-auth command when garth tokens expire
- [ ] 1.5 Test: verify progress bars render, retry works, auth error is actionable

## 2. Correlation Engine

- [ ] 2.1 Add `correlations` table to schema: metric_pair, lag_days, coefficient, p_value, sample_size, last_computed
- [ ] 2.2 Implement `fit/correlations.py` — predefined pairs: alcohol→HRV (lag 1), alcohol→readiness (lag 1), sleep_quality→readiness (lag 0), weight→pace (weekly, lag 0), temp→speed_per_bpm (lag 0), water→HRV (lag 1)
- [ ] 2.3 Implement `fit correlate` CLI command — compute all correlations, display ranked table
- [ ] 2.4 Add correlation summary to `get_coaching_context()` — top 5 by absolute strength
- [ ] 2.5 Add correlation panel to Fitness tab — strongest positive/negative with effect sizes
- [ ] 2.6 Test: compute with real data, insufficient data handling, dashboard rendering

## 3. Runna Training Plan Integration

- [ ] 3.1 Add `planned_workouts` table: date, workout_type, target_distance_km, target_zone, target_pace_range, notes
- [ ] 3.2 Implement `fit plan import <file>` — CSV/JSON import into planned_workouts
- [ ] 3.3 Implement `fit plan` — show next 7 days of planned workouts
- [ ] 3.4 Implement plan adherence: join activities with planned_workouts, compute zone/distance/pace deltas
- [ ] 3.5 Add plan indicator to run timeline visualization (green=on plan, red=deviated)
- [ ] 3.6 Add plan adherence summary to `get_coaching_context()`
- [ ] 3.7 Test: import CSV, plan display, adherence computation (on-plan, deviated, rest violation)

## 4. Fitdays Auto-Import

- [ ] 4.1 Add weight CSV auto-detection in `fit sync` — scan ~/Downloads/ for apple_health_weight*.csv
- [ ] 4.2 Import new measurements (only dates not already in body_comp)
- [ ] 4.3 Auto-update weight calibration when new body_comp data imported
- [ ] 4.4 Investigate Fitdays API for direct integration (spike — document findings)
- [ ] 4.5 Test: auto-detect, import new only, calibration refresh

## 5. .fit File Analysis

- [ ] 5.1 Add `fitparse` to dependencies
- [ ] 5.2 Add `activity_splits` table: activity_id, split_num, distance_km, time_sec, pace_sec_per_km, avg_hr, avg_cadence, elevation_gain_m
- [ ] 5.3 Implement `fit/fit_file.py` — download .fit via garminconnect, parse with fitparse, extract per-km splits
- [ ] 5.4 Integrate into `fit sync` — download and parse .fit for new running activities
- [ ] 5.5 Implement cardiac drift detection: HR first half vs second half, flag >5% drift
- [ ] 5.6 Add split visualization to Fitness tab — pace/HR/cadence per km for selected run
- [ ] 5.7 Add split analysis to `get_coaching_context()` — drift %, fade point for last long run
- [ ] 5.8 Test: parse known .fit file, split extraction, drift computation

## 6. ioBroker Integration (optional)

- [ ] 6.1 Add `iobroker` config section: enabled, output_path
- [ ] 6.2 After `fit sync`, write `~/.fit/iobroker.json` with: readiness, ACWR, last run (date/distance/zone), weight, streak, headline
- [ ] 6.3 Test: JSON file written, structure valid, disabled by default

## 7. Documentation + Tests

- [ ] 7.1 Update README: correlation engine usage, Runna plan import format, .fit file analysis
- [ ] 7.2 Update CLAUDE.md: new tables, new CLI commands, correlation pairs
- [ ] 7.3 Add tests for correlations (happy + edge cases), plan adherence, split parsing
- [ ] 7.4 Verify all tests pass, ruff clean
