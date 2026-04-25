## Why

The HR zone system has three calibration issues — two factual, one definitional. They compound: the wrong max HR shifts every %MaxHR boundary downward, the dual-model preference creates a 19 bpm Z2-ceiling gap, and there is no anchored aerobic threshold (AeT) to settle which model is right for a given run. Result: easy-day runs get classified inconsistently between the two models, and the user does not trust either zone label.

A fourth issue surfaces underneath: calibration refresh is manual for `max_hr` (the user has to spot a new max in race data and run `fit calibrate max_hr <v>`), inconsistent for confidence levels (LTHR auto-extract always writes `medium` regardless of agreement with prior readings), and the calibration table has no way to record-but-flag implausible values — it relies on rejection at the prompt.

This proposal parks the fix for after `import-rpe-from-garmin`. Implementation should not start until the AeT drift test (see Issue 3) has been run and produces a real personal AeT estimate.

## Background — Evidence as of 2026-04-25

**Issue 1 — Max HR is undercounted (factual).**
Stored: `192` (`config.profile.max_hr`, manual, "from training history").
Observed in race data:
- 195 bpm on 2026-04-15
- 194 bpm on 2026-04-19
- Several races in 190–192 range

True max HR is at least 195, likely 195–198. Every %MaxHR boundary today is computed from 192 and is therefore biased low by 2–6 bpm. Z2 ceiling currently 134 (70% × 192) → would be 136 at max=195, 138 at max=198.

**Issue 2 — LTHR confidence should bump from medium → high (factual).**
Two independent race-extracted readings within 1 bpm:
- 2025-10: LTHR ≈ 172
- 2026-04: LTHR ≈ 171

That's a robust calibration. The `calibration` table already supports confidence levels (`migrations/001_schema.sql:163`). When the next LTHR row is inserted (post-`import-rpe-from-garmin`, from the coaching-signals flow), it SHALL be inserted with `confidence = 'high'`. No code change required — `fit calibrate lthr <value>` already writes `'high'`; this is a directive for whoever (coach skill, manual entry) writes the row.

**Issue 3 — The two zone models genuinely disagree (definitional, not calibration).**

| | Z2 ceiling | Source |
|---|---|---|
| %MaxHR (today) | 134 bpm | 70% × 192 (standard %MaxHR) |
| %LTHR (Friel) | 153 bpm | 89% × 172 (Friel %LTHR) |
| **Gap** | **19 bpm** | |

Concrete impact, recent runs:

```
Date         avg_hr   %MaxHR model   %LTHR model
2026-04-24   143      Z3             Z2
2026-04-22   142      Z3             Z2
2026-04-17   146      Z3             Z2 (just barely)
2026-04-09   148      Z3             just over Z2
```

Under %LTHR these are textbook easy aerobic. Under %MaxHR none of them are. Both formulas are legitimate — they're answering different questions. %MaxHR's "Z2" represents deeply aerobic / fat-oxidation. %LTHR's "Z2" represents upper aerobic / sub-threshold. The truth — actual aerobic threshold (AeT) — is the question that matters and neither formula tells us. AeT for trained runners typically 75–85% of LTHR, which here is 129–146 bpm — closer to the %MaxHR ceiling (134) than the %LTHR ceiling (153), but probably a bit higher than 134.

## What Changes

The proposal has four independently shippable parts. Parts A, B, C depend on data from the AeT drift test (described below). Part D is the calibration-refresh substrate that the others ride on top of and can ship first.

**Part A — Update max HR calibration.**
- Insert a new `calibration` row for `max_hr` with the observed-max value (currently 195 from 2026-04-15 race; re-evaluate at proposal start in case higher values appear). With Part D shipped, this happens automatically on the next sync; no manual entry needed.
- Trigger `fit recompute` to re-classify `hr_zone_maxhr` and `effort_class` for all activities.
- Update `config.yaml` `analysis.easy_hr_ceiling` and `analysis.speed_per_bpm_hr_range` if/when the AeT result lands (these are independently tuned, not auto-derived from `max_hr`).

