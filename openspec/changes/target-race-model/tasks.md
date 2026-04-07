# Target Race Model

## 1. Schema + Migration

- [ ] 1.1 Create migration 010 (Python): add `is_target BOOLEAN DEFAULT 0` to race_calendar, add `derivation_source TEXT DEFAULT 'manual'`, `auto_value REAL`, `is_override BOOLEAN DEFAULT 0` to goals
- [ ] 1.2 Backfill: set `is_target = 1` on the race currently linked via goals.race_id (preserve existing state)
- [ ] 1.3 Backfill: set `derivation_source = 'manual'` on all existing goals
- [ ] 1.4 Test: migration applies cleanly, backfill correct, is_target constraint works

## 2. Target Race Lifecycle

- [ ] 2.1 Simplify `get_target_race()`: `SELECT * FROM race_calendar WHERE is_target = 1 LIMIT 1`
- [ ] 2.2 Add `set_target_race(conn, race_id)`: clear all is_target, set chosen one, trigger objective derivation
- [ ] 2.3 Add `clear_target_race(conn)`: clear all is_target
- [ ] 2.4 Add CLI: `fit target set <race_id>` — set target, show summary with derived objectives
- [ ] 2.5 Add CLI: `fit target show` — display current target + objectives + days remaining
- [ ] 2.6 Add CLI: `fit target objectives` — list objectives with auto/manual labels, allow edit
- [ ] 2.7 Add CLI: `fit target clear` — remove target
- [ ] 2.8 Update `fit status` to use simplified `get_target_race()`
- [ ] 2.9 Test: set/clear/switch target, exactly-one constraint, CLI output

## 3. Objective Derivation

- [ ] 3.1 Implement `derive_objectives(conn, race_id)`: compute VO2max target (Daniels inverse), volume target, long run target, consistency target, Z2 target from race distance + target_time
- [ ] 3.2 Implement Daniels inverse lookup: given target_time + distance → minimum VO2max needed
- [ ] 3.3 Distance-based heuristics: peak volume (marathon 50-60, HM 40-50, 10K 30-40), long run (marathon 30-32, HM 18-21, 10K 12-15), consistency weeks (marathon 12, HM 8, 10K 6)
- [ ] 3.4 On `set_target_race()`: auto-create goals with `derivation_source = 'auto_daniels'` / `'auto_distance'` / `'auto_timeline'`, set `auto_value` and `target_value`
- [ ] 3.5 Preserve user overrides: when target changes, update `auto_value` on all auto-derived goals but only update `target_value` if `is_override = 0`
- [ ] 3.6 Preserve manual goals (weight, custom): `derivation_source = 'manual'` goals are never recalculated
- [ ] 3.7 Update `_goal_progress()`: show derivation source label ("auto · Daniels" vs "manual")
- [ ] 3.8 Test: derivation for marathon/HM/10K targets, override preservation, manual goal carry-over, inverse Daniels accuracy

## 4. Adaptive Predictions

- [ ] 4.1 Rename `predict_marathon_time()` → `predict_race_time(target_km=42.195, ...)` with backward compat
- [ ] 4.2 Update prediction trend chart: use target_km from `get_target_race()`, scale VDOT to target distance
- [ ] 4.3 Update race prediction table: Riegel extrapolates to target_km, target annotation uses target_time
- [ ] 4.4 Update prediction summary in Race Anchor Card: range for target distance
- [ ] 4.5 Update pacing strategy: adapt segment count and HR ceilings to target distance
- [ ] 4.6 Update all callers of predict_marathon_time to use predict_race_time
- [ ] 4.7 Test: predictions for marathon/HM/10K, backward compat, pacing for different distances

## 5. Global Color Palette + Readability

- [ ] 5.1 Define 5-zone palette in CSS variables: Z1=#93c5fd, Z2=#60a5fa, Z3=#fbbf24, Z4=#f97316, Z5=#ef4444
- [ ] 5.2 Update all chart generators to use 5 zones (not grouped Z1+Z2/Z4+Z5)
- [ ] 5.3 Align run type colors: easy=Z2 blue, tempo=Z3 amber, intervals=Z4 orange, race=purple, long=emerald
- [ ] 5.4 Set Chart.defaults.font.size = 12 (was 10)
- [ ] 5.5 Enforce minimum 60% opacity on all data lines/fills
- [ ] 5.6 Max 2 datasets per chart — split any chart with 3+ into separate charts
- [ ] 5.7 Weight chart: don't connect across >30 day gaps
- [ ] 5.8 Test: all charts readable on dark background, colors distinguishable

## 6. Dashboard Redesign: Metric Cards

- [ ] 6.1 Create metric card component: value + action + sparkline + target in one unit
- [ ] 6.2 Replace Body tab charts with metric cards: readiness, RHR, HRV, stress/battery → cards. Keep: weight trend, sleep composition, ACWR trend as charts
- [ ] 6.3 Replace Training tab raw numbers: volume, runs/week, Z2 compliance → cards with progress bars toward phase targets
- [ ] 6.4 Update Today tab: status cards use derived targets from objectives (not hardcoded)
- [ ] 6.5 Add "so what?" action text to every card: derived from readiness thresholds, phase targets, objective targets
- [ ] 6.6 Test: cards render with and without target race set, empty states work

## 7. Chart Improvements

- [ ] 7.1 Zone distribution: show 5 zones (not 3 groups), percentage bars with phase target line
- [ ] 7.2 Efficiency chart: add trend caption "improving/declining X% over 4 weeks"
- [ ] 7.3 Split analysis: frame as "Aerobic ceiling test" with interpretive caption
- [ ] 7.4 Prediction table: range bar prominent, detail collapsed (already done, verify)
- [ ] 7.5 ACWR chart: capped y-axis (already done), spike annotations scoped (already done)
- [ ] 7.6 Run Timeline: show per-run zone % breakdown (not just single zone color)
- [ ] 7.7 Test: all charts meet readability minimums, "so what?" context present

## 8. Documentation

- [ ] 8.1 Update Today tab: objectives show derivation source label
- [ ] 8.2 Update Fitness tab section title: adapts to target distance
- [ ] 8.3 Update journey timeline: waypoint races as milestone markers
- [ ] 8.4 Update CLAUDE.md: target race model, is_target flag, objective derivation, color palette, metric cards
- [ ] 8.5 Update README: fit target commands, dashboard redesign
- [ ] 8.6 Test: dashboard renders correctly with marathon/HM targets, all tabs consistent
