## Context

Phase 2 delivered a race-anchored dashboard with narratives, .fit analysis, plan integration, and Apple Health import. Post-archive improvements added coaching history, plan adherence zone compliance, prediction scaling to target distance, and data storytelling. But metrics still don't answer "so what?" because there's no fitness model connecting observations to race requirements.

## Goals / Non-Goals

**Goals:**
- Fitness profile tracking 4 dimensions (aerobic capacity, threshold, economy, resilience)
- VDOT from race results as primary fitness score (more reliable than Garmin VO2max)
- Objectives auto-derived from target race + Daniels + timeline (gap × achievability)
- Checkpoint races as fitness measurement opportunities with readiness signals
- Dashboard where every element shows: value + target + gap + action
- One-command target switching (`fit target set <id>`)

**Non-Goals:**
- Multi-target periodization (one target at a time)
- Automated training plan generation (Runna generates, we track)
- Machine learning prediction model (Riegel + Daniels is sufficient for now)
- Real-time race pacing from wearable (post-race analysis only)

## Decisions

### 1. Target race via goals.race_id (no schema change needed)

Proven approach: `UPDATE goals SET race_id = ? WHERE active = 1` switches the target. `get_target_race()` follows the FK chain. `fit target set <id>` wraps this + triggers objective re-derivation.

No `is_target` flag needed — the FK chain already works and we proved it by switching from marathon to HM in this session.

### 2. Fitness profile as 4 dimensions

Based on established sports science (Daniels, Canova, recent research on physiological resilience):

| Dimension | Indicators | Source |
|-----------|-----------|--------|
| Aerobic capacity | VO2max (Garmin), VDOT (races) | activities.vo2max, race_calendar.result_time |
| Threshold | LTHR, Z2 pace at HR ceiling | calibration, activities (Z2 filtered) |
| Economy | speed_per_bpm, cadence | activities |
| Resilience | drift onset km, pace fade %, long run ceiling | activity_splits, fit_file analysis |

New: `fit/fitness.py` module computes the profile from existing data. No new tables — it's a view over existing data, not new storage.

### 3. VDOT from race results, not just Garmin VO2max

Each race in race_calendar with a result_time produces a VDOT score via Daniels tables. This is more reliable than Garmin's wrist-based VO2max estimate because it's measured from actual performance, not estimated from HR data.

The fitness profile tracks both:
- `garmin_vo2max`: Latest from activities (updates every outdoor GPS run)
- `race_vdot`: Computed from most recent race results (updates per race)
- `effective_vdot`: Weighted blend, preferring race_vdot when recent (<8 weeks)

### 4. Objectives as computed projections (not manually created goals)

Current goals table gains three columns:
- `derivation_source TEXT` — 'auto_daniels', 'auto_distance', 'auto_timeline', 'manual'
- `auto_value REAL` — system-derived target (always computed, even if overridden)
- `is_override BOOLEAN DEFAULT 0` — true when user manually set target_value

Objective computation: `required (Daniels) − current (fitness profile) ÷ time remaining = weekly/monthly target`.

Achievability: `current + (trend × months_remaining) vs required`. Three levels:
- ✓ On track (projected value meets requirement)
- ⚠ Tight (projected value within 5% of requirement)
- ✗ At risk (projected value below requirement — adjust target time or extend timeline)

### 5. Checkpoint races as fitness calibration

Pre-target races get a `derived_target_time` computed via Riegel back-calculation from the target race. This is NOT stored in the database — it's computed at display time from the current target.

When a checkpoint race is completed:
1. Compute VDOT from actual result
2. Update effective_vdot in fitness profile
3. Recalculate target race prediction (more accurate with fresh data)
4. Show: "Your S25 result (22:15) gives VDOT 45.5, projecting a 3:55 marathon. Previous projection was 3:52-4:27."

### 6. Dashboard redesign: metric cards + fitness model

Every dashboard element traces to the fitness model:

**Metric card format:**
```
LABEL           VALUE
action          target from derivation
[sparkline]     gap indicator
```

**What becomes a card** (single number + context):
- Readiness, RHR, HRV, stress/battery → Body cards
- Volume, Z2 compliance, runs/week → Training cards
- VO2max/VDOT, weight → Objective cards with gap-to-target

**What stays as a chart** (trend shape is the story):
- Efficiency trend (aerobic engine trajectory)
- Prediction trend (VDOT + Riegel over time)
- Weight trajectory (long-term body comp)
- ACWR trend (spike/recovery pattern)
- Sleep composition (stacked bars)

### 7. Global 5-zone color palette

5 zones, each distinct:
```
Z1 Recovery   = #93c5fd (blue-300)
Z2 Easy       = #60a5fa (blue-400)
Z3 Moderate   = #fbbf24 (amber-400)
Z4 Hard       = #f97316 (orange-400)
Z5 Very Hard  = #ef4444 (red-400)
```

Run types aligned: easy=Z2, tempo=Z3, intervals=Z4, long=#34d399 (emerald), race=#c084fc (purple).

All colors ≥60% opacity on #07070c. Font size 12px minimum. Max 2 datasets per chart.

### 8. Build on post-archive foundations

- **Apple Health import**: Body comp for weight objectives. Already auto-populates calibration.
- **fit races add/update/delete**: Foundation for `fit target set` — race CRUD already exists.
- **track_running/trail_running**: All queries already handle these types.
- **Coaching history**: When target changes, AI coaching can reference previous recommendations.
- **Prediction scaling to target_km**: Already works — `fit target set` just changes which race `get_target_race()` returns.
- **Plan adherence zone compliance**: Zone targets from objectives feed into adherence evaluation.

## Risks / Trade-offs

**[VDOT accuracy]** Daniels tables assume well-trained runners. An undertrained runner's 5K VDOT overpredicts marathon time.
→ Mitigation: Show confidence level based on training age + consistency. Weight race VDOT by distance similarity to target.

**[Objective churn]** Switching targets frequently recalculates objectives.
→ Mitigation: User overrides (`is_override`) persist. Only auto-derived values change.

**[Resilience measurement requires splits]** Drift onset needs .fit file data, which is opt-in.
→ Mitigation: Resilience dimension shows "insufficient data" until splits available. Other 3 dimensions work without splits.

**[Achievability is linear projection]** "Current + trend × time" assumes steady improvement.
→ Mitigation: Coaching AI adds judgment ("you've been inconsistent, linear projection is optimistic").
