## Why

The marathon forecast today is a single scalar with no uncertainty, derived from a fitness number (VDOT, or the now-retired conservative table) that **smears together three independent things**: how much you fade over distance (**durability**), how fit you were when you ran each effort (**fitness state**), and how hard each effort actually was (**maximality**). A single VDOT or Riegel number cannot separate them, so:

- a detrained-but-maximal race looks like poor durability,
- a fresh tempo and a tapered race at the same fitness are treated identically,
- the headline is hostage to one stale or unrepresentative race, and
- there is no interval and no probability of hitting the goal.

A validated Bayesian prototype (`marathon_model.py`, see the brainstorm handover) resolves this: it regresses log-time on distance, fitness (CTL) and effort (HR), yielding a **durability exponent**, a **fitness effect**, an **effort effect**, and a **posterior marathon time with a 90% credible interval and P(sub-goal)** — a headline that *moves as you train* and is not owned by any single race. On April-2026 data: marathon **3:59 [3:49, 4:09], P(sub-4) = 0.57**, durability exponent **1.061** (textbook).

This change hardens that prototype into a `fit` module and makes it the source for the Marathon Prediction chart + headline. It is **complementary to** `standardize-calibration-anchors`, not a replacement: that change owns the VDOT anchor + Daniels *training* pace zones + the LTHR/MaxHR/AeT calibrations; this change owns the *race-day forecast and durability/fitness analytics*, and it **consumes** the LTHR anchor as an input.

## What Changes

### New module `fit/analysis/marathon/`

```
extract_efforts(conn)        -> DataFrame    # Section "Data flow" SQL + CTL/ATL/x/c/h features
fit(efforts)                 -> posterior    # PyMC sample; cached to marathon_posterior.nc
predict(posterior, ctl, avg_hr, distance)    -> {median, lo, hi, p_sub_goal}
trend_series(posterior, daily_load)          -> DataFrame   # fitness-tracking line + band
derived_metrics(posterior, daily_load)       -> dict        # the metrics below
residuals(posterior, efforts)                -> DataFrame   # day-quality, for the correlation engine
influence(posterior, efforts)                -> DataFrame   # leave-one-out headline delta per effort
```

### The model (log-time regression, Student-T likelihood)

```
log(t_i) = alpha + beta_d·x_i + phi·c_i + kappa·h_i + delta·(x_i·c_i) + eps_i
x_i = log(distance_km_i / 42.195)     # 0 at the marathon (durability)
c_i = (CTL_i - 50) / 10               # fitness state, per 10 CTL, centred at 50
h_i = (avg_hr_i - LTHR) / 5           # effort/maximality, per 5 bpm vs LTHR
eps_i ~ StudentT(nu, 0, sigma)        # robust to bad-day races
```

LTHR comes from `get_calibration_anchor('lthr')` (the `standardize-calibration-anchors` anchor), **not** a hardcoded 172. Priors are weakly-informative and Riegel-centred (`beta_d ~ N(1.06, 0.05)`); the data dominates.

### Data flow

