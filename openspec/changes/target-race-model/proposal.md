# Target Race Model — Fitness-First Design

## Mental Model

```
┌─────────────────────────────────────────────────────────────────┐
│                        YOUR RUNNING                             │
│                                                                 │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│  │   GARMIN     │     │  FIT DAYS   │     │  YOU (daily) │      │
│  │  watch data  │     │   scale     │     │  fit checkin │      │
│  └──────┬───────┘     └──────┬──────┘     └──────┬──────┘       │
│         │                    │                    │              │
│         └────────────┬───────┴────────────────────┘              │
│                      ▼                                           │
│              ┌───────────────┐                                   │
│              │   fit sync    │  ← one command, everything updates│
│              └───────┬───────┘                                   │
│                      ▼                                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              FITNESS PROFILE (4 dimensions)                │  │
│  │                                                            │  │
│  │  Aerobic ████████░░  Threshold ██████░░░░                  │  │
│  │  Economy ███████░░░  Resilience ████░░░░░░                 │  │
│  │                                                            │  │
│  │  VDOT: 46 (from S25 race) · Garmin VO2max: 49             │  │
│  └───────────────────────┬───────────────────────────────────┘  │
│                          ▼                                       │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  TARGET RACE: Berlin Marathon sub-4:00 in 173 days       │   │
│  │                                                           │   │
│  │  OBJECTIVES (auto-derived, achievability projected):      │   │
│  │  VO2max    49/50  ✓ achievable in 1 month                │   │
│  │  Weight    78.6/75 ⚠ tight (need -0.5kg/mo for 6 months)│   │
│  │  Consistency 0/12wk ⚠ must start now                     │   │
│  │  Resilience 12/30km ⚠ progressive build needed           │   │
│  │                                                           │   │
│  │  CHECKPOINTS:                                             │   │
│  │  S25 in 12d → your target: 22:00 · marathon pace: 22:30  │   │
│  │  Tierparklauf in 159d → derived target: 44:00             │   │
│  └──────────────────────────┬───────────────────────────────┘   │
│                             ▼                                    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  DASHBOARD: "so what?" for every metric                   │   │
│  │                                                           │   │
│  │  Today:    What to do today (from readiness + plan)       │   │
│  │  Training: Are you training right? (vs phase targets)     │   │
│  │  Body:     Is your body recovering? (trends, not numbers) │   │
│  │  Fitness:  Is your engine improving? (4 dimensions)       │   │
│  │  Coach:    AI coaching (judgment the rules can't provide) │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
│  COACHING (Claude AI — the judgment layer):                      │
│  "Given your 0-week consistency and the S25 in 12 days,         │
│   focus on 3 easy runs this week. Override the Runna tempo."    │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### User Flow (optimized for convenience)

```
DAILY (30 seconds):
  fit sync              ← pulls everything, recomputes profile, generates dashboard
  open dashboard        ← 10-second glance: what to do today
  fit checkin           ← after training: RPE, legs, sleep quality (1 minute)

WEEKLY (5 minutes):
  Ask Claude for coaching ← AI reads fitness profile, gives judgment
  fit report            ← regenerates with fresh coaching notes

AFTER A RACE (automatic):
  fit sync              ← detects race result, computes VDOT, updates projections
                           "S25 result: 22:15 → VDOT 45.5 → marathon now 3:55"

WHEN CHANGING GOALS (rare, intentional):
  fit target set 35     ← switch to HM. Objectives recalculate. Dashboard adapts.
  fit races add         ← add a new race to the calendar
```

Everything else is automatic. No `fit report` needed after sync (auto-generated).
No manual objective updates. No manual VDOT calculation. The system computes,
the dashboard displays, Claude interprets.

## Why

The dashboard shows metrics without answering "so what?" because there's no model connecting observations to goals. Charts display VO2max, efficiency, zone distribution as independent data points, but the user has to mentally project: "Is VO2max 49 good enough for a sub-4 marathon in 173 days?"

The deeper problem: objectives (VO2max ≥50, weight ≤75kg) are manually created and static. They don't adapt when the target race changes, don't account for timing, and don't connect to the underlying fitness dimensions that sports science says determine race performance.

## The Model

### Fitness Profile (always tracked, race-independent)

Four dimensions of running fitness, each with observable indicators:

| Dimension | What it measures | How we track it |
|-----------|-----------------|-----------------|
| **Aerobic capacity** | Oxygen delivery ceiling | VO2max (Garmin), VDOT (from race results) |
| **Threshold** | Sustainable hard effort | LTHR, Z2 pace at HR ceiling, tempo pace |
| **Economy** | Speed per unit of effort | speed_per_bpm, cadence, stride length |
| **Resilience** | Resistance to fade over distance | Cardiac drift onset km, pace fade %, long run ceiling |

These are always tracked regardless of target race. They represent your actual fitness state.

Supporting indicators (body/recovery state):
- Weight, body fat % (body composition)
- RHR, HRV, readiness, sleep (recovery capacity)
- Consistency streak, weekly volume, Z2 compliance (training load)

### Target Race (the lens)

One race is the current training focus. It projects the fitness profile into race-specific requirements:

- **Required fitness**: Daniels inverse lookup — target_time + distance → minimum VDOT → per-dimension requirements
- **Time remaining**: Days to race
- **Gap analysis**: Current value vs required value per dimension
- **Achievability**: Current + (trend × time remaining) ≥ required?
- **Training phase**: What should training look like right now given the gap and timeline?

When target changes (marathon → HM), the lens changes but the fitness profile stays. Requirements recalculate. Some gaps close (HM needs less resilience), others open (HM pace needs higher threshold).

### Checkpoints (races before the target)

Races before the target are **measurement opportunities**, not independent goals. Each checkpoint:

- **Derived target time**: Riegel back-calculation from target race ("to be on track for sub-4 marathon, run this 10K in ~44:00")
- **User target time**: Manual override ("I want 45:00" — already on race_calendar)
- **Readiness signal**: "If you run X at this checkpoint, your target race projection updates to Y"
- **VDOT update**: The actual result gives a real VDOT data point — more reliable than Garmin's VO2max estimate

The S25 in 12 days isn't "a 5K goal" — it's "a fitness measurement that updates the marathon prediction."

### Objectives (fitness × target × time)

Objectives are computed projections, not manually created goals:

```
Objective = what the target race requires (from Daniels)
          − where you are now (from fitness profile)
          ÷ time remaining (from race_calendar)
          = what you need to achieve per week/month
