# Marathon prediction model: handover

**Target repo:** `github.com/bigcrunsh/fit`
**Status:** working prototype, validated against `fitness.db`; ready to harden into a module.
**Owner:** Christoph (BigCrunsh)
**Reference code:** `marathon_model.py` (self-contained: extract, fit, predict, chart)
**Reference chart:** `marathon_v2.png`

## 1. What this is, in one paragraph

A Bayesian model that predicts marathon time (with a credible interval) from your
existing race and hard-effort history, while cleanly separating three things that a
single VDOT number or a Riegel calculator smears together: your **durability** (how
much you fade as distance grows), your **fitness state** at the time of each effort,
and the **maximality** of each effort. It replaces the broken "slowest-in-window"
headline and the naive Daniels/Riegel single-number approach. The headline output is
"marathon time at your *current* fitness and a maximal effort", and it moves as you
train rather than being hostage to one stale or detrained race.

## 2. Why the obvious approaches fail (rationale, so the next person does not relitigate it)

- **Daniels VDOT from one race** gives a point estimate with no interval, and its
  marathon-equivalent bakes in an *assumed* durability (an implicit fatigue exponent
  near 1.06). If your real durability differs, the equivalent is biased; for me it
  read optimistic at the marathon.
- **Riegel** (`t2 = t1 * (d2/d1)^c`, classic `c = 1.06`) is a time-prediction power
  law, not a VDOT, and the fixed exponent is wrong for most non-elite runners. It is
  tunable but still a point estimate.
- **Any single order statistic over a window** (best-in-window, slowest-in-window)
  collapses durability, fitness, and recency into one scalar and then cannot separate
  them. `slowest-in-window` is sticky to one bad race; `best-in-window` ignores
  durability. This was the original defect we set out to fix.
- **A joint model with a *linear time trend*** (the first version, see Section 6) is
  better but still wrong: fitness is not monotonic in calendar time. A linear trend
  mistook a three-month detraining gap for permanent decline and dumped the resulting
  slow long-races into the durability exponent, inflating it to ~1.09. Replacing
  calendar time with a **fitness-state covariate (CTL)** fixed this and pulled the
  exponent back to a textbook ~1.06.

The current model is the resolution of that progression.

## 3. Model specification

For each effort `i` we model log-time as a linear function of distance, fitness,
and effort, with a Student-T likelihood for robustness to bad-day races:

```
log(t_i) = alpha
         + beta_d * x_i                      # durability (distance)
         + phi    * c_i                      # fitness state
         + kappa  * h_i                      # effort / maximality
         + delta  * (x_i * c_i)              # durability x fitness interaction
         + eps_i,     eps_i ~ StudentT(nu, 0, sigma)

x_i = log(distance_km_i / 42.195)            # 0 at the marathon
c_i = (CTL_i - 50) / 10                       # fitness, per 10 CTL units, centred at 50
h_i = (avg_hr_i - 172) / 5                    # effort, per 5 bpm relative to LTHR=172
```

**Interpretation of parameters**

| param   | meaning                                                        | sign of "better" |
|---------|----------------------------------------------------------------|------------------|
| `alpha` | log marathon time at CTL=50, effort=LTHR (reference point)     | lower            |
| `beta_d`| fatigue/durability exponent (Riegel exponent)                  | lower (~1.06 normal) |
| `phi`   | fitness effect: change in log-time per +10 CTL                 | negative         |
| `kappa` | effort effect: change in log-time per +5 bpm toward max        | negative         |
| `delta` | does durability improve with fitness? (exponent shift per CTL) | negative         |

**Priors** (weakly-to-mildly informative; the data dominates all of them):

```
alpha  ~ Normal(log(240), 0.4)     # ~4h, generous
beta_d ~ Normal(1.06, 0.05)        # Riegel-centred; lets data move it, keeps extrapolation sane
phi    ~ Normal(0, 0.05)
kappa  ~ Normal(0, 0.05)
delta  ~ Normal(0, 0.03)
sigma  ~ HalfNormal(0.06)
nu     ~ Gamma(2, 0.1)             # robustness; small nu downweights outliers
```

