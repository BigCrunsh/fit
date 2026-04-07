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

### 8. Dashboard redesign: metric cards over charts

Most current charts fail the "so what?" test — they show data without context or action. The fix is NOT adding captions to every chart (that's additive complexity). The fix is replacing most charts with **metric cards**: value + action + sparkline + target in one compact unit.

**What stays as a chart** (time-series where the shape tells a story):
- Efficiency trend (is my aerobic engine improving?)
- Prediction trend (am I getting closer to my target time?)
- Weight trend (long-term body comp trajectory)
- Sleep composition (stacked bars — visual pattern)
- ACWR trend (spike/recovery pattern)

**What becomes a metric card** (single-number-with-context):
- Readiness → card: "67 — easy day" with 7d sparkline
- RHR → card: "60 bpm ↓5" with trend arrow
- HRV → card: "29ms — low" with 7d sparkline
- Volume → card: "8km / 25-30km target" with progress bar
- Z2 compliance → card: "50% / 90% target" with progress bar
- Runs/week → card: "1 / 3-4 target"
- Stress/Battery → card: "Stress 26, Battery 85→42" (two numbers, no chart)

### 9. Global 5-zone color palette

Every chart and card uses the same colors for the same meaning. 5 zones, not 3 groups:

```
Z1 Recovery   = #93c5fd (blue-300, lighter)
Z2 Easy       = #60a5fa (blue-400)
Z3 Moderate   = #fbbf24 (amber-400)
Z4 Hard       = #f97316 (orange-400)
Z5 Very Hard  = #ef4444 (red-400)
```

Run type colors align with zone colors:
- easy/recovery = Z1/Z2 blue
- long = #34d399 (emerald — distinct, not a zone)
- tempo = Z3 amber
- intervals = Z4 orange
- race = #c084fc (purple — special events)

Safety/status:
- On track = #34d399 (emerald)
- Caution = #fbbf24 (amber, same as Z3 — intentional)
- Danger = #f87171 (red-400, brighter than current)

Neutral:
- Accent/primary = #818cf8 (indigo)
- Muted text = #94a3b8 (slate-400)

All colors at minimum 60% opacity on #07070c background. No more 20% ghost lines.

### 10. Every element answers four questions

Inspired by Duarte's *Data Story* framework, every dashboard element must answer:
1. **What is it?** (label)
2. **Where am I?** (current value)
3. **Where should I be?** (target — derived from target race)
4. **What should I do?** (action)

If an element can't answer all four, it either needs a target (from objective derivation) or should be removed.

### 11. Chart readability minimums

- Font size: 12px minimum (was 10px)
- Line opacity: 60% minimum (was 20% for some datasets)
- Point radius: 4px minimum for interactive charts
- Axis labels: always visible, never truncated
- Maximum 2 datasets per chart (3 = confusing, split into separate charts)
- Weight/body fat: don't connect across >30 day gaps (`segment` option)

## Risks / Trade-offs

**[Objective drift]** Auto-derived objectives may not match user expectations.
→ Mitigation: Always show "auto-suggested: X, your target: Y" so the user sees the gap.

**[Target switching churn]** Frequent target switches recalculate objectives each time.
→ Mitigation: `is_override` preserves user choices. Only auto-derived values change.

**[Daniels accuracy at extremes]** VDOT inverse lookup is approximate for VO2max <40 or >60.
→ Mitigation: Same interpolated lookup table already validated in Phase 2.
