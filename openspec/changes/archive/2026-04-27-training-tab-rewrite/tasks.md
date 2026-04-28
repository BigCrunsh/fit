## 1. Rolling Window Foundation

- [x] 1.1 Extract `_aggregate_date_range(conn, start_date, end_date)` from `compute_weekly_agg()` in `fit/analysis.py` — shared internal function returning the same dict structure as a `weekly_agg` row
- [x] 1.2 Refactor `compute_weekly_agg()` to call `_aggregate_date_range()` with Mon/Sun dates — no behavior change, existing tests must pass
- [x] 1.3 Implement `compute_rolling_week(conn, end_date=None, window_days=7)` calling `_aggregate_date_range()` with (today-6, today)
- [x] 1.4 Add `compute_rolling_acwr(conn, end_date=None)` — acute from `compute_rolling_week()`, chronic from prior 4 ISO weeks in `weekly_agg`
- [x] 1.5 Tests for `_aggregate_date_range()`: verify identical output to `compute_weekly_agg()` for same Mon-Sun range
- [x] 1.6 Tests for `compute_rolling_week()`: mid-week query includes prior days, Monday includes weekend runs, empty window returns zeros
- [x] 1.7 Tests for `compute_rolling_acwr()`: rolling acute vs ISO chronic, insufficient chronic data returns None

## 2. Rolling Window Consumers

- [x] 2.1 Update `fit/alerts.py`: remove `iso.weekday < 5` partial-week suppression guard, use `compute_rolling_week()` for ACWR evaluation
- [x] 2.2 Update `fit/cli.py` `fit status`: replace ISO week lookup with `compute_rolling_week()`, change label from "This week" to "Last 7 days"
- [x] 2.3 Update `fit/narratives.py` `generate_wow_sentence()`: accept rolling 7d dicts (same structure, different source), handle "fewer than 14 days of history" edge case
- [x] 2.4 Update `mcp/server.py` `get_coaching_context()`: replace ISO week current-week query with `compute_rolling_week()`, remove partial-week ACWR flag
- [x] 2.5 Tests for alerts: ACWR alert fires on Tuesday when threshold met, no day-of-week suppression
- [x] 2.6 Tests for `generate_wow_sentence()`: rolling input produces correct deltas, first-week edge case

## 3. Remove `fit goal` CLI

- [x] 3.1 Remove `fit goal add/list/complete` Click group from `fit/cli.py`
- [x] 3.2 Remove manual goal CRUD functions from `fit/goals.py` (keep `get_target_race()`, `set_target_race()`, `clear_target_race()`, and anything used by `derive_objectives()`)
- [x] 3.3 Remove manual goal CRUD tests from `tests/test_goals.py` (keep target race lifecycle and objective derivation tests)
- [x] 3.4 Update `mcp/server.py`: remove references to `fit goal add` in coaching context and tool descriptions
- [x] 3.5 Update CLAUDE.md: remove `fit goal` from Quick Commands and Architecture sections, update Goal CLI references to `fit target`

## 4. Training Tab — Hero Card & Objectives

- [x] 4.1 Implement `_last_7_days_hero(conn)` in `cards.py`: compliance ring (planned vs completed in 7d window), volume progress bar (rolling 7d vs phase target), WoW subtitle from `generate_wow_sentence()`, next workout from `_next_workouts()`
- [x] 4.2 Implement `_training_objectives(conn)` in `cards.py`: 4 canonical slots (Volume, Long Run, Z2, Consistency), auto-derived targets via prefix match to `derive_objectives()`, deactivated state with "Set a target race with `fit target set`" prompt
- [x] 4.3 Streak sub-label logic in `_training_objectives()`: "2/3 runs this week — 1 more to keep streak", "streak secured, updates Monday", at-risk amber when late in week
- [x] 4.4 Tests for `_last_7_days_hero()`: rolling window data, no plan data, no activities, compliance ring values
- [x] 4.5 Tests for `_training_objectives()`: all active (target race), all deactivated (no race), prefix matching to derived names, streak sub-labels

## 5. Training Tab — Last 7 Days Run Detail Cards

