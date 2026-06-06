# Design — marathon-durability-model

How we harden the validated prototype (`reference/marathon_model.py`) into a `fit`
module, with the modelling decisions settled, the `LINEAGE_REVIEW.md` honesty
constraints (F2/F4/F5/F6) baked in, and a dual-lens (Bayesian + sports-medicine)
review converged so both sign off. The proposal is the *what*; this is the *how/why*.
Grounded in the measured data: ~30 qualifying efforts, longest ever ≈ a half-marathon
(none beyond it), distance and effort-HR correlated (long efforts run easier).

## Guiding principle — parsimony (explain through existing metrics)

Everything the model needs is mapped onto metrics the platform **already computes**;
new concepts must be justified. The audit:

| Model need | Existing metric reused | New? |
|---|---|---|
| effort selection | `run_type`, `effort_class` | — |
| `x` durability | `distance_km` | — |
| `d_max`, long-run quantity | `classify_run_type` long-run rule + weekly volume | — |
| **fitness state `c`** | **ACWR's chronic-load primitive** (trailing mean of daily `training_load`) | — (NO new CTL/ATL) |
| `h` effort | `avg_hr` + LTHR anchor | — |
| long-run **quality** | second-half pace + `drift_onset_km` machinery (`periodization.py`/`fit_file.py`) + `effort_class` | one small ratio |
| goal distance / adaptivity | `get_target_race` | — |
| extrapolation penalty `γ` | (no analog) | **new — irreducible** |

**Net new: one concept** (`γ`, the honesty overlay) **+ one computed ratio**
(long-run pace-fade, on existing machinery) **+ one chart** (the durability view that
*unifies* existing + new). Everything else reuses what exists — and this **dissolves
the F2 "two load models" problem** (one shared chronic-load primitive, see Decision 6).

## Context & non-goals

- **In:** the race-day forecast (median + interval + P-ceiling), durability/fitness/
  effort coefficients, the fitness-tracking trend, derived metrics, day-quality
  residuals, leave-one-out influence. Replaces the Phase-2 trend charts and retires
  `_vdot_to_marathon_seconds` once `trend_series` lands.
- **Out:** training-pace prescription (Daniels VDOT anchor), coaching notes
  (`fit-coach` untouched), injury-risk (ACWR stays — Decision 6), fuelling (race-day
  *execution*, belongs in race-day spread, not the fitness prior — labelled exclusion).
- **Contract:** per `CLAUDE.md`, the MCP coaching context and fit-coach skill must stay
  in sync — the forecast headline changes meaning (point → median+interval+ceiling).

## Decision 1 — Model spec (drop δ; goal-adaptive; existing-metric covariates)

```
log(t_i) = alpha + beta_d·x_i + phi·c_i + kappa·h_i  + StudentT(nu, 0, sigma)
  x_i = log(d_i / D_REF)      D_REF = GOAL distance (get_target_race), not hardcoded 42.195
  c_i = (L_i − L_ref) / L_scale   L = chronic load (existing ACWR primitive), point-in-time
  h_i = (avg_hr_i − LTHR) / 5     LTHR from get_calibration_anchor('lthr')
```

- **δ dropped:** the prototype's `delta·(x·c)` is `−0.008 [−0.025,+0.008], P(<0)=0.79`
  — unproven; a 4th slope over-fits at n≈30 (F4).
- **Goal-adaptive `D_REF`:** centring `x` at the *goal* makes `alpha` read "goal-distance
  time"; switch the target to a half and the model re-centres. (Centring is cosmetic —
  `beta_d/phi/kappa` are centring-invariant — but the prediction target and the penalty,
  Decision 2, are genuinely goal-driven.)
- **`c` reuses the existing chronic-load primitive** — a trailing mean of daily
  `training_load` strictly **before** each effort (the same quantity ACWR uses as its
  chronic denominator), evaluated point-in-time. **No new CTL/ATL EWMA** (Decision 6).
  `L_ref`/`L_scale` are cosmetic centring constants (like `D_REF`).

## Decision 2 — Honest extrapolation: a preparedness-shrunk penalty (NOT cardiac drift)

The forecast must not pretend to know the back half it has never run. A one-sided
penalty, applied **per predicted distance** so it self-adapts to the goal:

*(Terminology: previously drafted as `s_drift` — renamed after the dual-lens review
rejected cardiac drift as the driver; the name must not imply drift feeds it.)*

