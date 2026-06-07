# Design — duration-keyed effort schedule

## Context

The forecast supplies a **maximal-effort HR** per distance so the model's effort covariate
`h = (avg_hr − LTHR)/H_DIV` has a value when no real `avg_hr` exists (a prediction). Today
that is `_MAXIMAL_HR_OFFSET`, a four-point table in **distance** (km → bpm-vs-LTHR),
interpolated in log-distance and capped at the MaxHR reserve.

The flaw is the axis. The intensity you can sustain is a function of **duration**, not
distance: the classic critical-speed / duration–intensity relationship. "HM ≈ LTHR" holds
only if the HM lasts the threshold-sustainable time. Two runners at the same distance but
different speeds are not at the same intensity, so a distance→bpm table assumes a fitness
level — the very confound the durability model removes. This change re-keys the schedule on
the model's *own predicted duration*, collapsing four hand-set anchors into two physiological
parameters that **reproduce** the validated table.

## The law

```
offset(t) = β · ( log t − log T₀ )          # bpm relative to LTHR
h(d)      = clamp( offset( t(d) ), reserve ) / H_DIV
```

- `t(d)` — the model's predicted maximal-effort time at distance `d` (minutes).
- `T₀` — duration where a maximal effort sits at LTHR (offset 0).
- `β < 0` — fade slope (bpm per natural-log-unit of duration).
- `reserve = MaxHR − LTHR` — the existing cap (`hr_reserve`), unchanged: `offset` is `min`-capped
  so a maximal effort can never exceed MaxHR.

## Validation: the table is already this law

Using the athlete's predicted maximal durations (current fitness):

| Distance | t (min) | log t | table offset (bpm) |
|---|---|---|---|
| 5 K | 22.5 | 3.114 | +10.0 |
| 10 K | 48.6 | 3.883 | +5.0 |
| HM | 111.1 | 4.710 | 0.0 |
| M | 243.9 | 5.497 | −6.0 |

Fit `offset = 0` at the HM (`T₀ = 111 min`) and `β` to the 10 K anchor (`+5`):
`β = 5 / (log 48.6 − log 111.1) = −6.04 bpm/log-unit`. That two-parameter curve predicts the
*other* two anchors it never saw: **5 K +9.65** (table +10.0) and **M −4.76** (table −6.0).
Three of four within 0.35 bpm; the marathon within ~1.2 bpm.

The consecutive table slopes are −6.50, −6.04, −7.63 bpm/log-unit — nearly constant, with the
marathon segment slightly steeper. A single `β` is therefore a near-exact fit short-to-mid and
mildly under-fades the marathon. That residual is **Decision 3**.

## Decisions

### Decision 1 — T₀ is personalised, β is population (with priors)

`T₀` is **personalised**: the duration at which the athlete holds ≈ LTHR at a *genuine maximal*
effort. Estimated from the qualifying effort whose `avg_hr` is closest to LTHR (this athlete:
the HM, 111 min, HR 173 ≈ LTHR 173). Population fallback **T₀ ≈ 55 min** (textbook
threshold-sustainable duration) when no such effort exists — the reusable cold-start default.

`β` is a **population** constant, **β ≈ −6.5 bpm/log-unit** (the duration–intensity slope is
far more stable across trained runners than T₀, which depends on individual threshold
endurance). Reusable shape; per-athlete refinement is a follow-on (Decision 4).

**Why personalise T₀ and not β:** T₀ is where the athlete *individually* sits at threshold —
this athlete holds LTHR for 111 min (strong threshold endurance, or a slightly-low
Garmin LTHR); a faster runner's threshold duration is shorter. β (how fast intensity fades
either side of T₀) is close to universal. Pinning T₀ from data is what keeps the forecast
**stable** (reproduces the validated table) while the duration axis makes it **general**.

