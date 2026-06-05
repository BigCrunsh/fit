# Design — marathon-durability-model

How we harden the validated prototype (`reference/marathon_model.py`) into a `fit`
module, with the modelling decisions settled and the honesty constraints from
`LINEAGE_REVIEW.md` (F2/F4/F5/F6) baked in. The proposal is the *what*; this is the
*how* and *why*. Grounded in the measured data: ~30 qualifying efforts, longest ever
≈ a half-marathon (none beyond it, none near 30 km), distance and effort-HR
correlated (long efforts run easier).

## Context & non-goals

- **In:** the race-day forecast (median + interval + P-ceiling), durability/fitness/
  effort coefficients, the fitness-tracking trend, derived metrics, day-quality
  residuals, leave-one-out influence. Replaces the Phase-2 trend charts and retires
  `_vdot_to_marathon_seconds` once `trend_series` lands.
- **Out:** training-pace prescription (stays with the Daniels VDOT anchor —
  `standardize-calibration-anchors`), coaching notes (`fit-coach` is untouched; this
  is the analysis layer), and ACWR/injury-risk (stays as-is — see Decision 6).
- **Contract:** per `CLAUDE.md`, the MCP coaching context and the fit-coach skill must
  stay in sync if the headline metric or its semantics change. The forecast headline
  changes meaning here (point → median+interval+ceiling), so both need updating.

## Decision 1 — Drop the δ interaction term

The prototype's `delta·(x·c)` (durability × fitness) is **removed**. The handout's own
fit has `delta = -0.008 [-0.025, +0.008], P(<0)=0.79` — "leans favourable, not proven."
At ~30 efforts with collinear covariates (F4), a fourth slope is over-fitting. Final
mean model:

```
log(t_i) = alpha + beta_d·x_i + phi·c_i + kappa·h_i  +  pen(d_i)   (+ StudentT noise)
x_i = log(d_i / 42.195)         c_i = (CTL_i − 50)/10        h_i = (avg_hr_i − LTHR)/5
```

`LTHR` comes from `get_calibration_anchor('lthr')`, **not** a hardcoded 172.

## Decision 2 — Honest extrapolation: a drift-informed penalty on the unobserved region (NOT γ·x²)

**The problem with the agreed γ·x².** Because `x = 0` at the marathon, a `γ·x²` term
evaluates to **zero at the marathon** regardless of `γ` — it contributes neither fade
nor uncertainty at the exact point we extrapolate to. It would only bend the curve at
*short* distances (where we already have data). So γ·x² does not buy honest marathon
widening. This is the one place the prior brainstorm was technically wrong; here is the
fix.

**The construction.** A one-sided penalty active only **beyond the longest observed
effort** `d_max` (≈ the half):

```
pen(d) = gamma · max(0, log(d) − log(d_max))        gamma ~ HalfNormal(s_drift)
```

Because every observed effort has `d_i ≤ d_max`, `pen(d_i) = 0` for all data — the
likelihood never sees `gamma`. We have no information beyond the half, so the widening
at the marathon is an honest statement of ignorance, not a fitted quantity. At the
marathon `pen = gamma · log(42.195/d_max) ≈ gamma · 0.69`, and it collapses
automatically if/when a 30 km+ effort raises `d_max` (roadmap: half-plus validation).

**Implementation (skill-validated — `pymc-modeling`): keep `gamma` OUT of the PyMC
graph.** Since the likelihood never touches it, putting `gamma` in the model just adds a
prior-only dimension that pollutes `az.summary`/ESS/r̂ and means nothing inferentially;
`pm.Potential` is also wrong (it modifies logp but produces no predictive draws). So the
**fit model carries no penalty term** (`mu = alpha + beta_d·x + phi·c + kappa·h`), and the
penalty is applied as a **predict-time overlay**: draw `gamma ~ HalfNormal(s_drift)` in
NumPy, once per posterior draw, and add `gamma·max(0, log(d/d_max))` to the predicted
log-time. This is mathematically identical to a prior-only RV (independent of the fitted
params either way), keeps inference to 6 parameters, and makes the extrapolation an
explicit, documented overlay rather than a hidden model term. **Consequence for tests:**
PyMC prior/posterior predictive checks deliberately exclude the penalty; the "marathon
interval wider than in-sample" assertion runs against the penalized `predict()` output,
not a PyMC ppc.

**Why this is data-driven, not a σ_extrap knob.** `s_drift` is set from the athlete's
**measured cardiac drift** (the same `compute_cardiac_drift` / resilience signal on the
dashboard), not a tuned constant:

1. From recent long runs, take the second-half HR:pace decoupling (drift %) past the
   measured onset — the athlete's own within-run fade rate.
2. Project that rate over the *unobserved* span (`d_max` → 42.195 km) to a fractional
   time penalty `p_drift` (a doubling of distance for our data).