**Prediction.** The headline is the posterior of `t` at the marathon (`x = 0`),
current CTL, and a *maximal marathon effort*. Maximal effort for a marathon is taken
as avg HR ~167 (`h = -1.0`), because sustainable HR falls with duration and your
maximal half-marathons sat at HR 172-173. Sensitivity: +/-2 bpm moves the headline
about +/-3 min.

## 4. Data

**Source:** `fitness.db`, table `activities`. No other table is required for the
core model. `daily_health` (HRV, resting HR, readiness) is unused and is a candidate
for a future freshness/recovery extension.

**Columns used:** `date, type, run_type, effort_class, distance_km, duration_min,
avg_hr, training_load`. The athlete LTHR (172) comes from `lthr_used`.

**Effort selection.** Continuous, intensity-bearing efforts only. Intervals are
excluded because their `distance_km` includes recoveries, so they are not a single
continuous effort.

```sql
SELECT id, date, run_type, distance_km, duration_min, avg_hr
FROM activities
WHERE type IN ('running','track_running')
  AND ( run_type = 'race'
        OR (run_type IN ('tempo','progression') AND effort_class IN ('Hard','Very Hard')) )
ORDER BY date;
```

Note the `run_type` label is **not** used to assume maximality. A "race" can be
submaximal (e.g. a 5K logged at avg HR 164, below several tempo runs). Maximality is
handled uniformly by the `h` (HR) covariate, so races and tempos sit on the same
frontier and the model infers the max-effort curve when `h` is at its ceiling.