**Anti-recommendation — anchor offset-0 to a fixed *distance* (e.g. "0 at the HM for
everyone").** This was the obvious lighter move and I rejected it: it re-imports the speed
confound. A maximal HM lasts 60–130 min by fitness; only a ~60-min HM is truly at LTHR. Pinning
offset-0 to the HM distance silently assumes the athlete's HM lasts the threshold time. Pinning
it to a **duration** (T₀) does not.

### Decision 2 — keyed on the model's own predicted duration (one-pass coupling)

`offset` needs `t(d)`; `t(d)` depends on `h = offset/H_DIV` through `κ`. This is a fixed point.
It is **weak**: `κ` moves log-time by ~1–3 % per 5 bpm, so `h` moving a few bpm moves `t(d)` by
<1 %, which moves `offset` by <0.1 bpm. **One pass** is therefore essentially exact:

```
t0 = predict(d, h = 0)                 # seed (or h from the legacy table)
h1 = offset(t0) / H_DIV
t1 = predict(d, h = h1)                # final
```

Implementation does **two** passes for safety and asserts convergence (|Δoffset| < 0.05 bpm) in
tests. No iteration loop ships to the hot path.

**Anti-recommendation — solve the fixed point exactly (root-find per distance).** Rejected:
the coupling is below the noise floor of the posterior; a solver adds cost and complexity for a
correction smaller than rounding. Two passes is the honest precision.

### Decision 3 — single slope; marathon residual flagged, not curvature-corrected

A single `β` under-fades the marathon by ~1.2 bpm (≈ 2 min). Two options:

- **(chosen) Single slope**, `β` chosen by least squares over all four anchors-in-duration
  (≈ −6.5). Simpler, one physiological law. The table's extra marathon kink (−6 vs the law's
  −4.8) may itself be a hand-set artifact, not a measured fade — there is no marathon in the
  data to adjudicate (the wall region is `extrapolation_prior`'s job, and it already widens the
  interval past `d_max`).
- (rejected) **Mild curvature** (quadratic in log t). Adds a third constant to fit a 1.2-bpm
  gap with no data behind it. Defer until a 30 km+ effort exists — at which point it joins the
  same calibration milestone as the wall knobs.

So the marathon point will read ~1–2 min faster than today's table. This is the only material
forecast change; it is documented, small, and on the optimistic side of a deliberately
conservative headline — surfaced for the athlete to accept, not hidden.

### Decision 4 — prior→posterior is the follow-on, not this change

The unifying principle (replace a hardcoded value with prior + cheap data update) applies:
`T₀` and `β` get population priors and per-athlete updates. This change does the **lightweight**
half — pin `T₀` from the nearest-LTHR maximal effort, `β` from population — because fitting them
properly needs a *maximality filter* (the athlete's 5 Ks are submaximal parkruns at ~LTHR; a
naive fit would learn "can't exceed threshold short" and over-slow every short prediction).
Building that filter (race-calendar flag, or HR within X % of distance-expected max) is the
follow-on, tracked next to the same maximal-effort work.

## Migration

1. `maximal_effort_h(distance_km, hr_reserve=None)` → keyed on duration. Two shapes considered:
   - **(chosen) `maximal_effort_h(predicted_minutes, hr_reserve=None)`** — pure function of
     duration; callers (who already call `predict`) supply `t(d)` and run the two-pass solve via
     a small helper `effort_h_for_distance(idata, ds, d, ...)`.
   - (rejected) `maximal_effort_h(idata, ds, distance)` doing the solve internally — couples the
     pure schedule to the posterior and is harder to unit-test in isolation.
2. `T₀`/`β` as module constants `EFFORT_T0_MIN`, `EFFORT_BETA`, plus `effort_t0(ds)` resolving
   the personalised `T₀` (nearest-LTHR genuine maximal effort → its duration; else `EFFORT_T0_MIN`).
3. Rewire the five internal callers (`forecast`, `derived_metrics`, `required_chronic_for_goal`,
   `durability_panel`, `trend_series`) and the two display callers (`cli`, `_model_week_trend`)
   through `effort_h_for_distance`. The MaxHR-reserve cap rides along unchanged.
4. `design.md` (marathon change) "Constants & assumptions": replace the four-row
   `_MAXIMAL_HR_OFFSET` justification with the (T₀, β) rows + this validation table. Update
   `DATA_LINEAGE.md` glossary (maximal-effort schedule → duration-keyed).

## Risks

- **T₀ estimation depends on identifying a genuine maximal-at-LTHR effort.** Mitigation:
  restrict to races / `effort_class ≥ Hard`; fall back to the population default and label it
  (same `defaulted` pattern as `extrapolation_prior`).
- **Forecast shift.** Bounded to the marathon ~1–2 min (Decision 3); validated against the
  athlete's actual race max-HRs before and after, same as the original schedule.
- **Cold-start athlete** (no maximal effort near LTHR) → population T₀; the law still generalises,
  just less personalised — strictly better than today's distance table for any non-anchor distance.