```
pen(d) = gamma · max(0, log(d / d_max))           # 0 when d ≤ d_max (interpolation)
gamma ~ HalfStudentT(nu = 4, extrapolation_scale)
extrapolation_scale = GENERIC_WALL_SCALE · shrink            shrink ∈ [floor, 1]   (asymmetric: data only reduces)
  shrink ↓ with long-run pace-HOLDING (median pace-fade at effort_class ≥ Moderate):
     hold/negative-split → shrink to floor;  fade hard → stay at the generic scale;  no
     qualifying long runs → defaulted=True, stay generic, log it.
```

**The gap is NOT re-encoded in the scale.** The extrapolation *distance* lives entirely
in the multiplier `log(d/d_max)` (→ 0 as `d_max` approaches the goal). `shrink` carries
only *pace-quality* — how much the wall costs **this** athlete — so the two mechanisms
stay orthogonal (no double-counting). Implemented in `fit/marathon/preparedness.py`
(`extrapolation_prior`); quality via `long_run_pace_fade` on the existing splits
machinery.

**Goal-adaptive by construction.** `pen` keys off `d` vs `d_max`, not 42.195: a marathon
goal with HM data → big penalty; a half goal you've raced → `pen ≈ 0`; a 10k goal →
interpolation, none. The race-equivalency table gets the right penalty per row.

**Why `HalfStudentT(ν=4, extrapolation_scale)`.** (a) **One-sided (≥0):** extrapolating past your
longest distance can only add fade, never remove it. (b) **Mode at 0:** we *allow* a
wall, don't *assume* one. (c) **Heavy tail (ν=4):** the wall is right-skewed and
occasionally catastrophic (+20–40 min); a Gaussian (HalfNormal) tail underweights the
blow-up. **ν=4 is a labelled convention, not a derivation** — the smallest integer ν with
finite kurtosis ("heavy but not pathological"), and the `pymc-modeling` skill's
recommended robust default (ν∈[3,7]). The headline is far more sensitive to `extrapolation_scale`
than to ν, so ν is deliberately *not* gold-plated. (Strict-parsimony alternative:
HalfNormal — the 90% edge barely moves; we choose the heavier tail for honesty about
blow-ups.)

**`shrink` is asymmetric + floored + endpoint-anchored.** It starts at `GENERIC_WALL_SCALE` (a
population marathon-fade scale, labelled "generic — no goal-distance data") and only
**shrinks** as you demonstrate preparedness; it never inflates on thin/noisy data (that
was the fatal flaw of the drift idea). The floor keeps it > 0 until an actual
goal-distance effort exists — no full confidence on pure extrapolation.

**Why preparedness, not cardiac drift.** The dual-lens review (recorded in chat) found
cardiac drift is the *wrong* signal for the wall: the most direct evidence finds HR:pace
decoupling **not associated** with marathon durability, and late-race fade is
*speed*-driven, not HR-driven; drift is also confounded by heat/hydration and measured at
easy-run intensity. The evidenced signals are **longest-run distance** (longest run
<25 km → slower finish) and **fast-finish long runs** (predict the marathon 8–12 wk out)
— so `shrink` uses long-run quantity + a **pace-fade** quality signal, not drift.

**Implementation (skill-validated): `gamma` stays OUT of the PyMC graph.** Because every
observed effort has `d_i ≤ d_max`, `pen(d_i)=0`, so the likelihood never sees `gamma` —
putting it in the model would only pollute ESS/r̂, and `pm.Potential` yields no predictive
draws. So the **fit carries no penalty term** (`mu = alpha + beta_d·x + phi·c + kappa·h`);
the penalty is a **predict-time NumPy overlay** (draw `gamma` per posterior draw, add to
the predicted log-time). Identical math, 6 clean parameters, explicit overlay. *Tests:*
PyMC ppc excludes the penalty; "interval wider than in-sample" runs against `predict()`.

## Decision 3 — P(goal) is a fitness-sufficiency *ceiling*, not race-day odds

The interval is **estimation uncertainty** + the Decision-2 extrapolation penalty — **not**
race-day spread (weather, pacing, fuelling). So `P(sub-goal)` is labelled *"probability
your current fitness is sufficient under a maximal, well-executed effort"* — a ceiling on
race-day odds. The median is never shown alone, and P is never rendered as "your chance on
the day." (F5)

## Decision 4 — Durability leads with the *measured* signal; β_d is the optimistic bound