3. Choose `s_drift` so the penalty's median ≈ `p_drift` and its 90% upper covers a
   plausible "wall" (the HalfNormal carries the uncertainty of the projection).

So the prior *is* the measurement. **Flag:** this maps a within-run HR:pace signal to a
cross-distance time fade — principled but approximate. When drift data is thin
(cold-start), fall back to a conservative fixed `s_drift` and **log that the penalty is
defaulted, not athlete-derived** (no silent caps). **This is the decision most worth a
second look — see Open Questions.**

## Decision 3 — P(goal) is a fitness-sufficiency *ceiling*, not race-day odds

The interval is **estimation uncertainty** (how well we know the curve) plus the
Decision-2 extrapolation penalty — it is **not** race-day spread (weather, pacing,
fuelling, the wall beyond what drift implies). So `P(sub-goal)` is labelled and
documented as: *"probability your current fitness is sufficient for the goal under a
maximal, well-executed effort"* — a ceiling on race-day odds, not the odds themselves.
The dashboard never renders the median alone, and never renders P as "your chance on
the day." (F5)

## Decision 4 — Durability leads with the *measured* signal, β_d is the optimistic bound

Two durability readouts that can disagree (F5): the **measured** resilience drift-onset
(physiological, in-sample, ~mid-distance for this athlete) and `beta_d` (a performance
exponent, prior-dominated, extrapolated). The dashboard **leads with the measured
drift-onset** and presents `beta_d` as the *optimistic cross-distance bound* — "this is
what holds **if** the power law extends; your measured long-run form decays earlier."
When they conflict, the measured one wins the headline.

## Decision 5 — Report prior-vs-data movement (anti-false-precision)

