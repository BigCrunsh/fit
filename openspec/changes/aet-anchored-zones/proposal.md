## Why

LTHR is the primary anchor for HR zones (after `lthr-default-zones`), and that's the right call for everything from Z3 upward — tempo, threshold, intervals — because Friel's %LTHR percentages are well-validated, ecosystem-standard, and LTHR is stable and reliably measurable.

But **Z2 ceiling is a different boundary**. Z2 = "easy aerobic" = below the body's actual aerobic threshold (AeT). Friel's "Z2 ceiling at 89% × LTHR" is a convention that happens to work for many runners, but for trained runners specifically it's generous: it includes upper-aerobic territory that's *not* truly fat-oxidation-dominant. For marathon base building specifically, the question of "how much time below AeT" matters more than "how much time below Friel-Z2-ceiling."

For this user (LTHR=172, observed easy runs at avg HR 144–148):

- Friel Z2 ceiling: 89% × 172 = **153 bpm** — comfortably above the user's easy efforts (good — alerts don't false-fire).
- Likely AeT: 80% × LTHR ≈ **138 bpm** — *below* the user's easy efforts. The user is regularly running 6–10 bpm above probable AeT on "easy" days.

That gap is hidden by the Friel model. AeT-refined Z2 ceiling would surface it — without changing any other zone boundary.

This change subsumes Part C of the archived `recalibrate-hr-zones` proposal.

## What Changes

### AeT becomes a calibrated metric (does not replace LTHR)

A new `aet` row type in the `calibration` table — same shape as `max_hr`, `lthr`, `weight`, `vo2max`. The `calibration-history` change covers the schema additions (flags, confidence). This change adds:

- `aet` to `STALENESS_THRESHOLDS` (proposed: 56 days, same as LTHR — AeT shifts during build phases but not weekly)
- `aet` to `RETEST_PROMPTS`: *"Run a 15+km steady-pace effort to derive AeT from heart-rate drift. See `aet-drift-test-instructions`."*
- `aet` to `get_calibration_status()` so it shows up in `fit doctor` and the attention panel
- `fit calibrate aet <value>` CLI: explicit manual override (sets `confidence='high'`)

### AeT refines Z2 ceiling only

`compute_hr_zones()` SHALL accept an optional `aet` argument. When provided, Z2 ceiling is set to AeT directly. Z3 / Z4 / Z5 boundaries continue to derive from %LTHR (Friel) — AeT does NOT replace LTHR for any other boundary.

The fallback chain for Z2 ceiling becomes:

1. AeT (when calibrated)
2. 85% × LTHR (Friel's *lower* Z2 bound, more conservative than the 89% upper bound) — when LTHR is calibrated, no AeT
3. 70% × MaxHR — last resort

Once AeT lands, the zone math becomes:

| Zone | Lower bound | Source |
|---|---|---|
| Z1 | 0 | — |
| Z2 | 85% × LTHR | Friel lower Z2 (preserves a recovery vs easy distinction) |
| **Z2 ceiling = Z3 lower** | **AeT** (when calibrated) or **89% × LTHR** (fallback) | AeT or Friel |
| Z3 | (Z3 lower) | (continues) |
| Z4 | 95% × LTHR | Friel |
| Z5 | 100% × LTHR | Friel |

### AeT drift-test instructions (always available)

A new dashboard section linked from the AeT calibration row's "Not measured" prompt, and from the Needs Your Attention panel, and from `fit calibrate aet --help`. The instructions cover:

- **Protocol**: 15+km running activity, constant target pace, flat terrain, fueled, well-hydrated, moderate temperature (<20°C), not within 24h of a hard session
- **What the system measures**: pace stddev across splits (must be <15 sec/km to qualify as "steady"), first-half avg HR vs second-half avg HR (distance-weighted), drift percentage
- **Interpretation**: drift <5% → pace was below AeT (lower bound), drift 5–7% → at AeT (direct estimate), drift >7% → above AeT (upper bound)
- **Iterative refinement**: 2–3 drift tests across different paces bisects to a confident AeT value

### AeT auto-derive from steady-pace long runs

The sync pipeline SHALL scan running activities ≥12km with per-km splits for "steady" candidates (pace stddev <15 sec/km, after excluding the first km warmup and the last km cooldown). For each candidate:

```
first_half_hr  = mean(splits[1 .. N/2].avg_hr,  weighted by distance)
second_half_hr = mean(splits[N/2 .. N-1].avg_hr, weighted by distance)
drift_pct      = (second_half_hr - first_half_hr) / first_half_hr * 100

if drift_pct < 5: AeT > avg_hr_of_run (lower bound, flag: lower_bound)
if 5 <= drift_pct <= 7: AeT ≈ avg_hr_of_run (direct estimate)
if drift_pct > 7: AeT < avg_hr_of_run (upper bound, flag: upper_bound)
```

The bisection across recent candidates (8-week window) yields the active AeT. Method = `drift_test`. Confidence per the uniform rubric (`calibration-history` change): single direct estimate → `medium`, two within ±3 bpm → `high`.

### Falls back gracefully when AeT is missing

The dashboard SHALL NOT block on AeT data. With no `aet` row, Z2 ceiling uses Friel's 89% × LTHR — the same behavior as `lthr-default-zones` provides. The presence of the AeT prompt on the dashboard is the gentle reminder; the absence of data doesn't degrade existing functionality.

## Capabilities

### Modified Capabilities

- `fitness-profile`: gains `aet` as a tracked calibration metric with its own staleness threshold and retest prompt; Z2 ceiling derives from AeT when calibrated, falls back to %LTHR otherwise; Z3/Z4/Z5 boundaries remain LTHR-anchored regardless.
- `data-ingestion`: sync gains a steady-pace candidate detector and AeT auto-derive path that writes calibration rows from qualifying long runs.
- `dashboard`: gains the AeT drift-test instructions section; Profile-tab Calibration History (from the `calibration-history` change) gains an AeT chart.

## Impact

- **Code**:
  - `fit/calibration.py`: `aet` added to `STALENESS_THRESHOLDS`, `RETEST_PROMPTS`, `get_calibration_status()`. New helper `extract_aet_from_steady_run(activity, splits, current_aet) -> tuple[float, str] | None` returning `(value, flag)` where flag is one of `direct_estimate`, `lower_bound`, `upper_bound`.
  - `fit/analysis.py`: `compute_hr_zones()` gains optional `aet` arg; Z2 ceiling logic updates per the fallback chain.
  - `fit/sync.py`: new step after enrich that walks new running activities with splits, calls `extract_aet_from_steady_run`, writes calibration rows.
  - `fit/cli.py`: `fit calibrate aet <value>` subcommand (extending the existing `fit calibrate`).
  - `fit/report/sections/cards.py`: new `_aet_instructions()` section builder.
  - `fit/report/templates/dashboard.html`: AeT instructions section (anchored as `#aet-instructions`).
- **Schema**: `aet` is a new value of the existing `metric` column on `calibration`. No table changes. Depends on `calibration-history` having shipped (for `flags`, confidence rubric).
- **Tests**:
  - `tests/test_calibration.py::TestAeTExtraction` — drift % calculation, direct/lower/upper bound classification, candidate detection (pace stddev), distance-weighted HR averaging.
  - `tests/test_analysis.py::TestHRZones::TestAetCeiling` — Z2 ceiling switches to AeT when calibrated; falls back to 89% × LTHR otherwise.
- **Data**: no historical backfill — the AeT instructions tell the user to do a drift test next time they're scheduled for a long run. Auto-derive walks new activities going forward; can be re-run over history with a one-off `fit backfill aet` command (similar pattern to existing `fit backfill rpe`).
- **External**: none.

## Risks / Trade-offs

- **AeT measurement is noisy.** Two drift tests on different days can disagree 3–5 bpm due to hydration, temperature, glycogen, pacing precision. The proposal's "two within ±3 bpm → high confidence" rule will rarely fire in practice. Realistic expectation: most AeT calibrations stay `medium`. **Mitigation**: when AeT confidence is `medium`, the Z2 ceiling display shows a "±3 bpm" margin. When `low` (one estimate plus disagreement), Z2 ceiling falls back to 89% × LTHR.
- **AeT shifts during a build.** A 12-week base build can move AeT 5+ bpm. Anchoring zones to a moving target creates retroactive zone changes when `fit recompute --force` runs. **Mitigation**: the dashboard shows the AeT-calibration-date alongside the value; zone-distribution charts annotate the AeT change so the user can see when "easy" got harder.
- **Steady-pace detection threshold (15 sec/km) is a guess.** Pace stdev on flat road runs is typically 5–10 sec/km for trained runners; trail/hill runs much higher. **Mitigation**: tune after dogfooding. Make threshold configurable in `analysis.aet_steady_pace_stddev_sec`.
- **AeT auto-derive could write spurious rows from fatigue-driven negative splits.** A run with first-half avg 138, second-half avg 130 (negative drift) is not a valid AeT estimate. **Mitigation**: require drift_pct >= 0 for direct/upper-bound classification; drift_pct < 0 → no row written.

## Open Questions

1. Steady-pace threshold (15 sec/km) — tune after dogfooding.
2. Minimum distance — 12 km is the proposal default; should it be longer (15 km) to ensure the drift signal isn't drowned by acclimatization noise?
3. Should AeT be derivable from races, or only from non-race long runs? Races have hydration / temperature / pacing variables that confound drift.
4. Active-window length for bisection — 8 weeks is proposal default; tune.
5. What does `fit calibrate aet <value>` do if there are existing auto-derived AeT rows? Overwrites active selection (manual override always wins)?