Durability readouts can disagree (F5). The dashboard **leads with the measured signals** —
long-run **pace-fade** (speed give-back, the evidenced wall signal) and the existing
`resilience` drift-onset — and presents `beta_d` as the *optimistic cross-distance bound*
("what holds **if** the power law extends; your measured long-run form decays earlier").
When they conflict, the measured signal wins the headline.

## Decision 5 — Report prior-vs-data movement (anti-false-precision)

For `beta_d` (and the rest), surface **how far the posterior moved from the prior** and
flag "prior-dominated: not yet measured from your data" when it's within ~1 prior-SD of
the prior mean. A prior-sensitivity re-fit (wider `beta_d` prior) is QA, not dashboard.
Answers F4: never present a prior as a measured personal trait.

## Decision 6 — One shared load concept (F2 dissolved — no new CTL/ATL)

The model's fitness state `c` reuses **ACWR's chronic-load primitive** (trailing mean of
daily `training_load`), evaluated point-in-time per effort. So the forecast and ACWR sit
on **one** load concept — there is no second fitness model to disagree with. ACWR remains
the **injury-risk ratio** (acute ÷ chronic); the forecast uses the **chronic level** as
fitness state. (The prototype's 42-day EWMA is dropped: its only edge over the existing
trailing-mean is smoothness, which doesn't justify a parallel concept. Freshness/TSB and
ATL stay on the roadmap.) `training_load` is Garmin-**opaque** — marked as such in
`DATA_LINEAGE.md` and the def-box.

## Decision 7 — Graceful degradation; the dashboard never hard-depends on PyMC

