## Why

The current model has races and goals as separate concepts loosely coupled by a `race_id` FK on the goals table. The "target race" is inferred by finding which race goals point to, and objectives (VO2max, weight, streak) are generic — not derived from the target race's requirements. This creates confusion: stepping stone races (S25 5K, Tierparklauf 10K) appear as objectives, the dashboard can't adapt prediction charts to different target distances, and changing the target race requires manual SQL updates to re-link goals.

The race should be the anchor. You set "Berlin Marathon sub-4:00" as the target, and objectives derive automatically from that: VO2max ≥50 (Daniels), weight ≤75kg (user-set), consistency ≥12 weeks (distance-derived). When the target changes, objectives recalculate.

## What Changes

- **Add `is_target` flag to `race_calendar`** — exactly one race is THE target at any time. All other registered races are waypoints/stepping stones.
- **Auto-derive objectives from target race** — when a target is set, the system generates objectives based on target_time + Daniels tables + training science + current fitness level.
- **User-overridable objectives** — auto-derived values are defaults; user can override (e.g., custom weight target). Overrides persist when target changes.
- **Retire generic goals table** — goals become race-specific objectives. The goals table schema changes to reference the target race explicitly and track derivation source (auto vs manual).
- **New CLI commands** — `fit target set <race_id>`, `fit target show`, `fit target objectives` to manage the target race and review/edit objectives.
- **Dashboard + prediction charts adapt** — prediction trend, race prediction table, Forecast section title, and pacing strategy all read from target race distance (marathon, half, 10K).
- **`get_target_race()` simplified** — reads `is_target = 1` directly instead of inferring from goal FK chains.

## Capabilities

### New Capabilities

- `target-race-lifecycle`: Setting, switching, and managing the target race. Migration to add `is_target` column. CLI commands. Exactly-one constraint enforcement. Waypoint race display.
- `objective-derivation`: Auto-deriving objectives from target race + target time using Daniels VDOT tables, distance-based volume needs, and timeline-based consistency requirements. User override support. Recalculation on target change.
- `adaptive-predictions`: Prediction charts and tables adapt to the target race distance. Marathon predictions when target is marathon, half marathon predictions when target is HM, etc. Riegel formula uses target_km from race_calendar.

### Modified Capabilities

- `race-model`: `race_calendar.is_target` flag replaces the current goal→race FK inference chain. `get_target_race()` simplified.
- `goal-progress`: Objectives section reads from derived objectives, not generic goals. Progress bars and compliance targets are race-specific.

## Impact

- **User-facing**: `fit target set 36` makes Berlin Marathon the anchor. Objectives auto-populate. Dashboard immediately reorients.
- **Data model**: Migration adds `is_target` to race_calendar, adds `derivation_source` and `auto_value` to goals for tracking overrides.
- **No breaking changes to existing data** — migration sets `is_target = 1` on the race that current active goals reference (preserves existing behavior).

## Design Notes

- **Objective derivation from Daniels**: sub-4:00 marathon → VO2max ≥50 (from Daniels table inverse lookup). Sub-1:47 HM → VO2max ≥52. The derivation is a lookup, not a guess.
- **Carried-over vs race-specific objectives**: Weight target is user-set and carries over when target changes. VO2max target is auto-derived and recalculates. Consistency target scales with race distance (marathon: 12wk, HM: 8wk, 10K: 6wk).
- **Waypoint races as milestones**: Stepping stone races (S25, Tierparklauf) become milestone markers on the journey timeline, with their own target times but not as dashboard objectives.
- **Phase targets adapt**: When target race changes, training phase Z2/volume targets should also recalculate (longer races need more Z2 base).