For `beta_d` (and the others), surface **how far the posterior moved from the prior**
— e.g. prior 1.06±0.05 vs posterior median/interval, and a flag when the posterior is
within ~1 prior-SD of the prior mean ("prior-dominated: not yet measured from your
data"). A prior-sensitivity check (re-fit with a wider `beta_d` prior) is part of the
test/QA, not the dashboard. This directly answers F4: do not present a prior as a
measured personal trait. `beta_d`'s readout carries this caveat until varied, longer
efforts identify it.

## Decision 6 — ACWR and CTL/ATL coexist; they answer different questions (F2)

They are **not** merged. ACWR (rolling-7d acute ÷ chronic) stays the **injury-risk**
ratio. CTL/ATL/TSB (42d/7d EWMAs) are the **fitness/fatigue/freshness** state the model
regresses on. The design documents the split in one place and the dashboard labels them
distinctly. Both sit on Garmin `training_load`, which is **opaque** (we don't compute
it) — marked as such in `DATA_LINEAGE.md` and the def-box, so the garbage-in risk is
visible. Cross-training is included in daily load for CTL/ATL (matches the prototype and
TrainingPeaks); the running-only metrics keep their own denominator — noted, not
reconciled away.

## Decision 7 — Graceful degradation; the dashboard never hard-depends on PyMC

PyMC/arviz are **not installed** and are heavy. They go behind an extra
(`pip install -e '.[forecast]'`). Imports are lazy (inside the fit/predict functions).
When pymc **or** a cached posterior is absent or stale, the dashboard falls back to the
**Phase-1 anchor headline** (`anchor_race_time` → calibrated VDOT, or the Riegel race
fallback) with a **loud** note: *"durability model not fit — showing calibrated-VDOT
estimate, no interval."* It **never** falls back to the retired `_vdot_to_marathon_seconds`
table. (F6 — the fallback must change the label, not silently swap sources.)

## Decision 8 — Inference & diagnostics (skill-validated — `pymc-modeling` / `pymc-testing`)

- **Sampler: `nuts_sampler="nutpie"`** (2–5× faster) with fallback to default NUTS /
  numpyro if unavailable. Add `nutpie` to the `forecast` extra. Never change the model
  to suit the sampler.
- **Mandated workflow before any number is trusted** (not optional): (1) **prior
  predictive** — confirm priors generate plausible marathon times (≈2.5–6 h), not
  absurdities; (2) **save the posterior immediately** after sampling (before
  post-processing); (3) **divergences == 0**, `r_hat < 1.01`, `ess_bulk/tail > 400`;
  (4) **posterior predictive + LOO-PIT** calibration. Tight slope priors (σ≈0.05) are
  deliberately *informative* (a >5%/5bpm effect is implausible) — at n≈30 the prior
  influence is real, so the **prior-sensitivity re-fit** (Decision 5) is required, not
  nice-to-have.
- **Leave-one-out influence via `az.loo(pointwise=True)` Pareto-k**, not N manual
  refits — flag efforts with k > 0.7 as influential (cheaper, and the standard signal).
  nutpie doesn't store log-likelihood, so call `pm.compute_log_likelihood` first.
- **Tests use `pymc.testing.mock_sample`** (`pymc-testing` skill) for fast
  structure/shape/predict-wiring tests with no real sampling; a single seeded
  real-sample smoke test asserts `r_hat ≈ 1`.

## Data & features (from the prototype, unchanged where it was right)

- **Efforts:** races + tempo/progression at Hard/Very-Hard; intervals excluded
  (their `distance_km` includes recoveries). `run_type` is **not** used for maximality
  — the `h` (HR) covariate carries it, so a submaximal race and a hard tempo sit on the
  same frontier.
- **Daily load:** `SUM(training_load) GROUP BY date` (cross-training included).
- **CTL/ATL:** closed-form EWMAs (τ=42 / τ=7) computed in NumPy from loads **strictly
  before** each effort day (incoming fitness, not inflated by the effort's own load).
  Matches TrainingPeaks recursion to ~1%; no SQLite math functions needed.
- Efforts with no prior history (undefined CTL) are dropped — logged, not silent.

## Module shape

```
fit/analysis/marathon/
  features.py   extract_efforts(conn) -> DataFrame   # SQL + CTL/ATL + x/c/h + d_max
  model.py      fit(efforts) -> InferenceData        # priors (Decisions 1,2,5), NUTS, cache
  predict.py    predict(post, ctl, avg_hr, distance) -> {median, lo, hi, p_ceiling}
                trend_series(post, daily_load) -> DataFrame   # Panel B (replaces table charts)
                derived_metrics(post, daily_load) -> dict     # phi-value, layoff curve, β_d, κ, equiv table, required-CTL
                residuals(post, efforts) -> DataFrame         # day-quality (cleaner correlation input)
                influence(post, efforts) -> DataFrame         # leave-one-out headline delta
```

Posterior cached to `~/.fit/marathon_posterior.nc` (ArviZ NetCDF). Refit on `fit sync`
(cheap; gate behind a flag if latency matters) or on-demand `fit forecast`; report-time
reads the cache. Derived values embedded at report build like other section data.

## Honesty constraints → where each lives

| Finding | Constraint | Realized by |
|---|---|---|
| F2 | ACWR ≠ CTL; mark load opaque | Decision 6 + lineage/def-box |
| F4 | β_d may be prior-dominated | Decision 5 (prior-vs-data flag) |
| F5 | marathon is 2× extrapolation; durability readouts disagree | Decisions 2, 3, 4 |
| F6 | stale model must not revert silently to the bad path | Decision 7 (loud, anchor not table) |
| handover §8 | interval ≠ race-day spread; HR is an input; LOO | Decision 3 + influence() + def-box |

## Testing

- **Features (no PyMC):** CTL/ATL closed-form vs recursion (~1%), strict-before-day,
  effort-selection SQL, `d_max` computation, drop-no-history. 2:1 unhappy:happy.
- **Structure (mock, no sampling — `pymc-testing`):** `pymc.testing.mock_sample` to
  assert the model builds, shapes are right, and `predict()`/`trend_series` wire up —
  fast, CI-friendly.
- **Penalty (Decision 2 — predict-time overlay, γ not in the graph):** the fit `mu` has
  no penalty term; `predict()` *with* the overlay yields a marathon interval strictly
  wider than *without* it; the penalty is 0 at `d ≤ d_max`; `s_drift` is
  defaulted-and-logged when drift data is thin.
- **Predict/degrade:** percentile shape; P-ceiling monotone in CTL; **graceful
  degradation** when pymc/posterior absent → anchor headline + loud note, never the
  table (assert no import of `_vdot_to_marathon_seconds`).
- **Real sampling:** one seeded smoke test runs the mandated workflow (prior predictive
  plausible, divergences==0, `r_hat≈1`, ESS>400); not run in the fast suite.

## Open questions (carry to review before building)

1. **Decision 2 mapping** — is the within-run cardiac-drift → cross-distance fade
   projection sound enough to set `gamma`'s prior, or should v1 ship a conservative
   fixed `s_drift` (clearly labelled) and make the drift-link a fast-follow? *(My lean:
   ship fixed-but-labelled first, wire drift second — get the honest widening live
   without betting the headline on an unvalidated mapping.)*
2. **Refit cadence** — every `fit sync` vs nightly vs on-demand `fit forecast`?
3. **Staleness policy** — refit when N new efforts or > X days old?
4. **Maximal-marathon HR** — fixed (~167) input, or derived from observed max-effort
   HR-vs-duration? (±2 bpm ≈ ±3 min.)
5. **Freshness term** `psi·TSB` (roadmap §10.1) — fold into v1 or defer? (Cheapest
   accuracy win; data already extracted.)
```