- [x] 5.1 Implement `_last_7_days_runs(conn)` in `cards.py`: query activities for last 7 days, build card header (date, run_type, distance, duration, pace, HR, effort class, training load)
- [x] 5.2 Plan comparison per run: match planned workout by date, compute pacing verdict (on target / too fast / too slow based on zone intent)
- [x] 5.3 Per-km split display: query `activity_splits`, horizontal pace bars colored by zone, elevation overlay, cardiac drift from `compute_cardiac_drift()`
- [x] 5.4 Workout phase overlay on splits: group splits under phase labels when planned workout has phases (skipped — planned_workouts schema has no per-phase breakdown)
- [x] 5.5 Adaptation signals SQL: self-join query for 4-week rolling avg pace and speed_per_bpm by same run_type, HAVING count >= 2
- [x] 5.6 sRPE context per run: show sRPE value with "felt harder/easier than HR suggests" when sRPE exists
- [x] 5.7 Tests for `_last_7_days_runs()`: multiple runs, no runs, plan comparison verdicts, split display with/without data, adaptation signals with sufficient/insufficient history

## 6. Training Tab — Plan Adherence & Charts

- [x] 6.1 Implement `_weekly_plan_adherence(conn)` in `cards.py`: call `compute_plan_adherence()` for last 4 ISO weeks, build week rows with compliance %, color coding (<70% amber, <50% red)
- [x] 6.2 Modify volume chart in `charts.py`: default to 12 weeks, add phase target as shaded band (box annotation, 40+ hex opacity), use `weekly_agg` for history + `compute_rolling_week()` for current bar, x-axis labels as end dates
- [x] 6.3 Remove Training Load per Run chart from `_all_charts()` in `charts.py`
- [x] 6.4 Add gap annotations to volume chart: shaded regions for training breaks >14 days with duration label
- [x] 6.5 Tests for `_weekly_plan_adherence()`: 4 weeks of data, partial data, no plan data, compliance thresholds
- [x] 6.6 Tests for volume chart: 12w default range, phase target band present, rolling current bar, gap annotations

## 7. Template & Wiring

- [x] 7.1 Update `fit/report/generator.py`: wire new context variables (hero card, objectives, last 7 days runs, plan adherence) to template
- [x] 7.2 Rewrite Training tab section in `dashboard.html`: 6 sections in order (hero, objectives, last 7 days, plan adherence, volume trend, run type mix)
- [x] 7.3 Progressive disclosure JS for run detail cards: click-to-expand toggle, CSS `display:none` default for detail sections
- [x] 7.4 Remove old Training tab sections from template: standalone WoW card, Training Load chart, flat Run Timeline
- [x] 7.5 Style hero card: compliance ring (SVG or CSS conic-gradient), volume progress bar, WoW subtitle, next workout display
- [x] 7.6 Style objectives row: 4-slot grid, active vs deactivated states, traffic-light colors, streak sub-label
- [x] 7.7 Style run detail cards: collapsed header, expanded detail with splits/plan/signals sections

## 8. Coaching Cadence

- [x] 8.1 Update `_coaching()` in `cards.py`: change staleness from `report_date < last_sync` to `report_date < (today - 7 days)`
- [x] 8.2 Update `check_dashboard_freshness()` in `mcp/server.py`: compare coaching age to 7 days, not last sync
- [x] 8.3 Update stale coaching banner text in `dashboard.html`: "Last coaching review was N days ago. Time for a weekly check-in — ask Claude to review your week."
- [x] 8.4 Tests for coaching staleness: 3-day-old notes after sync = fresh, 9-day-old notes = stale

## 9. Integration & Cleanup

- [x] 9.1 Run full test suite, fix any regressions from rolling window refactor
- [x] 9.2 Generate dashboard with test data, visual review of all 6 Training tab sections (manual)
- [x] 9.3 Verify `fit status` shows "Last 7 days" with rolling data
- [x] 9.4 Verify `fit sync` still populates `weekly_agg` correctly (no regression — full test suite passes, 773 tests)
- [x] 9.5 Verify Coach tab staleness works on 7-day cadence
- [x] 9.6 Update CLAUDE.md: document rolling window design decision, update Training tab description, remove `fit goal` references
