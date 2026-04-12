# Target Race Model — Fitness-First Design

## 1. Fitness Profile Module

- [x] 1.1 Create `fit/fitness.py`: `get_fitness_profile(conn)` returning 4 dimensions (aerobic, threshold, economy, resilience) with current_value, trend, rate_per_month
- [x] 1.2 Implement VDOT computation from race results using Daniels tables (distance + time → VDOT score)
- [x] 1.3 Implement effective_vdot: blend Garmin VO2max and race VDOT (prefer race when <8 weeks old)
- [x] 1.4 Implement trend computation: 8-week linear regression per dimension, rate expressed per month
- [x] 1.5 Resilience dimension: drift onset km + long run ceiling from activity_splits (graceful degradation without .fit data)
- [x] 1.6 Test: profile with sufficient data, insufficient data, VDOT from multiple distances, trend directions

## 2. Schema + Migration

- [x] 2.1 Create migration 010 (Python): add `derivation_source TEXT DEFAULT 'manual'`, `auto_value REAL`, `is_override BOOLEAN DEFAULT 0` to goals
- [x] 2.2 Backfill: set `derivation_source = 'manual'` on all existing goals
- [x] 2.3 Test: migration applies cleanly, existing goals preserved

## 3. Target Race Lifecycle

- [x] 3.1 Implement `set_target_race(conn, race_id)`: update all active goals.race_id + trigger objective re-derivation
- [x] 3.2 Add CLI: `fit target set <race_id>` — set target, derive objectives, show summary
- [x] 3.3 Add CLI: `fit target show` — current target + fitness profile + objectives + gap analysis
- [x] 3.4 Add CLI: `fit target clear` — unlink goals from race
- [x] 3.5 Update `fit status` to show target info from fitness profile
- [x] 3.6 Test: set/clear/switch target, objectives recalculate, overrides preserved

## 4. Objective Derivation

- [x] 4.1 Implement Daniels inverse lookup: target_time + distance → required VDOT → per-dimension minimums
- [x] 4.2 Distance-based heuristics: peak volume, long run target, consistency weeks (scaled by distance)
- [x] 4.3 Achievability projection: current + (trend × months_remaining) vs required. Three levels: ✓/⚠/✗
- [x] 4.4 On `set_target_race()`: auto-create/update goals with derivation_source, auto_value. Only update target_value if is_override=0
- [x] 4.5 Preserve user overrides: is_override=1 goals keep target_value, auto_value still updates for comparison
- [x] 4.6 Preserve manual goals (weight, custom): derivation_source='manual' never recalculated
- [x] 4.7 Test: derivation for marathon/HM/10K, override preservation, achievability edge cases (no trend data, 0 days remaining)

## 5. Checkpoint Enrichment

- [x] 5.1 Implement `derive_checkpoint_targets(conn)`: Riegel back-calculation from target race for each upcoming registered race
- [x] 5.2 On race completion: compute VDOT from result, update effective_vdot, recalculate target race projection
- [x] 5.3 Readiness signal: "Your S25 result (22:15) → VDOT 45.5 → marathon projection: 3:55"
- [x] 5.4 Dashboard: checkpoint card on Today tab showing user target vs derived target vs gap
- [x] 5.5 Test: derived times for 5K/10K/HM checkpoints, VDOT update after race, projection change

## 6. Adaptive Predictions

- [x] 6.1 Rename `predict_marathon_time()` → `predict_race_time(target_km=42.195)` with backward compat
- [x] 6.2 Verify prediction trend chart adapts to target_km (already partially implemented)
- [x] 6.3 Verify race prediction table adapts (already implemented)
- [x] 6.4 Verify prediction summary adapts (already implemented)
- [x] 6.5 Update pacing strategy for non-marathon distances
- [x] 6.6 Test: predictions for marathon/HM/10K, backward compat

## 7. Global Color Palette + Readability

- [x] 7.1 Define 5-zone CSS variables: Z1=#93c5fd, Z2=#60a5fa, Z3=#fbbf24, Z4=#f97316, Z5=#ef4444
- [x] 7.2 Update all chart generators to use 5 zones (not grouped Z1+Z2/Z4+Z5)
- [x] 7.3 Align run type colors with zone palette
- [x] 7.4 Set Chart.defaults.font.size = 12
- [x] 7.5 Enforce minimum 60% opacity on all data lines
- [x] 7.6 Max 2 datasets per chart — split any with 3+
- [x] 7.7 Weight chart: don't connect across >30 day gaps
- [x] 7.8 Test: all charts readable on dark background

## 8. Dashboard Redesign: Metric Cards

- [x] 8.1 Create metric card component: value + action + sparkline + target
- [x] 8.2 Body tab: replace 6 charts with metric cards (readiness, RHR, HRV, stress) + keep charts (weight, sleep, ACWR)
- [x] 8.3 Training tab: volume/compliance/frequency as cards with gap-to-target from objectives
- [x] 8.4 Today tab: objective cards show gap + achievability from fitness profile
- [x] 8.5 Fitness tab: efficiency trend caption, zone distribution as 5-zone %, split analysis as "resilience test"
- [x] 8.6 Test: cards render with/without target, empty states, achievability levels

## 9. Documentation

- [x] 9.1 Update CLAUDE.md: fitness profile, VDOT tracking, objective derivation, checkpoint model
- [x] 9.2 Update README: fit target commands, fitness model explanation
- [x] 9.3 Update all specs to match implementation
- [x] 9.4 Test: dashboard renders correctly with marathon/HM/10K targets, all tabs consistent