**Part B — Bump LTHR confidence on next insert.**
- With Part D shipped, the LTHR auto-extract path in `fit/sync.py` evaluates `confidence` against the prior reading per the explicit rubric (see Part D), so the medium→high bump happens automatically when the next race-extracted LTHR comes in within ±2 bpm of the existing 171–172. No manual directive needed.

**Part C — Introduce AeT as the anchored Z2 ceiling, replace the dual-model picker.**
- Add `aet` to `config.profile` (single bpm value, sourced from the drift test).
- Add a new `aet` calibration metric in the `calibration` table (parallel to `max_hr`, `lthr`).
- New `_classify_zone_aet()` (or extend `_classify_zone`) that uses AeT as the **Z2 ceiling** anchor; remaining boundaries derived from AeT (Z3 ceiling = AeT × 1.10 for tempo, etc. — exact derivation TBD in design.md).
- Replace the `zone_model: max_hr | lthr` config with a single AeT-anchored model. Keep `_classify_zone_lthr` and `_classify_zone` as inputs/diagnostics for the dashboard's "model comparison" view, but `hr_zone` (primary) is AeT-anchored.
- Remove the hardcoded `easy_hr_ceiling: 134` and `speed_per_bpm_hr_range: [115, 134]` from `config.yaml.analysis` — derive both from `aet` calibration so they update automatically.

**Part D — Calibration auto-refresh, flags, and explicit confidence semantics.**

*D1 — Always record, never reject.* Add a `flags TEXT` column to the `calibration` table (JSON array of tags). Auto-extracted readings are stored even when implausible or anomalous; flags explain why the row got the confidence it did. Flag taxonomy:

| Flag | When it fires |
|---|---|
| `implausible_value` | outside physiological range (e.g., max_hr >215 or <140 for adult; LTHR <130) |
| `spike` | activity-level max far above sustained max — sub-1-min anomaly suggesting strap glitch (window/threshold TBD in design) |
| `unexpected_direction` | max_hr drops >2 bpm vs prior, OR LTHR drops >5 bpm vs prior, in <12 weeks (real age decline is gradual; sudden drops usually mean under-recovery or measurement noise) |
| `agrees_with_prior` | within ±2 bpm of prior reading from the same method |
| `weak_context` | extracted from a non-race / non-hard-effort activity |

Calibrations are bidirectional — max HR drifts down with age (~1 bpm/year), LTHR can drop after detraining. Direction asymmetry is wrong; the `unexpected_direction` flag captures the rare-but-real case where a sudden drop is suspicious without rejecting it.

*D2 — Auto-refresh during sync.* Three new auto-extract paths in `fit/sync.py`, mirroring the existing LTHR pattern:

- **`max_hr`**: scan running activities in the sync window; if `max(activities.max_hr) > active.value + 1`, insert a new calibration row. `method='race_extract'` if the source activity is a race, `method='activity_max'` otherwise.
- **`lthr`**: existing extractor stays, but confidence becomes a function of agreement with prior, not always `medium`.
- **`aet`**: new extractor (D3 below) walks recent steady-pace long runs and bisects.

*D3 — AeT auto-derive from steady-pace long runs.* Per-km splits flow for every running activity already (`fit/sync.py:248-269` — universal, not gated on `download_fit_files`). Detection at sync time:

```
Candidate per activity:
  - type='running', distance >= 12km, splits available
  - pace stdev across splits < threshold (e.g., 15 sec/km — TBD)

For each candidate:
  first_half_hr  = mean(splits[0:N/2].avg_hr,  weighted by distance)
  second_half_hr = mean(splits[N/2:].avg_hr,   weighted by distance)
  drift_pct      = (second_half - first_half) / first_half * 100
  pace_avg       = total_distance / total_time

Bisection across recent steady runs (8-week window):
  drift <5%   → AeT > avg_hr of run (lower bound)
  drift 5-7%  → AeT ≈ avg_hr (direct estimate)
  drift >7%   → AeT < avg_hr (upper bound)

Active AeT = best estimate from window, with confidence reflecting:
  - one direct estimate, plausible value → medium
  - ≥2 direct estimates within ±3 bpm → high
  - only bounds, no direct estimate → low (insufficient_data flag)
```