1. **Source** — `fitness.db` only. Efforts from `activities` (continuous intensity-bearing efforts: races, plus `tempo`/`progression` at effort_class Hard/Very Hard; intervals excluded — their `distance_km` includes recoveries). Daily load = `SUM(training_load) GROUP BY date` (cross-training included). No new tables to read.
2. **Features** — CTL/ATL are closed-form EWMAs of daily load computed in NumPy, using loads **strictly before** each effort day (incoming fitness, not inflated by the effort's own load). Maximality is the HR covariate, NOT the `run_type` label (a "race" can be submaximal).
3. **Fit** — PyMC NUTS, 4 chains, ~40 s. Robust (Student-T) so a single bad race does not dominate.
4. **Predict** — posterior draws → marathon at current CTL + a maximal-marathon HR (~167, an exposed input), summarised to median + 90% interval + P(sub-goal).

### When/how fitted, where/when stored

- **Refit** on `fit sync` (after ingest) — sampling is cheap; gate behind a flag if sync latency matters, else nightly.
- **Posterior** cached to `~/.fit/marathon_posterior.nc` (ArviZ NetCDF); `predict`/`derived_metrics`/`trend_series` reuse the cached draws with no refit.
- **Report-time** the dashboard reads the cached posterior; if absent/stale it falls back to the existing simple prediction with a "model not yet fit" note (never blocks the dashboard).
- Derived headline values (marathon median/interval, P(goal), beta_d, the derived-metric dict) are computed at report build and embedded in the dashboard like other section data; the posterior file is the source of truth.

### Dashboard

The existing "Marathon Prediction Trend" section is re-sourced from the model:
- **Headline** = marathon median **with the 90% interval always shown** + **P(sub-goal)** — never the point estimate alone.
- **Trend chart** = `trend_series` (marathon-equivalent at max effort tracking CTL over time) with per-effort points coloured by distance (the handover's Panel B). A durability panel (Panel A — efforts collapsing onto one power law) is optional.
- **Leave-one-out influence** surfaced: flag any effort whose removal moves the headline > ~5 min, so no single race silently owns the number.
- Assumptions stated in the def-box (Riegel-based durability exponent; maximal-marathon HR is an input; the interval is estimation uncertainty, not race-day spread).

### What the model produces, and how it fits the story vs existing metrics

| Output (from) | What it is | Existing metric it relates to / how it fits the story |
|---|---|---|
| **Marathon forecast + 90% interval + P(sub-goal)** | race-day time with uncertainty and goal probability | replaces the single-scalar prediction; the dashboard headline & the bridge to a required-load plan. Project has the goal (Berlin sub-4) but no probability — this attaches one. |
| **Durability `beta_d`** (exponent) | personal Riegel exponent w/ interval (1.061 [1.031,1.090]) | a metric the project **lacks entirely** — sits beside ACWR/zones/efficiency as "how well I hold pace as distance grows". Complements the `resilience` dimension (drift onset), which is the *physiological* durability signal; `beta_d` is the *performance* one. |
| **Fitness via CTL `phi`** | what a CTL point is worth in race time (+10 CTL ≈ −2.7% ≈ −6.4 min at the marathon) | the project tracks CTL/ACWR but never says what it's *worth*; makes the fitness chart actionable and prices a layoff (detraining cost curve). |
| **Effort maximality via HR `kappa`** | HR↔pace exchange (+1 bpm ≈ −0.58% pace) | sits alongside the descriptive `speed_per_bpm` efficiency metric as a *causal* "what a bpm is worth"; sanity-checks target race HR. |
| **Live race-equivalency table** | every distance at today's CTL + distance-appropriate max HR, with intervals | updates every sync using *your* exponent — replaces static Daniels VDOT equivalency tables (which assume fixed durability and never move). Coexists with Daniels *training* pace zones (different job: race paces vs training prescription). |
| **Required-CTL-for-goal** | inverse: CTL needed for P(sub-4) ≥ target (≈58 for 0.80, ≈70 for 0.90) | turns the goal into a fitness target and a training plan (roadmap). |
| **Day-quality residuals** | observed − model (distance/fitness/effort netted out) | a *cleaner* input to the existing correlation engine than raw pace — a temperature/sleep effect is no longer confounded by how fit/long each effort was. |
| **Confidence / data-gap flag** | width of the interval as a metric | the project doesn't express its own uncertainty; flags "limited by no efforts beyond 21 km". |

**Story fit:** Daniels VDOT (from `standardize-calibration-anchors`) answers *"how sharp is my engine right now"* (anchor + training paces); this model answers *"what will race day give, and how do fitness/durability/effort each contribute"* — and crucially provides the **probability** and the **interval** the dashboard headline needs. Durability (`beta_d`) and fitness-value (`phi`) become first-class, trackable signals the platform currently has no equivalent for.

## Capabilities

### Modified Capabilities
- `adaptive-predictions`: the prediction trend + race-time output are produced by the Bayesian model (posterior median + interval + P(goal)), still adapting to the target distance; the single-VDOT/Riegel scalar is superseded.
- `dashboard`: Marathon Prediction section shows median + interval + P(goal) + the fitness-tracking trend + leave-one-out influence; new durability/fitness-value readouts.
- `data-ingestion`: `fit sync` refits the posterior (or nightly) and caches it.

## Impact
- **Dependencies (new):** `pymc>=5`, `arviz`, `numpy`, `pandas`, `matplotlib`, `scipy` — heavy. Add as an extra (`pip install -e '.[forecast]'`) so the core install stays light; the dashboard degrades gracefully when absent.
- **Code:** new `fit/analysis/marathon/` (extract/fit/predict/trend/derived/residuals/influence); `fit/sync.py` refit+cache step; `fit/report/sections/` predictions + chart re-sourced; `fit/cli.py` a `fit forecast` command + refit trigger.
- **Storage:** `~/.fit/marathon_posterior.nc` (ArviZ NetCDF). No schema change for the core; derived metrics computed at report build.
- **Tests:** feature engineering (CTL/ATL closed-form vs recursion, strict-before-day), effort selection SQL, predict/percentile shape, graceful-degradation when pymc/posterior absent, leave-one-out delta. Sampling itself is not unit-tested (seeded smoke test only).
- **External:** none.

## Risks / Trade-offs
- **Extrapolation past the half** — longest race is 21 km; the marathon is a 2× extrapolation. `beta_d` is unverified beyond 21 km; marathon-specific limiters (glycogen, the wall, fuelling) are absent. Treat the interval as a floor, not the whole uncertainty; state it on the chart.
- **CTL is itself a model** on Garmin `training_load` — garbage-in risk.
- **Maximal-marathon HR (167) is an assumption**, not a fact — expose it; ±2 bpm ≈ ±3 min.
- **`phi` identified mostly off one detraining swing** — persuasive but will firm up (or move) with more varied-fitness efforts.
- **Estimation uncertainty ≠ race-day spread** — the interval is how well we know the curve; weather/course/pacing/fuelling variance on the day is often larger. Never let the point estimate stand alone.
- **PyMC weight / sampling latency** — mitigated by the optional extra, caching, and graceful degradation.

## Open Questions
1. Refit cadence — every `fit sync` vs nightly cron vs on-demand `fit forecast`?
2. Posterior staleness policy — refit when N new efforts or > X days old?
3. Do we surface the durability (Panel A) chart, or only the fitness-trend (Panel B) + headline, in v1?
4. Maximal-marathon HR — fixed 167, or derived from the athlete's observed max-effort HR vs duration?
5. Roadmap order (handover §10): freshness term (TSB = CTL − ATL) is the cheapest accuracy win — fold into v1 or defer?
