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

### Decision 1 — T₀ and β are population PRIORS the athlete's data updates (shrinkage)

Both parameters get a **population prior** and a **recency-/representativeness-weighted update**
from the athlete's own maximal efforts — the *same* treatment the durability model already gives
`β_d` (a `PRIOR_BETA_D` the race data updates). Nothing is purely assumed, and nothing is staked
on a single hand-picked race. Sparse or noisy data → stays at the population value; enough
consistent data → personalises. (This supersedes the earlier draft's "personalise T₀, fix β"
split — see below for why that draft broke on real data.)

- **β** — prior **≈ −6.5 bpm/log-unit** (population duration–intensity fade). The athlete's race
  HR-vs-log-duration slope updates it, precision-weighted: thin/noisy → ≈ −6.5; enough consistent
  data → the athlete's own fade.
- **T₀** — prior the population threshold-sustainable duration (**~55 min**). The athlete's races
  update where the curve crosses LTHR, weighted by **recency** (`exp(−age/τ)`, τ ≈ 12–18 months —
  so it tracks fitness: threshold endurance grows with base, erodes with detraining) and by
  **representativeness** (efforts nearer the *goal* duration count more; an old, far, or
  sub-maximal effort counts for almost nothing). Lands ≈ the athlete's half (~110–120 min) because
  they have *several* recent HMs near threshold — not because one was hand-picked.

**Why the prior is the whole point (a single-point rule breaks on real data).** The earlier draft
pinned `T₀` from the one effort whose `avg_hr` was nearest LTHR. On this athlete's *current* data
that fails: LTHR moved 173→171, and their nearest-LTHR race is now a **sub-maximal 5 K run at
threshold (25 min)**. The naive rule reads that as "holds threshold only 25 min" and collapses the
marathon forecast ~15 min slower. A prior dissolves this by construction — a lone sub-maximal race
barely moves a well-anchored estimate, and a short easy race earns almost no weight (far from the
goal duration; the prior expects a *maximal* 5 K well *above* threshold). This also answers the
original objection to fitting β from data ("sparse race HRs are noisy"): the prior is the safety
net, so fitting is regularised, not fragile.

**Why this is also the consistency fix.** Durability fade (`β_d`, time-vs-distance) is *measured*;
the effort fade (`β`, HR-vs-duration) was *assumed*. They are two faces of the same endurance
physiology, so measuring one and hard-coding the other was itself an inconsistency. Giving both
the prior+data treatment makes the two endurance parameters method-consistent. (Related cleanup
**D15**: the population durability exponent is hardcoded `1.06` in three places —
`predict_race_time`, `riegel_fallback_secs`, an inline `**1.06` — alongside the fitted
`β_d ≈ 1.07`; route those through one constant so the durability fade is single-sourced too.)

**Anti-recommendation — pick one race (nearest-LTHR, or longest-race-≥-LTHR).** Both are
single-point estimates, fragile to that race being sub-maximal, stale, or a bad-HR day.
"Longest race ≥ LTHR" is a decent heuristic, but the prior+weighted-data form *subsumes* it (it's
just the data the likelihood sees) without betting the forecast on one point.

**Anti-recommendation — anchor offset-0 to a fixed *distance* ("0 at the HM for everyone").**
Rejected: it re-imports the speed confound. A maximal HM lasts 60–130 min by fitness; only a
~60-min HM is truly at LTHR. Keying offset-0 to a *duration* (T₀), estimated as above, does not.

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