```

Examples for Berlin Marathon sub-4:00 with 173 days remaining:
- **VO2max**: Need ≥50, have 49, trend +1/mo → achievable in ~1 month ✓
- **Weight**: Need ≤75, have 78.6, trend -0.5/mo → tight (75.6 at race) ⚠
- **Consistency**: Need 12 consecutive weeks, have 0 → must start now, exactly enough time ⚠
- **Resilience**: Need 30km without drift, current ceiling ~12km → progressive build over 20 weeks

When target switches to Müggelsee HM sub-1:47 with 194 days:
- **VO2max**: Need ≥52, have 49, trend +1/mo → need 3 months of consistent training ⚠
- **Weight**: Need ≤76, have 78.6, trend -0.5/mo → achievable in 5 months ✓
- **Consistency**: Need 8 weeks, have 0 → achievable ✓
- **Resilience**: Need 21km without drift, current ceiling ~12km → smaller gap than marathon ✓

Objectives carry over when target changes:
- **Auto-derived** (VO2max, volume, consistency): recalculate for new target
- **User-set** (weight): preserved, system shows both user target and derived suggestion
- **Historical**: old objectives become context ("when targeting marathon, needed VO2max 50")

## What Changes

- **Fitness profile module** (`fit/fitness.py`): Track 4 dimensions with trends. VDOT from race results. Achievability projections.
- **`fit target set <race_id>`**: Updates `goals.race_id` on all active goals + triggers objective re-derivation. No schema change needed for target selection (proven with the marathon→HM switch).
- **Objective derivation**: Auto-compute from Daniels + distance heuristics + timeline. Store with `derivation_source` and `auto_value` for override tracking.
- **Checkpoint enrichment**: Derive target times for upcoming races based on current target. Show readiness signal.
- **Dashboard redesign**: Metric cards with gap-to-target. Charts only where trend shape matters. 5-zone palette. Every element answers "so what?" via the fitness model.

## Capabilities

### New Capabilities

- `fitness-profile`: 4-dimension fitness model with VDOT tracking from race results, trend computation, and achievability projection.
- `objective-derivation`: Auto-derive objectives from target race + Daniels + timeline. Achievability assessment. User override support.
- `checkpoint-enrichment`: Derive target times for pre-target races. Show readiness signals. Update VDOT from results.
- `dashboard-redesign`: Metric cards over charts. "So what?" from fitness model. 5-zone palette. Readability.

### Modified Capabilities

- `race-model`: `fit target set/show/clear` CLI. Target via goals.race_id (no is_target flag).
- `coaching-signals`: Prediction adapts to target distance (already partially done). Confidence from training progression.
- `dashboard`: Every metric card shows: value + target (from derivation) + gap + achievability + action.

## Design Notes

- **VDOT > Garmin VO2max**: Daniels' VDOT from actual race results is more reliable than Garmin's wrist-based estimate. Each race updates VDOT. The fitness profile should track both but prefer VDOT when available.
- **Prediction improves over time**: Research shows prediction error drops after week 13 of structured training. Early confidence should be "low" with a specific note: "13 weeks until predictions stabilize."
- **Resilience is the 4th dimension**: Cardiac drift onset and pace fade measure durability — critical for marathon but less for 5K. The split analysis we built is actually a resilience measurement tool.
- **Coaching AI adds the judgment layer**: The fitness model computes gaps and achievability. Claude interprets: "Given your 0-week consistency, the VO2max gap is achievable but the consistency gap is the bottleneck. Focus there."
- **Checkpoint races as VDOT calibration**: The most valuable thing about running S25 isn't the time — it's the VDOT update. A 22:00 5K = VDOT 46, which projects to 3:52 marathon. A 23:00 = VDOT 43, projecting to 4:05. The checkpoint result is a prediction update.
