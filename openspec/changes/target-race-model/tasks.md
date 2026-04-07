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

## 5. Dashboard + Docs

- [ ] 5.1 Update Today tab: objectives show derivation source label
- [ ] 5.2 Update Fitness tab section title: "Race Forecast" (already done) adapts subtitle to target distance
- [ ] 5.3 Update journey timeline: waypoint races as milestone markers
- [ ] 5.4 Update CLAUDE.md: target race model, is_target flag, objective derivation
- [ ] 5.5 Update README: fit target commands
- [ ] 5.6 Test: dashboard renders correctly with marathon/HM targets, all tabs consistent