- **(chosen) Single slope**, one `β` (the prior-shrunk estimate of Decision 1 — ≈ −6.5 at
  cold-start, personalising with data). One physiological law. The table's extra marathon kink
  (−6 vs the law's −4.8) may itself be a hand-set artifact, not a measured fade — there is no
  marathon in the data to adjudicate (the wall region is `extrapolation_prior`'s job, and it
  already widens the interval past `d_max`).
- (rejected) **Mild curvature** (quadratic in log t). Adds a third shape constant to fit a
  1.2-bpm gap with no data behind it. Defer until a 30 km+ effort exists — at which point it
  joins the same calibration milestone as the wall knobs.

So with **thin data** (β ≈ the population prior) the marathon point reads ~1–2 min faster than
today's table — documented, small, on the optimistic side of a deliberately conservative headline,
surfaced for the athlete to accept, not hidden. As race data accumulates and β personalises, this
point tracks the athlete rather than a fixed assumption. (Confirmed in validation: shrinkage to
the prior reproduces the validated anchors, so the headline stays ~stable.)

### Decision 4 — adopt the prior+data (shrinkage) form now; full-Bayesian-in-sampler is the further follow-on

The earlier draft deferred prior+data and shipped a single-point `T₀`. That draft is what *broke*
on real data (the 25-min sub-maximal 5 K, Decision 1), so the prior+data form is **promoted into
this change**, not deferred. It is implemented as a **lightweight shrinkage estimate outside the
PyMC sampler** — a closed-form precision-weighted blend of the population prior and the
recency-/representativeness-weighted race data, computed in `predict.py`. The original objection
("fitting β from sparse race HRs is noisy") and the maximality concern (sub-maximal parkruns at
~LTHR) are both handled *by the prior + the weights*, not by a hard filter: a sub-maximal short
race is far from the goal duration and so earns almost no weight, and even if it did, the prior
keeps the estimate from running away.

The **further** follow-on (not this change) is making `T₀`/`β` true parameters *inside* the PyMC
likelihood (HR as part of the model), fit jointly with `β_d`/`φ`/`κ`. That earns its keep only if
the closed-form shrinkage proves insufficient — it adds likelihood terms, a model refit, and a
much larger validation surface for little expected gain over a well-prior'd closed form.

## Migration

1. `maximal_effort_h(distance_km, hr_reserve=None)` → keyed on duration:
   **`maximal_effort_h(predicted_minutes, t0, beta, hr_reserve=None)`** — a pure function of
   duration given the schedule params; callers (who already call `predict`) supply `t(d)` and run
   the two-pass solve via `effort_h_for_distance(idata, ds, d, ...)`. (Rejected: doing the solve
   inside `maximal_effort_h` — couples the pure schedule to the posterior, harder to unit-test.)
2. `effort_schedule(ds)` resolves the **shrunk** `(T₀, β)`: population priors `EFFORT_T0_PRIOR_MIN`
   (~55) and `EFFORT_BETA_PRIOR` (~−6.5), updated by a precision-weighted fit over the athlete's
   races (weight = recency `exp(−age/τ)` × representativeness near the goal duration). Returns the
   params + a `defaulted`/`reason` flag (mirrors `extrapolation_prior`) when data is too thin to
   move off the prior. Knobs (τ, prior strength, representativeness bandwidth) are named constants
   with cited justification.
3. Rewire the five internal callers (`forecast`, `derived_metrics`, `required_chronic_for_goal`,
   `durability_panel`, `trend_series`) and the two display callers (`cli`, `_model_week_trend`)
   through `effort_h_for_distance`. The MaxHR-reserve cap rides along unchanged.
4. `design.md` (marathon change) "Constants & assumptions": replace the four-row
   `_MAXIMAL_HR_OFFSET` justification with the (prior, shrinkage) description + validation table.
   Update `DATA_LINEAGE.md` glossary (maximal-effort schedule → duration-keyed, prior+data).
5. **D15** (separate, mechanical): route the three hardcoded Riegel `1.06`s through one constant.

## Risks

- **New knobs** (τ, prior strength, representativeness bandwidth). Mitigation: set with cited
  defaults; the prior dominates until data is genuinely informative, so defaults are forgiving.
  Validate before/after.
- **Shrinkage to prior must reproduce the validated anchors** (else the headline moves). This is
  the primary validation gate — confirm the cold-start (prior-only) law lands 5 K +9.65 / M −4.8
  as in the validation table, and that the current athlete's headline stays ~stable (≤ ~2 min).
- **Sub-maximal / bad-HR races bias the fit.** Mitigation: recency × representativeness weighting
  down-weights them; the prior caps the damage; no single race can move the estimate far.
- **Cold-start athlete** (no informative races) → both params sit at the population prior; the law
  still generalises across every distance — strictly better than today's distance table.
