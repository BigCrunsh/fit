## Why

The default HR-zone model is `%MaxHR` with the textbook 60/70/80/90 percentages. For a trained runner with high LTHR relative to MaxHR (here: LTHR 172, MaxHR 195 → LTHR is 88% of MaxHR vs the ~75% the model assumes), the textbook %MaxHR Z2 ceiling lands ~17 bpm below actual aerobic territory. Every "easy" run gets classified as Z3 or worse and the system fires false "All Runs Too Hard" alerts. The data confirms this — recent easy runs at avg HR 144–148 bpm are 84–86% of LTHR (squarely Z2 under Friel), but 74–76% of MaxHR (Z3 under the %MaxHR model).

A separate `aet-anchored-zones` change will eventually make AeT (aerobic threshold) the primary anchor, but that requires field data the user has not yet collected (the drift test). Until then, `%LTHR (Friel)` is the right default: LTHR is already calibrated (172 bpm, two readings 1 bpm apart over 6 months), Friel's model is the de facto standard for serious runners, and the result puts the user's actual easy efforts in Z2.

## What Changes

- `config.yaml` template default: `zone_model: lthr` (was `max_hr`). `${FIT_ZONE_MODEL:-lthr}` so env override still works.
- `config.local.yaml` (user-personal): switch `zone_model` to `lthr` for the user running this change.
- `compute_hr_zones()` primary-selection fallback chain becomes: **AeT → LTHR → %MaxHR**. Today's `zone_model: max_hr | lthr` switch is preserved as an explicit user override; the fallback only applies when `zone_model` is unset.
- `%MaxHR` continues to be computed in parallel as a diagnostic (`hr_zone_maxhr` column). Existing dashboard charts that show both models keep working.
- `weekly_agg.z12_pct` / `z45_pct` recompute against the new primary zone. `fit recompute --force` re-zones all 231 historical activities.
- The "All Runs Too Hard" alert thresholds remain unchanged. The alert relies on `z12_pct` from `weekly_agg`, which now correctly reflects time in true aerobic zones.

## Capabilities

### Modified Capabilities

- `fitness-profile`: default zone_model becomes `lthr`. Primary `hr_zone` selection has a documented fallback chain (AeT → LTHR → %MaxHR).
- `dashboard`: zone-mix charts and badges render against LTHR-anchored zones by default; per-chart def-toggles updated to reflect new ceiling values.

## Impact

- **Code**: `fit/analysis.py` (`compute_hr_zones` primary selection rule), `config.yaml` (template default).
- **Schema**: none.
- **Tests**: extend `tests/test_analysis.py::TestHRZones` to cover the new fallback chain. Existing LTHR/Max tests already cover both models.
- **Data**: one-time `fit recompute --force` to re-zone historical activities. Many runs flip from Z3 to Z2 — the dashboard should call out the recalibration date so trends pre/post don't look like a behavior change.
- **External**: none.

## Risks / Trade-offs

- **Historical analyses shift retroactively.** Weekly Z1+Z2 % jumps. Trends pre/post look discontinuous. Mitigation: annotate the recalibration date on the zone-distribution chart so a reader can see when the model changed.
- **Removes the strict `Z2 ceiling 134 bpm` design intent in CLAUDE.md.** That ceiling reflected the user's earlier deliberate choice to use the conservative %MaxHR model. This change supersedes that choice; CLAUDE.md should be updated to reflect the new default.
- **Falls back to %MaxHR when LTHR is missing.** New users with no LTHR cal get the textbook behavior. Acceptable — the fallback is by design temporary until the user does any 10K+ race (which triggers LTHR auto-extract).

## Open Questions

1. Update `CLAUDE.md`'s "Zone Model" section to reflect that LTHR is now primary? (Likely yes — the file is canonical project doc.)
2. Should `fit calibrate lthr` immediately trigger `fit recompute --force`? Today it does not.
