# Glossary — ubiquitous language for `fit`

**`fit` is a personal marathon-training data platform.** It pulls training and health data
(Garmin, Apple Health, weather, race results) into a local SQLite database, derives the
metrics a coach would track — fitness, training load, recovery, durability — forecasts your
race time, and renders an HTML coaching dashboard (with a CLI and an MCP server for an AI
coach on the side). The [README](../README.md) has the setup and product tour.

This file is the project's **shared vocabulary** — its *ubiquitous language*. Code, dashboard
copy, and docs all use these terms with exactly these meanings; **a name that contradicts the
glossary is a bug.** It's an engineering doc, but written to be read cold:

- **New here?** Read **Foundations** first — the running physiology everything else builds
  on — then the grouped **Core vocabulary**.
- **What vs how.** This doc says *what a term means*. Its sibling
  [`DATA_LINEAGE.md`](DATA_LINEAGE.md) says *how the number is computed* (source → metric).
- **Where decisions live.** The `/ddd-model-review` skill loads this file as the agreed
  glossary and reconciles code against it, one bounded context at a time. A review's output
  lands **here** (a vocabulary decision), in `DATA_LINEAGE.md` (a data-flow fact), or becomes
  an **OpenSpec change** (an action) — reviews are scaffolding, not standing docs.

> History: promoted from `DATA_LINEAGE.md §6` and consolidated with the former
> `DDD_REVIEW.md` / `LINEAGE_REVIEW.md` reviews on 2026-06-11 (git keeps their history).

---

## Foundations (running physiology)

The measured quantities the rest of the vocabulary stands on. If a term further down is new,
the reason is usually here.

- **VO2max** — the maximum rate your body can use oxygen; the physiological ceiling of
  aerobic capacity (ml/kg/min). Higher = fitter.
- **VDOT** — Jack Daniels' race-derived fitness index: the VO2max-equivalent *implied by an
  actual race time* (from his *Running Formula*). This is the fitness number `fit` trusts —
  *earned on the clock*, not guessed — and it is NEVER interchangeable with VO2max.
  Calibration metric `vdot`. Assumes the race was **near-maximal** — a deliberately easy effort
  understates it.
- **Garmin VO2max** — the wrist device's *estimate* of VO2max (`activities.vo2max`). *Guessed
  by the wrist*, and for this athlete it reads well above race-implied VDOT — so it is
  **reference-only**: shown for context, never a fitness anchor and never a forecast input.
- **LTHR** (lactate-threshold heart rate) — the HR at your sustainable hard-effort threshold
  (~1-hour race pace). The primary anchor for HR training zones.
- **AeT** (aerobic threshold) — the upper bound of *easy* aerobic effort, below LTHR; it marks
  the Z2 ceiling (the line easy runs must stay under).
- **MaxHR** — the highest heart rate you can reach.
- **HR zones Z1–Z5** — five intensity bands from recovery (Z1) to VO2max effort (Z5), set as a
  percentage of LTHR (the primary model) or MaxHR (fallback). Z2 = easy aerobic.
- **RPE / sRPE** — Rate of Perceived Exertion (how hard it felt, 1–10); **session-RPE** =
  RPE × minutes, a simple training-load proxy.

---

## Core vocabulary

The system and domain concepts built on the foundations above, grouped by area.

### Calibration & anchors

*The calibration system answers two questions: what single value do we trust per metric, and
how much do we trust each source it could come from?*

- **Calibration anchor** — the single canonical value per physiological metric
  (`get_calibration_anchor`). Trust precedence: **human confirm > device measurement >
  policy estimate (what races imply) > legacy**.
- **Method trust taxonomy** — every calibration `method` carries one of six ordered trust
  tiers: `INFORMATIONAL < REFERENCE < LEGACY < POLICY < DEVICE < CONFIRMED`. **Anchor-eligible
  = `LEGACY` and above** (`REFERENCE`/`INFORMATIONAL` are recorded for history/context but
  never become the anchor); among the eligible, the highest tier wins
  (`CONFIRMED > DEVICE > POLICY > LEGACY`). Method → tier:
  - `CONFIRMED` — `manual`, `confirmed` (human-owned, sticky)
  - `DEVICE` — `device_lt` (instrument measurement, authoritative below a human)
  - `POLICY` — the synthesized windowed *suggestion* (not a stored method)
  - `LEGACY` — the auto-derived candidates (`race_candidate`, `activity_max`, `drift_test`,
    `scale`) **and** any unrecognised method
  - `REFERENCE` — `device_vo2max` (context only, never an estimator input)
  - `INFORMATIONAL` — `race_observation`, `effort_observation` (history/chart rows)

  *(Method strings renamed in migration 016 — formerly `garmin_lt`, `garmin_estimate`,
  `race_estimate`/`effort_estimate`, `race_extract`.)*