**CTL / ATL (fitness / fatigue).** Exponentially-weighted training load. For an
effort on day `D`, use loads strictly *before* `D` (incoming fitness; do not let the
effort's own load inflate its CTL):

```
CTL(D) = (1/42) * sum_over_days_k<D [ load_k * exp(-(D - k)/42) ]   # chronic, fitness
ATL(D) = (1/7)  * sum_over_days_k<D [ load_k * exp(-(D - k)/7)  ]   # acute, fatigue
```

`load_k` is the sum of `training_load` over all activities on day `k` (cross-training
included; cycling contributes little). This closed form matches the standard
TrainingPeaks CTL recursion to ~1%. The reference script computes it in NumPy from a
single `GROUP BY date` query, so it needs no SQLite math functions.

**Exclusions / data-quality notes.**

- One effort (the earliest tempo) has no prior history, so `CTL` is undefined and it
  is dropped. 30 efforts remain (2.98 to 21.36 km, July 2024 to April 2026).
- The March 2026 half (122 min) is **kept**. It was a genuine maximal effort (TE 5.0,
  HR 173, good conditions, 6 C) but run at CTL ~10 after a three-month layoff. The
  model correctly explains it via low fitness, not poor durability. Do not "clean" it.

## 5. How to run

```bash
pip install pymc arviz numpy pandas matplotlib
FIT_DB=/path/to/fitness.db python marathon_model.py
```

Outputs: a parameter summary and prediction table to stdout, `marathon_model.png`
(2-panel chart), and `marathon_posterior.nc` (ArviZ posterior for reuse). Sampling is
~40 s on a laptop (4 chains). Set `FIT_TODAY` to re-anchor "today".

## 6. Results (snapshot, April-2026 data)

Sampling clean (R-hat 1.00, good ESS). Posterior medians, 90% credible intervals:

```
beta_d (durability exponent) : 1.061  [1.031, 1.090]      # textbook Riegel
phi    (per +10 CTL)         : -0.027 [-0.051, -0.004]    # ~2.7% faster / +10 CTL
kappa  (per +5 bpm)          : -0.029 [-0.043, -0.015]    # effort proxy well-identified
delta  (durability x fitness): -0.008 [-0.025, +0.008]    # P(<0)=0.79, leans favourable, not proven
sigma                        :  0.035                      # ~3.6% residual
```

Marathon at maximal effort (avg HR ~167):

```
current  CTL ~50 : 3:59  [3:49, 4:09]   P(sub-4) = 0.57
built    CTL  60 : 3:52  [3:39, 4:06]   P(sub-4) = 0.82
peak     CTL  70 : 3:46  [3:29, 4:05]   P(sub-4) = 0.90
detrained CTL 25 : 4:16  [4:02, 4:29]   P(sub-4) = 0.03
```

**Contrast with the superseded linear-time model** (kept only as a cautionary tale):
it gave durability exponent 1.09, a marathon of 4:10, and P(sub-4) = 0.15, driven
almost entirely by the detrained March half (leave-one-out on that single race moved
it to 3:55 and the exponent to 1.06). The fitness-aware model dissolves that fragility:
the March half is explained, not influential, and the conclusion no longer hangs on
one point.

**Takeaway for training:** durability is normal; the lever for sub-4 is chronic load,
not fade-resistance. Carry CTL in the 60s into Berlin and sub-4 is the likely outcome.

## 7. The chart (`marathon_v2.png` / `marathon_model.png`)

- **Panel A (durability):** every effort normalised to CTL=50 and maximal effort, on
  log-log distance/time axes. All distances (blue short -> red long) collapse onto one
  power law of slope `beta_d`. The grey band is the extrapolation to 42 km.
- **Panel B (fitness trend):** marathon-equivalent at maximal effort plotted against
  each date's actual CTL. The line dips through the Nov-Feb training gap and recovers;
  the March half point sits on the dipped line. Today's headline is the diamond.
- **Colour:** `RdYlBu_r`, blue = short, yellow = mid, red = long.

## 8. Caveats (carry these into any UI; do not let the point estimate stand alone)

1. **Extrapolation past the half.** The longest race is 21 km; the marathon is a 2x
   distance extrapolation. `beta_d` is well-behaved in-sample but unverified beyond
   21 km. Marathon-specific limiters (glycogen depletion, the late wall, fuelling) are
   absent from the data and from the band. Treat the interval as a floor, not the whole
   uncertainty.
2. **CTL is itself a model** built on Garmin `training_load`. Garbage-in risk if load
   values are off.
3. **The maximal-marathon HR (167) is an assumption.** Reasonable from the half data,
   but it is an input, not a fact.
4. **`phi` is identified mostly off one big detraining swing.** Persuasive, but it is
   one swing; expect the estimate to firm up (or move) as more varied-fitness efforts
   accumulate.
5. **Estimation uncertainty != race-day spread.** The credible interval is how well we
   know the curve; it does not include weather/course/pacing/fuelling variance on the
   day, which is often larger.

## 9. Integration plan for the fit platform

The prototype maps onto the existing "Marathon Prediction Trend" chart, which today
runs on the broken table. Suggested shape:

1. **Module** `fit/analysis/marathon/` exposing:
   - `extract_efforts(db) -> DataFrame` (Section 4 SQL + CTL/ATL features)
   - `fit(efforts) -> posterior` (cache to `marathon_posterior.nc`; refit on `fit sync`)
   - `predict(posterior, ctl, avg_hr, distance) -> (median, lo, hi, p_sub_goal)`
   - `trend_series(posterior, daily_load) -> DataFrame` (Panel B line + band)
2. **Headline** = `predict` at current CTL, maximal marathon effort, **with the 90%
   interval always shown**. Never render the point estimate alone (that reintroduces
   the false-precision problem we are escaping).
3. **Trend chart** = `trend_series` (fitness-tracking line + band) with per-effort
   points overlaid, coloured by distance. This is the replacement for the current
   chart's data source.
4. **Leave-one-out influence column.** For each effort, recompute the headline without
   it and store the delta. Surface efforts whose removal moves the headline > ~5 min,
   so no single race can silently own the number. (We saw exactly this with the linear
   model and the March half.)
5. **Refit cadence:** on `fit sync`, or nightly. Sampling is cheap.

This is analysis/reporting, not coaching notes; it does **not** go through the
`fit-coach` skill or `save_coaching_notes`. Keep it in the data/analysis layer.

## 10. Roadmap (in priority order)

1. **Freshness term (TSB = CTL - ATL).** Cheapest win. Currently a tapered race and a
   mid-block tempo at the same CTL are treated identically; a `psi * tsb` term separates
   them and should tighten the band. Data is already extracted (`atl`).
2. **Required-load projection.** Given a goal date (Berlin 2026) and a P(sub-4) target,
   invert the model to a required CTL, then to a required average weekly load and long-run
   progression. Turns prediction into a plan.
3. **Half-plus validation.** As longer efforts (25-35 km) accumulate, they directly test
   the 42 km extrapolation; weight them in the prior or as a validation hold-out.
4. **Hierarchical prior on `beta_d`** if the model is ever applied across multiple
   athletes (shrink each runner's exponent toward a population mean). Not needed for a
   single-athlete platform yet.
5. **Wire HRV/readiness** from `daily_health` as an alternative or complementary fitness
   signal to CTL.

## 11. Derived metrics the model unlocks (beyond the headline)

The fitted posterior is a calibrated map between fitness, distance, effort, and pace,
so a number of metrics fall out of the same parameters at no extra modelling cost.
Each entry below says what it is, how to compute it from the posterior, what existing
project metric it complements, and how much to trust it on current data. Figures are
from the April-2026 snapshot.

**A. Fitness valued in race time (from `phi`).** Translates the abstract CTL number
into pace. `+10 CTL ~ -2.7% ~ -9 sec/km ~ -6.4 min at the marathon` (about
-0.9 sec/km per single CTL point). Complements: the project tracks CTL but never says
what a CTL point is *worth*; this makes the fitness chart actionable. Trust: solid
(this is just `phi` rescaled), though identified mostly off one detraining swing.

**B. Cost of a layoff / detraining curve (from `phi` + CTL decay).** Combine the
42-day CTL decay with `phi` to price a break in race-time terms. From CTL 50:

```
 7 days off  -> CTL ~42  -> marathon +5.0 min  (+2.1%)
14 days off  -> CTL ~36  -> marathon +9.4 min  (+3.9%)
21 days off  -> CTL ~30  -> marathon +13 min   (+5.5%)
28 days off  -> CTL ~26  -> marathon +16 min   (+6.9%)
```

Complements: nothing in the project quantifies the cost of missed training; this turns
"don't take three weeks off" into a number. (It is also exactly what happened into the
March half.) Trust: solid as an illustration; the real curve depends on starting CTL.

**C. Durability exponent as a tracked metric (from `beta_d`).** A personal Riegel
exponent with a credible interval: `1.061 [1.031, 1.090]` (every doubling of distance
multiplies time by `2^1.061 = 2.087`). Refit on a rolling window to watch durability
trend. Complements: the project has ACWR, zones, and efficiency but no durability
metric at all; this is the one number that says how well you hold pace as distance
grows. Trust: the level is solid; a *trend* in it needs more long efforts (exploratory).

**D. HR-to-pace exchange rate (from `kappa`).** `+1 bpm of effort ~ -0.58% pace`
(`+5 bpm ~ -2.9%`). Useful for pacing decisions and for sanity-checking a target race
HR. Complements: sits alongside the existing speed/bpm efficiency metric, but as a
causal "what is a bpm worth" rather than a descriptive ratio. Trust: well-identified.

**E. Live, fitness-current race-equivalency table (whole posterior).** Predict every
distance at *today's* CTL and a distance-appropriate maximal HR, with intervals. At
CTL 50:

```
 5K  @ HR178 : ~4:40/km  (~23:20)   |  10K @ HR176 : ~4:55/km  (~49:10)
 HM  @ HR172 : ~5:16/km  (~1:51)     |   M  @ HR167 : ~5:39/km  (~3:59, 90% 3:48-4:09)
```

Complements / replaces: static Daniels VDOT equivalency tables, which assume a fixed
durability and never move. This one updates every `fit sync` and uses *your* exponent.
Trust: 5K-HM solid; the marathon row is the usual 2x extrapolation (Section 8). The HR
schedule is an input; expose it.

**F. Goal probability and required CTL (whole posterior).** P(goal | fitness), tracked
over time as a single moving number, plus the inverse (CTL needed for a target
probability):

```
P(sub-4:00) at CTL 50/55/60/65/70 = 0.58 / 0.74 / 0.82 / 0.87 / 0.90
CTL needed for P(sub-4:00) >= 0.80 : ~58      >= 0.90 : ~70
P(sub-3:45) at CTL 50/.../70       = 0.01 / 0.07 / 0.20 / 0.33 / 0.46
```

Complements: the project has the goal (Berlin, sub-4) but no probability attached to
it and no fitness target derived from it. This is the natural dashboard headline and
the bridge to roadmap item 2 (required-load projection). Trust: conditional on the
model; carry the Section 8 caveats.

**G. Performance residuals = a fitness- and effort-adjusted "day-quality" index.** For
each effort, `residual = observed log-time - model prediction(x, c, h)`. A positive
residual means slower than expected given distance, fitness, and effort; i.e. a bad
day after removing the things we can explain. Then correlate residuals against
race-day temperature, freshness (TSB = CTL - ATL), sleep, and HRV. Complements /
upgrades: the project already mines correlations and already flagged temperature
(~24 sec/km cold-to-warm); residuals are a *cleaner* input to that engine than raw
pace, because fitness and distance are already netted out, so a temperature or
sleep effect is not confounded by how fit or how long each effort was. Trust:
the residual itself is solid; correlating 30 of them is exploratory and should be
labelled as such until more efforts accumulate.

**H. Estimate confidence + data-gap flag (posterior spread).** The width of the
prediction interval is itself a metric: it narrows as you log more varied efforts and
widens where you have none. Right now it is widest at the marathon because the longest
race is a half. Surface this as "confidence: medium, limited by no efforts beyond
21 km" so the headline is never read as more certain than it is. Complements: nothing
in the project currently expresses its own uncertainty.

**Implementation note.** A, C, D are scalar transforms of single parameters and are
free. B, E, F, G, H all reuse the same `predict()` draws already in
`marathon_model.py`; add a `derived_metrics(posterior, daily_load)` function returning
a dict, and a `residuals(posterior, efforts)` helper that left-joins weather/sleep for
the correlation panel. None of these require refitting.

## 12. Appendix

**Daniels VDOT (used for the per-race equivalents in early exploration; not in the final model):**

```
v in m/min, t in min
VO2(v)   = -4.60 + 0.182258*v + 0.000104*v^2
pct(t)   = 0.8 + 0.1894393*exp(-0.012778*t) + 0.2989558*exp(-0.1932605*t)
VDOT     = VO2(v) / pct(t)
```

**Glossary.** CTL = chronic training load (fitness, 42-day EWMA of daily load).
ATL = acute training load (fatigue, 7-day EWMA). TSB = training stress balance =
CTL - ATL (freshness). LTHR = lactate threshold heart rate. Durability / fatigue
exponent = the Riegel power-law exponent; ~1.06 is typical, higher means more fade
over distance.

**File manifest.**

| file                   | purpose                                              |
|------------------------|------------------------------------------------------|
| `marathon_model.py`    | self-contained reference: extract, fit, predict, chart |
| `marathon_v2.png`      | reference 2-panel chart (this snapshot)              |
| `HANDOVER.md`          | this document                                        |