PyMC/arviz are heavy and behind the `forecast` extra; imports are lazy. When pymc **or** a
cached posterior is absent/stale, the dashboard falls back to the **Phase-1 anchor
headline** with a **loud** note (*"durability model not fit — calibrated-VDOT estimate, no
interval"*). It **never** falls back to the retired `_vdot_to_marathon_seconds` table.
(F6 — the fallback changes the label, not silently the source.)

## Decision 8 — Inference & diagnostics (skill-validated)

- **Sampler `nuts_sampler="nutpie"`** (fallback default NUTS / numpyro). Never change the
  model to suit the sampler.
- **Mandated workflow before trusting any number:** (1) prior predictive — plausible
  times (≈2.5–6 h); (2) save posterior immediately; (3) divergences==0, `r_hat<1.01`,
  `ess>400`; (4) posterior predictive + LOO-PIT. Tight slope priors (σ≈0.05) are
  *informative* → the prior-sensitivity re-fit (Decision 5) is required.
- **Leave-one-out influence via `az.loo(pointwise=True)` Pareto-k** (flag k>0.7), not N
  refits; `pm.compute_log_likelihood` first (nutpie doesn't store it).
- **`pymc.testing.mock_sample`** for fast structure tests; one seeded real-sample smoke
  test asserts `r_hat≈1`.

## Decision 9 — Unified durability + extrapolation watch view (REQUIRED)

The preparedness-shrunk penalty **ships with monitoring, not blind** — and the same view
**unifies existing + new durability metrics** (the only new chart, justified by the
parsimony rule because it ties the new ratio back to what you already track):

- **Decomposed headline:** power-law base **+** the penalty band, so the penalty's
  contribution is always visible; with the `GENERIC_WALL_SCALE` (generic) and zero-penalty lines as
  baselines — divergence from the generic line is a visible flag.
- **One durability story:** the existing `resilience` drift-onset (HR:pace, cardiac) **next
  to** the new long-run **pace-fade** (speed, glycogen/neuromuscular) and the long-run
  **distance progression** toward the goal — three readouts, one panel, with the
  difference between drift and pace-fade stated.
- **Tracked over time:** implied penalty % / `extrapolation_scale` vs the `GENERIC_WALL_SCALE` baseline; and the
  preparedness inputs (longest run, pace-fade) so a thin/noisy feed is visible.
- **Validation:** when a goal-distance-class effort (e.g. 30 km+) lands, overlay actual vs
  predicted band; until then label "unvalidated extrapolation."
- **Guardrail:** thin/noisy preparedness data, or penalty far from the `GENERIC_WALL_SCALE`
  baseline, falls back to `GENERIC_WALL_SCALE` and says so.

## Data & features (reuses existing metrics)

- **Efforts:** races + tempo/progression Hard/Very-Hard; intervals excluded. `run_type`
  not used for maximality — `h` carries it.
- **Daily load:** `SUM(training_load) GROUP BY date` (cross-training included).
- **Fitness `c`:** trailing-mean chronic load **strictly before** each effort (ACWR's
  chronic primitive, point-in-time). No EWMA.
- **`d_max` + long-run quantity:** from `distance_km` + the existing long-run rule.
- **Long-run pace-fade (new ratio):** second-half vs first-half pace give-back, built on
  the existing `avg_pace_second_half` / drift machinery, gated by `effort_class ≥ Moderate`
  (easy long runs count for quantity, not quality). Distinct from `resilience` (HR drift).
- Efforts with no prior history (undefined chronic load) are dropped — logged.

## Module shape

`fit/marathon/` (NOT `fit/analysis/marathon/` — `fit/analysis.py` is already a module):

```
fit/marathon/
  features.py   extract_efforts(conn) -> DataFrame    # efforts + chronic-load c + x/h + d_max  [DONE]
  preparedness.py  extrapolation_prior(conn, goal) -> {scale, default_scale, shrink, inputs, defaulted}   # gap + quality
  model.py      fit(efforts) -> InferenceData         # priors (D1,5), nutpie, cache
  predict.py    predict(post, c, avg_hr, distance, goal) -> {median, lo, hi, p_ceiling}
                trend_series / derived_metrics / residuals / influence
```

Posterior cached to `~/.fit/marathon_posterior.nc`; refit on `fit sync` (flagged) or
`fit forecast`; report reads the cache.

## Honesty constraints → where each lives

| Finding | Constraint | Realized by |
|---|---|---|
| F2 | one load concept, not two; load opaque | Decision 6 (shared chronic primitive) |
| F4 | β_d may be prior-dominated | Decision 5 |
| F5 | extrapolation; durability readouts disagree | Decisions 2, 3, 4, 9 |
| F6 | stale model must not revert to the bad path | Decision 7 |
| handover §8 | interval ≠ race-day spread; HR an input; LOO | Decisions 3, 8 + def-box |

## Testing

- **Features (no PyMC):** chronic-load strictly-before, effort SQL, `d_max`,
  drop-no-history. Done in `tests/test_marathon_features.py`.
- **Preparedness:** `shrink` monotone in gap + quality; asymmetric (never > 1); floored;
  `GENERIC_WALL_SCALE` fallback when data thin; pace-fade gated by `effort_class`.
- **Structure (mock):** `pymc.testing.mock_sample` — builds, shapes, predict wiring.
- **Penalty:** `predict()` with overlay wider than without; `pen=0` at `d ≤ d_max`;
  goal-adaptive (half goal within data → no penalty).
- **Degrade:** no pymc/posterior → anchor headline + loud note, never the table.
- **Real sampling:** one seeded smoke test (prior-pred plausible, divergences==0, r̂≈1).

## Open questions

1. **Extrapolation — RESOLVED:** preparedness-shrunk `HalfStudentT(ν=4)` penalty (not
   cardiac drift); `GENERIC_WALL_SCALE` is the floor/fallback; watch layer mandatory. Sub-question:
   the `shrink` curve's exact rate is an informed assumption (no study quantifies
   30 km-fast-finish → 42 km-fade) — monitored + validated by a goal-distance effort.
2. **LTHR source** — ingest the watch's lactate threshold (not currently synced) vs
   confirm a value manually. (Open input; the model uses the anchor either way.)
3. **Refit cadence** / **staleness policy** — every `fit sync` vs nightly vs on-demand.
4. **Maximal-goal-effort HR** — fixed input vs derived from observed max-effort HR-vs-
   duration (±2 bpm ≈ ±3 min). Re-derive relative to the *actual* LTHR anchor, not 172.
5. **Freshness term** `psi·TSB` — defer (roadmap).
```

## Constants & assumptions — justification (audit)

Every fixed number the change introduces, its source, and whether it's personalised or
reusable. Rule: nothing is a silent magic number — each is cosmetic, a reuse of an
existing concept, a data-personalised default, or a labelled assumption the watch layer
(Decision 9) + a 30 km+ effort validate.

| Constant | Value | Source / justification | Personalised? Reusable? |
|---|---|---|---|
| `_MAXIMAL_HR_OFFSET` schedule | 5k +10 / 10k +5 / HM 0 / M −6 bpm vs LTHR | physiological "maximal race HR rises above threshold for short, falls below for long". **Validated vs the athlete's own race max-HRs**: 10k max 179≈+5(178), HM max 173=+0(173). Marathon (−6) is the irreducible assumption (no marathon raced; handover §8). | **Personalised**: LTHR-relative (tracks the calibrated anchor) + goal-adaptive. Reuses the LTHR anchor. *Not* fit per-athlete from race HRs — those are effort-confounded (their 5ks are submaximal ~172), the exact problem the model exists for. |
| `PRIOR_BETA_D` | N(1.06, 0.05) | Riegel textbook exponent; weak SD | Posterior updates it; flagged `prior_dominated` when the data can't (F4) |
| `PRIOR_PHI`,`PRIOR_KAPPA` | N(0, 0.05) | weakly-informative; a >5%/unit effect is implausible | data-identified |
| `PRIOR_SIGMA` | HalfNormal(0.06) | race log-time noise ≈3–6% | data |
| `PRIOR_NU` | Gamma(2, 0.1) | standard Student-T robustness | data |
| `alpha` prior | N(log(goal·5.5), 0.5) | goal-adaptive centre (~5:30/km crude); wide | cosmetic — data dominates the intercept |
| `CHRONIC_WINDOW_DAYS` | 28 | **reuses ACWR's chronic window** (4 ISO weeks) | one shared load concept (F2) |
| `CHRONIC_REF/SCALE` | 50 / 10 | cosmetic centring of `c` (doesn't change β_d; φ rescales) | matches the prototype convention |
| `H_DIV` | 5 | κ expressed per 5 bpm | cosmetic |
| `NU` (wall penalty) | 4 | labelled heavy-tail convention (smallest integer with finite kurtosis); headline far more sensitive to scale | assumption, monitored |
| `GENERIC_WALL_SCALE` | 0.04 | population wall scale (median penalty ≈+2%) — the **default** | personalised by the pace-fade `shrink`; labelled when defaulted |
| `SHRINK_FLOOR` | 0.5 | never <½ the default until a goal-distance effort validates | tuning knob — **flagged**, monitored (Decision 9) |
| `FADE_LO / FADE_HI` | 0% / 8% | pace-fade credit band (hold→floor, ≥8% fade→no credit) | tuning knob — **flagged**, calibrate vs data |
| `QUALITY_MIN_KM` | 15 | "long run" threshold | relates to the existing long-run rule |
| `QUALITY_WINDOW_DAYS` | 112 | marathon-build horizon (16 wk) | assumption |
| `QUALITY_EFFORT` | Moderate+ | **reuses `effort_class`** | reuse |
| `_STD_DISTANCES` | 5k/10k/HM/M | standard race distances for the equivalency table | display choice |

**Residual tuning knobs** (not yet data-calibrated): `GENERIC_WALL_SCALE`, `SHRINK_FLOOR`,
`FADE_HI`, `NU`. All are extrapolation-penalty parameters — the part with *no* validating
data until a 30 km+ effort. They are labelled, defaulted-conservatively, and the
Decision-9 watch layer surfaces their effect; the 30 km+ effort is what calibrates them.

## Improvements identified (backlog)

- **`forecast_context(conn)` refactor** (efficiency/altitude): the posterior is loaded ~5×
  and `extract_efforts`/`extrapolation_prior` run 3–5× per report build. One shared
  context object passed to all consumers would collapse this. Deferred from /simplify
  (5-function refactor, regression risk). Highest-value cleanup.
- **MaxHR cap on `maximal_effort_h`**: short-distance offsets (LTHR+10) are unbounded; for
  an athlete with a small LTHR→MaxHR reserve they could exceed MaxHR. Cap at the calibrated
  MaxHR (reuse the anchor). Not binding for the current athlete (183 < 195).
- **Calibrate the penalty knobs** (`GENERIC_WALL_SCALE`/`FADE_HI`/`SHRINK_FLOOR`/`NU`) once
  a 30 km+ effort exists — the validation overlay (Decision 9) is the mechanism.
- **Automate the prior-sensitivity re-fit** (Decision 5) + add the PyMC ppc / LOO-PIT plots
  (Decision 8) — currently a manual QA step.
- **F3 (VDOT-anchor maximality bias)**: the forecast models effort via `h`, but the VDOT
  *anchor* still assumes near-maximal races — reconcile in a follow-up.