- **State reading vs estimator-backed anchor** — two kinds of calibration metric.
  *State readings* (`weight`) are latest-value: the current reading is the truth, age only
  raises a staleness warning, no aggregation. *Estimator-backed anchors* (`vdot`, `lthr`,
  `max_hr`, `aet`) are noisy snapshots where the windowed statistic — not the latest
  reading — is representative: a trailing window yields a *suggestion* + staleness, and the
  active value stays the human-confirmed sticky value (never auto-overwritten). `vo2max` is
  a *reference reading* — latest-value like weight, but reference-only and **never an
  anchor** (see Garmin VO2max). Encoded as "has an `AGGREGATION_POLICY` or not"; only the
  estimator-backed metrics are "anchors" in the precedence sense above.

### Training load

- **Chronic load** — THE fitness-state primitive: trailing mean of daily
  `training_load` over a window (`fit.training_load.chronic_load_before`). One windowing
  model, not two. The forecast's fitness covariate counts **all** activities (aerobic
  fitness); ACWR's chronic counts **running only** (running mechanical-load injury risk).
  Same primitive, activity filter chosen per question — never two ISO-vs-rolling formulas.
- **ACWR** (acute:chronic workload ratio) — acute (rolling 7d) ÷ chronic load: the
  *injury-risk ratio*. Not a fitness trend — that's the chronic level itself.

### Durability & forecast

- **Resilience** — aerobic-decoupling onset: the km at which HR:pace decouples >5% within
  a run (a cardiac/thermal signal). The dimension value is a **one-sided, right-censored**
  estimate (a no-drift run is a *lower bound* — durable to *at least* its distance), weighted
  by recency and run length and shrunk to a prior when thin/stale, reported with an asymmetric
  uncertainty band + confidence. NOT the same as…
- **Pace-fade** — speed give-back over a long run's second half at ≥ Moderate effort
  (a glycogen/neuromuscular signal; the evidence-backed marathon-durability marker).
- **Effort (qualifying)** — a continuous intensity-bearing run: a race, or
  tempo/progression at Hard/Very-Hard effort. Intervals are excluded (their distance
  includes recoveries). Maximality is carried by HR (`h`), never assumed from the label.
- **Marathon forecast** — the single race-day prediction: **median finish time + 90% range +
  P(reaching your goal)**, produced by the Bayesian durability model (`fit/marathon/`) and
  read identically everywhere (dashboard, `fit forecast` CLI, AI-coach context). Degrades to
  the simpler VDOT-anchor estimate (`anchor_race_time`) when the model can't run. *Model
  internals — the duration-keyed effort schedule and the coefficients β_d / φ / κ — are
  documented in [`DATA_LINEAGE.md`](DATA_LINEAGE.md) and the marathon-model spec.*
