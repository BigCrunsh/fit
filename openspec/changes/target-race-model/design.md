## Context

Phase 2 delivered a race-anchored dashboard with 16 tables, narratives, .fit analysis, and plan integration. But the race↔goal relationship is inverted: goals point to races, and `get_target_race()` infers the target by traversing FK chains. Objectives are manually created, not derived from the target race's requirements. Changing the target requires SQL updates.

## Goals / Non-Goals

**Goals:**
- One-command target race switching (`fit target set <id>`)
- Objectives auto-derive from target_time + Daniels + training science
- Dashboard, predictions, and pacing strategy adapt to target distance
- User overrides preserved across target changes

**Non-Goals:**
- Multi-target periodization (training for two races simultaneously)
- Automated training plan generation (Runna generates, we track)
- Historical objective tracking (what objectives were when target was X)

## Decisions

### 1. `is_target` flag on race_calendar (not a separate table)

Add `is_target BOOLEAN DEFAULT 0` to `race_calendar`. Enforce exactly-one constraint at application level (not SQL — SQLite doesn't support partial unique indexes well). `fit target set <id>` clears all `is_target` then sets the chosen one.

`get_target_race()` becomes: `SELECT * FROM race_calendar WHERE is_target = 1 LIMIT 1`. No more FK chain traversal.

### 2. Objectives as derived + overridable rows in goals table

Keep the `goals` table but add columns:
- `derivation_source TEXT` — 'auto_daniels', 'auto_distance', 'auto_timeline', 'manual'
- `auto_value REAL` — the system-derived value (preserved even when user overrides target_value)
- `is_override BOOLEAN DEFAULT 0` — true when user has manually set target_value

When target changes:
1. For `is_override = 0` goals: recalculate `target_value` and `auto_value` from new target
2. For `is_override = 1` goals: keep user's `target_value`, update `auto_value` to show what the system would suggest
3. Goals with `derivation_source = 'manual'` (user-created, like weight) are never auto-recalculated

### 3. Daniels-based objective derivation

Given target_time and distance, derive:
- **VO2max target**: Inverse Daniels lookup. Sub-4:00 marathon → VO2max ≥50. Sub-1:47 HM → VO2max ≥52.
- **Weekly volume target**: Distance-based heuristic. Marathon: peak 50-60km/wk. HM: peak 40-50km/wk. 10K: peak 30-40km/wk.
- **Long run target**: Marathon: 30-32km. HM: 18-21km. 10K: 12-15km.
- **Consistency target**: Marathon: 12 weeks 3+ runs. HM: 8 weeks. 10K: 6 weeks.
- **Z2 compliance target**: Always 80%+ for base building, 70%+ for peak/taper.

User-set objectives (weight, custom metrics) are `derivation_source = 'manual'` and carry over unchanged.

### 4. Adaptive prediction distance

`predict_marathon_time()` renamed to `predict_race_time()`. Takes `target_km` parameter (from `race_calendar.distance_km WHERE is_target = 1`). Riegel extrapolates to target_km, VDOT scales from marathon equivalent. Prediction trend chart and table both use target_km.

### 5. Waypoint race display

Non-target registered races appear as:
- Compact pills on the Today tab (already implemented)
- Milestone markers on the journey timeline
- Rows in `fit races` with a distinct marker (vs the ★ target)

Waypoint races do NOT generate objectives or appear in the Objectives section.

### 6. Migration strategy (010)

Python migration (for transactional safety):
1. `ALTER TABLE race_calendar ADD COLUMN is_target BOOLEAN DEFAULT 0`
2. Set `is_target = 1` on the race that current active goals reference: `UPDATE race_calendar SET is_target = 1 WHERE id = (SELECT DISTINCT race_id FROM goals WHERE active = 1 AND race_id IS NOT NULL LIMIT 1)`
3. `ALTER TABLE goals ADD COLUMN derivation_source TEXT DEFAULT 'manual'`
4. `ALTER TABLE goals ADD COLUMN auto_value REAL`
5. `ALTER TABLE goals ADD COLUMN is_override BOOLEAN DEFAULT 0`
6. Backfill: set `derivation_source = 'manual'` on existing goals (preserves them as user-created)

### 7. CLI commands

- `fit target set <race_id>` — set target race, derive objectives, show summary
- `fit target show` — display current target race + derived objectives
- `fit target objectives` — show objectives with auto vs manual values, allow editing
- `fit target clear` — remove target (dashboard falls back to nearest race)

## Risks / Trade-offs

**[Objective drift]** Auto-derived objectives may not match user expectations.
→ Mitigation: Always show "auto-suggested: X, your target: Y" so the user sees the gap.

**[Target switching churn]** Frequent target switches recalculate objectives each time.
→ Mitigation: `is_override` preserves user choices. Only auto-derived values change.

**[Daniels accuracy at extremes]** VDOT inverse lookup is approximate for VO2max <40 or >60.
→ Mitigation: Same interpolated lookup table already validated in Phase 2.
