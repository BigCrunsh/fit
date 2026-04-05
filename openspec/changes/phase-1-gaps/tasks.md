## 1. Sync & Data Pipeline Gaps

- [ ] 1.1 Add user-friendly auth error in `garmin.py` — catch garth auth failures, show exact re-auth command
- [ ] 1.2 Expand activity type fetch list — add "strength_training", "elliptical", "yoga" or use a catch-all approach
- [ ] 1.3 Extract actual start hour from activity `startTimeLocal` in `garmin.py` and pass to hourly weather (instead of hardcoded hour=8)
- [ ] 1.4 LTHR auto-extraction: when a race candidate is detected in sync, prompt user or auto-save with method='race_extract', confidence='medium'
- [ ] 1.5 Add non-running guard to `compute_speed_per_bpm` — return None if activity type is not running
- [ ] 1.6 ACWR: require minimum 3 prior weeks (not 2) for computation, return None otherwise

## 2. fit status Enhancement

- [ ] 2.1 Wire `get_calibration_status()` into `fit status` — show max_hr, lthr, weight staleness + retest prompts
- [ ] 2.2 Wire `check_data_sources()` into `fit status` — show active/stale/missing per source
- [ ] 2.3 Show active training phase with compliance summary in `fit status`
- [ ] 2.4 Show ACWR (with safety indicator) and consistency streak in `fit status`

## 3. MCP Server Gaps

- [ ] 3.1 Add DB existence check in MCP server startup — return "fitness.db not found. Run `fit sync` first." instead of raw OperationalError
- [ ] 3.2 Add LTHR detection source check to `data_health.py`
- [ ] 3.3 Add automated goal creation logging — when goals are inserted via seed scripts, log to goal_log

## 4. Dashboard Gaps

- [ ] 4.1 Inline or remove Google Fonts @import — either vendor the fonts or use system fallback for offline support
- [ ] 4.2 Add run type breakdown stacked chart to Training tab (easy/long/tempo/intervals/recovery per week, intensity palette)
- [ ] 4.3 Extend event annotations to all time-series charts (weight, cadence, volume — not just efficiency + VO2)
- [ ] 4.4 Add calibration change and goal milestone events to `_get_event_annotations()`
- [ ] 4.5 Status cards: add VO2max peak reference + 4-week delta, weight race target + 4-week delta, sleep card REM hours
- [ ] 4.6 Zone distribution chart: overlay active phase z12_pct_target and z45_pct_target as reference lines
- [ ] 4.7 Journey timeline: add current vs target metrics below each phase segment
- [ ] 4.8 Sleep chart: add average annotation lines for total sleep and deep sleep
- [ ] 4.9 Weight chart: add race target reference line (from goals table) and event annotations
- [ ] 4.10 Headline engine: check sleep_quality='Poor' as recovery trigger (alongside readiness < 50)
- [ ] 4.11 Week-over-week card: detect incomplete current week (today != Sunday), label "Week in progress"
- [ ] 4.12 Race prediction: add confidence explanation and note about post-gap fitness adjustment
- [ ] 4.13 Metric definitions: make remaining generic definitions contextual (sleep, stress, cadence — reference actual values)

## 5. Documentation

- [ ] 5.1 Update spec: document that env vars are placeholder-substitution (not general key override) — this is by-design
- [ ] 5.2 Note in CLAUDE.md: logging uses single sync.log (design says per-module, implementation uses one file)