- **Extrapolation penalty (γ)** — a penalty that *widens the forecast's range* the further
  the race distance is past your longest run (`d_max`). Driven by long-run distance +
  Pace-fade, NOT cardiac drift. *(Distribution detail in the model spec; drafted as `s_drift`
  and renamed — drift doesn't drive it.)*

*The next three are model coefficients — skip unless you're reading the forecast model.*
Each is a **slope** of the regression `log t = α + β_d·x + φ·c + κ·h`, and the dashboard
visualises each as an **added-variable panel** — the covariate vs marathon-equivalent time
with the other two netted out, posterior median line + HDI ribbon (greyed when prior-dominated),
so the line's steepness *is* the coefficient (durability-param-panels).

- **β_d (durability exponent)** — the fitted Riegel power-law slope: the *optimistic*
  cross-distance bound ("what holds if the power law extends"). The dashboard leads with the
  measured Resilience/Pace-fade signals when they disagree with it.
- **φ (fitness value)** — the coefficient for how much fitness (chronic load) moves the
  forecast. Shown with a *prior-dominated* flag when the data can't shift it off the textbook
  prior — so it's never sold as "measured" when it isn't.
- **κ (HR↔pace coupling)** — the coefficient linking the assumed race HR to pace.
- **EffortDataset** — the model's input value object (`fit.marathon.features`): the efforts
  frame + `d_max`, `lthr`, `goal`. An explicit contract, not DataFrame `.attrs`.

### Planning & naming

- **Objective** — the athlete-facing term for a training target (the UI says "objectives").
  Auto-derived from the target race via `derive_objectives()`; never manually CRUD'd. `goals`
  is only the persistence name — the domain term is *Objective*, and code should speak it.
  *(Naming decision; code still mixes the two — a code rename is a candidate OpenSpec change.)*
- **readiness** — reserved for Garmin's measured **training readiness**
  (`daily_health.training_readiness`). Two adjacent decisions are deliberately *not*
  "readiness": phase advancement (whether to progress the training phase) and today's
  go/no-go (whether to do the planned session). One measured metric, one word — the other
  two senses get distinct names. *(Naming decision; the overloaded functions are a candidate
  OpenSpec change.)*

---

## Physio Calibration — concept reference (for contributors)

The most deeply-modelled context (the model context for the rest) — this table is optional
depth for people working in the code. SSOT module: `fit/calibration.py`. `grain / lifecycle`
is what the concept is keyed on and how it changes.

> **DDD roles** (the `role` column): **Entity** = has identity + a lifecycle · **Value
> object** = defined entirely by its values, immutable · **Domain service** = a stateless
> operation over them · **Domain policy** = a named rule set.

| term | definition | role | grain / lifecycle |
|------|------------|------|-------------------|
| **Calibration** (reading) | One recorded value of a metric, with method, confidence, date, flags | Entity | one observation; inserted `active=1`, prior rows flip to `0`; never updated, only superseded |
| **Calibration anchor** | The single canonical value per metric, resolved by precedence (see Core vocabulary) | Value object (from a domain service) | one per metric, recomputed every read; `value` is always present or the anchor is `None` |
| **Metric** | The quantity calibrated: `max_hr`, `lthr`, `aet`, `vdot`, `vo2max`, `weight` | Value object / enum | string key |
| **Method** | Reading provenance (`manual`, `confirmed`, `device_lt`, `device_vo2max`, `race_observation`, `effort_observation`, `race_candidate`, `activity_max`, `drift_test`, `scale`) | Value object / enum | persisted string (migration 016); each carries a trust tier |
| **Trust tier** | The six-tier order a method's trust resolves to (see *Method trust taxonomy* above); anchor-eligible = `LEGACY` and up | Classification VO | intrinsic to method |
| **Confidence** | `high / medium / low` quality of a reading | Value object (ordered) | per reading; `stale → low` at query time |
| **Aggregation policy** | Per-metric estimator — `max` (one-sided: VDOT, MaxHR) vs `median` (two-sided: LTHR, AeT) + window, min_samples, `differs` | Domain policy | one per estimator-backed metric |
| **Suggestion (policy estimate)** | Windowed aggregate of observation rows + `differs` flag + reason + inputs | Value object | one per metric per read; `None` if no in-window observation |
| **Flag taxonomy** | Per-reading tags: `implausible_value`, `agrees_with_prior`, `unexpected_direction`, `new_peak`, `weak_context` | Value object (set) | per reading |
| **Staleness** | Value older than the metric's threshold → prompt a re-test | Domain rule | per metric |
| **Suggest→confirm governance** | `evaluate_suggestions` → accept (writes a `confirmed` anchor) / reject (ledger suppresses re-nag) | Domain service + JSON ledger | `calibration_review.json` sidecar |

## Bounded contexts (module → context)

```
Integration/ACL      garmin · apple_health · weather
Ingestion            sync
Physio Calibration   calibration                      (the model context for the rest)
Training Load        training_load   (queued from analysis: weekly_agg · monotony · sRPE)
Performance/Forecast fitness (Daniels) · marathon/ · prediction
Planning             goals · plan · periodization · milestones
Self-report          checkin
Insight/Narrative    correlations · alerts · narratives · coach-MCP
Presentation         report/
```
`analysis.py` is split along these seams incrementally (re-export shims left behind);
new load code lands in `training_load`.