*D4 — Explicit confidence semantics, applied uniformly across all metrics.*

| Confidence | Definition |
|---|---|
| **high** | (a) two corroborating readings within ±2 bpm from hard-effort contexts, OR (b) explicitly set by user via `fit calibrate <metric> <value>` |
| **medium** | single recent reading from a hard-effort context (race, time trial, hard interval), plausible value, no flags |
| **low** | any of: `implausible_value`, `spike`, `unexpected_direction`, `weak_context`, or stale (past `STALENESS_THRESHOLDS`) |

Two practical rules that fall out of this semantics:
- **Active calibration selection** must prefer the highest-confidence non-flagged row, not just `MAX(date)`. Today `get_active_calibration()` is date-only ([fit/calibration.py:24-31](fit/calibration.py#L24-L31)) — a spurious low-confidence row would replace a clean medium one. Worth fixing.
- **Confidence is a property of the row, not of the metric.** A `low` row coexists with a prior `medium` / `high` row in history. The "active" pointer is just the chosen one for downstream computation.

*D5 — Calibration history graph (dashboard).* New view per metric — line chart over time with:
- Dots colored by confidence (high=solid, medium=hollow, low=red ring)
- Tooltip shows method + flags + source activity
- Annotation band for staleness threshold (active row turns red when it crosses)
- CLI counterpart: `fit calibrate history <metric>` — sparkline + table

The aha lives here: when you see two LTHR readings 1 bpm apart in October 2025 and April 2026, the "high" status is visually obvious instead of being a rule you have to remember.

**The AeT drift test (data-collection, not code):**
On a 15km steady-pace run, hold a constant pace (e.g., 7:00/km) for the full distance. Compare avg HR of first half vs second half:
- Drift <5% → pace was below AeT
- Drift 5–7% → pace was at AeT
- Drift >7% → pace was above AeT

Bisecting across two or three steady runs (or one run + Garmin's HR-vs-time curve) yields a personal AeT estimate. With Part D3 shipped, this happens automatically — every long steady run becomes a calibration data point. The first run still produces a `medium`-confidence AeT; agreement across runs bumps it to `high`.

## Capabilities

### New Capabilities

(none — all changes extend existing capabilities)

### Modified Capabilities

- `fitness-profile`: gains an `aet` calibration metric and AeT-anchored zone model; gains explicit `low | medium | high` confidence semantics applied uniformly across `max_hr` / `lthr` / `aet` / `weight` / `vo2max`; gains a `flags` column on calibration rows so anomalous readings are recorded-and-flagged instead of rejected. `zones_max_hr` and `zones_lthr` configs become diagnostic-only inputs; the primary `hr_zone` is AeT-anchored. `get_active_calibration()` selection becomes confidence-aware (no longer pure `MAX(date)`).
- `data-ingestion`: sync gains three auto-refresh paths — `max_hr` from observed activity max, `lthr` (existing extractor, with confidence now a function of agreement), and `aet` from steady-pace long-run drift detection. `fit recompute` is the trigger after any calibration update. May want a `fit calibrate` post-step that auto-runs recompute.
- `coaching-signals`: LTHR confidence comes from the explicit rubric in Part D4, not a hardcoded `medium`.
- `dashboard`: zone bands on HR-over-time charts shift; "easy/Z2" plot annotations and the speed_per_bpm_z2 trend chart re-render against the new AeT-anchored ceiling. New calibration history view per metric (line chart + flag annotations + staleness band) plus `fit calibrate history <metric>` CLI counterpart.

## Impact

- **Code**: `fit/analysis.py` (zone classification refactor), `fit/calibration.py` (add `aet` metric, flag computation, confidence rubric, confidence-aware `get_active_calibration`), `fit/sync.py` (max_hr auto-refresh + AeT auto-derive; LTHR confidence rule), `fit/cli.py` (`fit calibrate aet <value>`, `fit calibrate history <metric>`), `config.yaml` (new field + retire two analysis ceilings), `fit/report/sections/` + `dashboard.html` (calibration history charts).
- **Schema**: one migration adding `flags TEXT` to `calibration`. `aet` itself needs no schema change — just a new value of the `metric` column.
- **Tests**: extend `test_analysis.py` for AeT-anchored zone classification, `test_calibration.py` for `aet` + flag taxonomy + confidence rubric + confidence-aware active selection, `test_sync.py` for the three auto-refresh paths, regression tests covering the ~600-activity recompute (zones may flip; verify via fixtures).
- **Data**: one-time recompute over all activities after AeT lands. Auto-refresh paths backfill calibration history from existing `activities.max_hr` and per-km splits — no external API calls beyond what sync already does.
- **External**: none. All calibration values come from your own runs.

## Risks / Trade-offs

- **AeT estimate is noisy from a single drift test.** Mitigation: run the test 2–3 times across different conditions before committing; allow `fit calibrate aet --confidence medium` for the first reading, bump to `high` after agreement.
- **Zone re-classification will move many runs between Z2 and Z3.** Historical narratives, weekly load mix, "easy/quality" ratios will all shift retroactively. This is correct (the old labels were wrong) but the dashboard should call out the recalibration date so trends pre/post don't look like a behavior change.
- **Dropping the `zone_model: max_hr | lthr` switch is a config breaking change.** Acceptable — the config file is personal, no external consumers.
- **AeT may itself drift over a season as fitness improves.** A 75–85% × LTHR sanity check at recompute time would warn if AeT and LTHR disagree wildly (e.g., AeT > 90% LTHR → almost certainly stale).

## Open Questions (resolve in design.md when starting work)

1. Exact max HR value to write — re-check race data at start of work; may have moved past 195 by then.
2. AeT-derived Z3/Z4/Z5 boundary formulas — symmetric derivation around AeT, or anchor each zone independently? Likely: Z2 ceiling = AeT, Z4 floor = LTHR, Z3 = AeT–LTHR span, Z5 floor = LTHR + small offset.
3. Should `fit calibrate` auto-trigger `fit recompute`, or remain manual? Today it's manual.
4. Keep `zones_max_hr` and `zones_lthr` in config as diagnostic inputs for the dashboard's model-comparison view, or remove them entirely?
5. Migration story for the `easy_hr_ceiling` / `speed_per_bpm_hr_range` config keys — soft-deprecate (read AeT, fall back to old) or hard-remove?
6. **Flags storage shape** — `flags TEXT` JSON array (flexible, easy to extend) vs structured boolean columns `is_spike`, `is_directional_anomaly`, etc. (queryable, rigid). JSON is the assumed default in this proposal.
7. **Spike detection threshold** — what counts as a "spike" in `activities.max_hr`? Need to define the window (sub-minute peak vs sustained max) and how to detect it given that `activities.max_hr` is already Garmin-smoothed. May need to look at per-km split max HRs vs activity-level max.
8. **AeT steady-pace detection threshold** — pace stdev cutoff for "steady" candidate runs (proposal sketches 15 sec/km but this is a guess). Also: minimum distance (12km is a starting point), and whether to weight by elevation profile (a steady-pace run on rolling terrain has HR drift from elevation, not from AeT).
9. **AeT freshness window** — proposal suggests 8 weeks of recent steady runs. Too short and a single bad run dominates; too long and fitness changes get washed out.
10. **Direction-anomaly thresholds** — proposal suggests >2 bpm max_hr drop and >5 bpm LTHR drop in <12 weeks trigger `unexpected_direction`. These numbers are calibrated to age-decline expectations (~1 bpm/yr for max_hr) but worth reviewing.
11. **Confidence-aware active selection rule** — ties (e.g., multiple `high` rows from different dates) — pick most recent? Highest method-priority (race > time_trial > activity_max)? Worth pinning down.
12. **min agreement count for `high`** — proposal says "two corroborating readings within ±2 bpm." Should aging matter (e.g., agreement only counts within 12 months)? What about the second reading invalidating the first if it's far off?
13. **Backfill strategy for the new auto-refresh paths** — when D2 ships, do we walk historical activities once to populate calibration history, or only forward from sync date? The first option produces a richer graph; the second avoids retroactive flags.
