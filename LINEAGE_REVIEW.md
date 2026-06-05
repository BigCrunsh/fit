# Lineage & Forecast Architecture — Critical Review

A data-engineering + training-science challenge of the dashboard's metric lineage
(`DATA_LINEAGE.md`) in the context of the incoming Bayesian marathon model
(`openspec/changes/marathon-durability-model/`). Each finding: evidence (file:line
/ queried data), the data lens, the training lens, severity, and the fix.

Grounding data (queried from `~/.fit/fitness.db`; concrete personal values
generalised — this is a public repo): ~2 years of running history; a few dozen
model-qualifying efforts (races + tempo/progression Hard/Very-Hard); **longest
effort ever ≈ a half-marathon — zero efforts beyond it, none near 30 km.** The
effort distances cluster heavily in the 10 km range, thin out toward the half,
and stop there. Race HR falls as distance rises (10 k's run at clearly higher HR
than halves) — i.e. the longer efforts were run easier.

---

## Headline

The dashboard already shows **at least two marathon-equivalent times that can
disagree**, the Bayesian model would add a **third**, and the single number most
people will read off it — the marathon forecast — is the **least supported point
in the entire system** (a 2× extrapolation past zero data). Before the model ships,
the forecast lineage has to be collapsed to one path and the marathon prediction
has to be labelled as a ceiling, not a point estimate. None of this is a model-math
problem; it's an architecture-and-honesty problem.

Priority order: **F1 (collapse the forecasts) → F3 (maximality bias) → F6 (fallback
hazard) → F2 (two fitness models) → F4/F5 (honesty of the headline numbers).**

---

## F1 — Three live marathon forecasts on one dashboard · **HIGH**

**Evidence.** Two paths are live today and produce different numbers from the same data:
- **Riegel path** — `predictions.py:50`, hardcoded exponent `1.06`: `t2 = t1 * (target/d1)**1.06` off raw race times.
- **VDOT-table path** — `predictions.py:55`, `_vdot_to_marathon_seconds(vo2max)` (the old conservative table), then re-scaled by `1.06`. Same table still wired in `cards.py:1358/1422/1976`, `charts.py:952`. `_prediction_summary` literally takes `min`/`max` of the two as a "range" (`predictions.py:65-66`).
- **VDOT-anchor path** — `cards.py` `_vdot_comparison`/`_pace_zones` derive race-equivalents from the calibrated VDOT anchor via `vdot_to_race_time` (the formula inverse). Different number again.

The Bayesian model is specced to *own* the forecast (`proposal.md` "replaces the single-scalar prediction") — so it would be a **third** path unless the others are removed. This is duplication item **D1**, and it is **not** fixed despite the M-pace anchor work.

**Data lens.** Three code paths, three transforms, one concept. `min/max` over two of them isn't an uncertainty interval — it's the spread between a known-broken table and a fixed-exponent heuristic, presented as "moderate confidence."

**Training lens.** An athlete checking their Berlin time sees different numbers in different cards and can't tell which to believe or train toward.

**Fix.** Make the Bayesian posterior the single forecast source; delete the
`_vdot_to_marathon_seconds` table and the Riegel `_prediction_summary` blend; keep
the VDOT anchor for *training paces only* (Daniels zones), not race-day equivalents.
Until the model lands, pick **one** path as canonical and retire the others.

---

## F3 — The "canonical" VDOT anchor bakes in the bias the model is built to remove · **MED-HIGH**

**Evidence.** `compute_vdot_from_race` (`fitness.py:247`) docstring: *"Assumes a
near-maximal, evenly-paced effort."* The Bayesian model (`proposal.md` features)
**explicitly rejects** this — maximality is the HR covariate `h = (avg_hr − LTHR)/5`,
because "a race can be submaximal." Your data proves the point: HMs were run at
halves run at clearly lower HR than 10 k's — i.e. the halves were genuinely
submaximal, so the VDOT computed from them is **systematically understated**, and that value
feeds the sticky anchor (`get_calibration_anchor`).

**Data lens.** The metric we labelled "canonical" (green in the lineage) inherits a
maximality assumption a *downstream* metric is engineered to correct. Two transforms
on the same `(distance, time, avg_hr)` row encode contradictory assumptions.

**Training lens.** Anchor VDOT reads low after a season of submaximal long efforts,
so Daniels training paces drift slightly easy — self-reinforcing.

**Fix.** Either (a) feed effort/HR into the VDOT estimate so submaximal efforts are
discounted consistently with the model, or (b) explicitly scope the anchor as
"VDOT from best maximal efforts only" and document that long-run efforts don't move
it. Decide before the model ships so both layers treat maximality the same way.

---

## F6 — Posterior staleness silently falls back to the *old broken* forecast · **MED**

**Evidence.** `proposal.md` "Report-time": *"if absent/stale it falls back to the
existing simple prediction."* The "existing simple prediction" is exactly the F1
table/Riegel path. So a stale `~/.fit/marathon_posterior.nc` makes the dashboard
revert — without saying so — to the number we're trying to retire.

**Data lens.** The forecast lineage becomes *conditional/bimodal* and the doc draws
it as one clean edge. A stale cache changes the meaning of the headline with no
visual signal.

**Training lens.** The athlete sees a forecast jump (and an interval vanish) on a
day they didn't race, purely because the cache expired.

**Fix.** Draw the branch in the lineage. Make the fallback **loud** (e.g. "model
stale — showing heuristic estimate, no interval"). Never let the fallback reuse the
broken table; if the model is the truth, its absence should degrade to "unknown," not
to a worse model presented identically.

---

## F2 — Two fitness models on the same opaque input · **MED**

**Evidence.** ACWR = rolling-7d acute / ISO-week chronic (`analysis.py:541`
`compute_rolling_acwr`), built on `SUM(training_load)`. The Bayesian model introduces
**CTL/ATL** = EWMAs of the *same* `training_load`, "strictly before each effort"
(`proposal.md`). Both claim to summarise chronic fitness / acute fatigue, with
different windows and math. And `training_load` is itself a **Garmin black box** —
we don't compute it; the lineage should flag it as opaque/non-reproducible. The model's
daily load also *includes cross-training* (`SUM(...) GROUP BY date`), while the rest of
the running dashboard is running-only — possibly different denominators for "fitness."

**Data lens.** One opaque source → two overlapping fitness models that can disagree
on screen (ACWR "fine" while CTL says detraining; TSB vs ACWR fatigue read).

**Training lens.** Mixed messages: a coach should give one load/fatigue story, not two.

**Fix.** Decide the relationship explicitly — is ACWR redundant once TSB (CTL−ATL)
exists, or do they answer different questions (injury-risk ratio vs fitness trend)?
Reconcile in the model's "spine not island" section; mark `training_load` opaque in
the lineage; align the cross-training treatment.

---

## F4 — β_d is prior-dominated; "your durability" is mostly textbook · **MED**

**Evidence.** A few dozen efforts, and within them **distance and HR are correlated**
(long = easier, per the grounding data). The model wants to split "fade from distance"
(β_d) from "fade from easing off" (κ), but in this data they're entangled, so the
`β_d ~ N(1.06, 0.05)` prior carries much of the load. Your raw 10k→HM exponent comes
out **above** the textbook 1.06, but most of that gap is the effort difference (the
half run easier), not physiology.

**Data lens.** `proposal.md` claims "the data dominates" — at this sample size with
collinear covariates that's likely false for β_d. Reporting a tight personal exponent
with a narrow interval as a measured
personal trait overstates what the data identifies.

**Training lens.** "Your durability is textbook" is nearly tautological when we *told*
the model textbook and the data can't move it far.

**Fix.** Report β_d with an honest "prior vs data" note (how far the posterior moved
from the prior); consider a prior-sensitivity check; don't headline β_d as a measured
personal property until varied-effort, longer efforts identify it.

---

## F5 — The marathon forecast is a 2× extrapolation past zero data · **HIGH (training honesty)**

**Evidence.** Longest effort ≈ a half-marathon; **zero** efforts beyond it, none near
30 km. The marathon (42.195) sits entirely outside the data. The 30–32 km region —
glycogen depletion / the wall / fuelling / 3.5h thermoregulation — is a *regime change*
a single power-law cannot represent. (Delivered earlier as the durability answer;
recorded here for completeness.) Note the internal contradiction: the fitted β_d reads
"good durability," while the *measured* resilience drift-onset (`_compute_resilience`)
says form-holding is unproven much past mid-distance. Two "durability" readouts, opposite stories.

**Fix.** Label the marathon number a **fitness ceiling, not a prediction**; treat the
interval as a floor; show the "no data > 21 km" gap explicitly; the real fix is a
30 km+ effort in the plan to give the curve its first data point in that range.

---

## What becomes backlog vs design

| # | Finding | Action | Where |
|---|---------|--------|-------|
| F1 | Three forecasts | **Fix now** — collapse to one path | D1 (do first) |
| F3 | Maximality bias in anchor | Design decision before model ships | new D-item + model spec |
| F6 | Stale-posterior fallback | Loud fallback + draw the branch | model spec |
| F2 | ACWR vs CTL/ATL | Reconcile in "spine not island" | model spec |
| F4 | β_d prior-dominated | Honesty note + prior-sensitivity | model spec |
| F5 | Marathon extrapolation | Ceiling framing + 30 km+ in plan | model spec + training plan |

---

# Appendix — D1 implementation plan (collapse the forecasts)

**Decision taken:** interim canonical = the **VDOT-anchor path** via the Daniels
formula inverse `vdot_to_race_time(vdot, distance_km)` (`fitness.py:285`), fed by
`get_calibration_anchor(conn, 'vdot')` — not raw latest Garmin VO2max, not the
`_vdot_to_marathon_seconds` table. This removes both the broken table **and** the
"latest Garmin reading" input in one move (addresses F1; partially F3).

### One new helper (single source of truth)
Add `anchor_race_time(conn, distance_km) -> int | None`:
reads the VDOT anchor, returns `vdot_to_race_time(anchor['value'], distance_km)`,
or `None` if no anchor. Every "VDOT estimate" leg below calls this — no module
recomputes the conversion.

### Sites to switch (table → anchor) — 6 + the core
| # | File:line | Today | After |
|---|-----------|-------|-------|
| 1 | `analysis.py:723` (inside `predict_race_time`, the `vdot` leg) | `_vdot_to_marathon_seconds(vo2max)` | `vdot_to_race_time(vdot, marathon_km)` — caller passes anchor VDOT, not Garmin VO2max |
| 2 | `predictions.py:55` (`_prediction_summary` headline blend) | table + Riegel `min/max` | `anchor_race_time(conn, target_km)` is the headline |
| 3 | `predictions.py:139` (`_race_prediction`, "VO2max Estimate (Daniels)" row) | `_vdot_to_marathon_seconds(latest vo2max)` | `anchor_race_time(conn, target_km)` |
| 4 | `cards.py:1358` | table | `anchor_race_time` |
| 5 | `cards.py:1976` (weekly vo2max_avg → marathon) | table | anchor (or drop the series if it duplicates the headline) |
| 6 | `charts.py:952` (VO2max-over-time → marathon-equivalent series) | table per weekly avg | anchor-based, or relabel as "Garmin VO2max trend" and stop converting to a time |
| 7 | `cards.py:1421-1422` (calibration delta: old vs new VDOT → minutes) | `_vdot_to_marathon_seconds(old/new)` | `vdot_to_race_time(old/new, target_km)` — same intent, correct converter |

### Kept deliberately (not the broken table)
- **Per-race Riegel rows** in `_race_prediction` (exponent 1.06 off each real race,
  `predictions.py:120-133`) — transparent, informational, clearly per-race; the
  Bayesian model will supersede it. Headline stops blending it; table keeps showing it.

### Open approval — delete vs deprecate the table
Once the 7 sites are off it, `_vdot_to_marathon_seconds` + `_VDOT_TABLE`
(`analysis.py:573-667`) are dead. **Recommend deleting** (git preserves history; no
reason to keep a known-pessimistic converter). Flagging because it's a removal —
say "deprecate instead" if you'd rather leave it marked-unused until the model lands.

### Tests
- Audit `tests/` for `_vdot_to_marathon_seconds` and prediction-shape assertions;
  update to the anchor path.
- Add regression: headline marathon time == `vdot_to_race_time(anchor_vdot, 42.195)`;
  assert no dashboard path imports the table (grep-style guard or unit).
- 2:1 unhappy:happy — no anchor (None/graceful), stale anchor, anchor below VO2max>30
  gate, target_km ≠ 42.195 scaling.

### Status — Phase 1 implemented (2026-06-05)

**Done.** The headline/current-value consumers now route through `anchor_race_time`:
`predict_race_time` vdot leg, both `_prediction_summary`s, the `_race_prediction`
"VDOT Anchor (Daniels)" row, and the countdown `center_secs`. New
`anchor_race_time(conn, distance_km)` (`fitness.py`) and `riegel_fallback_secs`
(`analysis.py`) are the single sources. Cold-start (no anchor) falls back to the
**conservative Riegel extrapolation from real races**, never the table.

**Before → after: the headline got ~10 min slower** — the *opposite* of my plan's
prediction, and the after-number is the honest one. The old path fed an **optimistic
Garmin VO2max** into a **pessimistic table** (two errors partly cancelling); the anchor
path uses the race-calibrated VDOT (well-supported by the race-implied values) → the
slower number. New sub-finding: **Garmin VO2max sits well above race-implied VDOT** —
anything forecasting off Garmin VO2max is inflated.

**Tests:** new `tests/test_forecast_anchor.py` (anchor/ fallback / source-priority,
2:1 unhappy:happy); 2 obsolete `predict_race_time(vo2max=…)` tests in
`test_analysis.py` + 2 in `test_coaching_metrics.py` converted to the new contract
(no tests skipped). Full suite **1006 passing**.

**NOT yet done — Phase 2 (trend time-series) + table deletion.** Three consumers
still use `_vdot_to_marathon_seconds`: `_prediction_trend_data` (weekly VO2max→time),
the `trend_badge`, and the charts "VDOT (from VO2max)" line. They plot a *time-series*;
the anchor is a single current value with **no history**, so they can't swap to it,
and treating Garmin VO2max as VDOT would re-inject the inflation. This is exactly the
job of the Bayesian model's `trend_series`.

**Decision (2026-06-05): defer Phase 2 to the marathon-durability-model.** The
trend charts keep using `_vdot_to_marathon_seconds` for now, flagged with
`TODO(marathon-durability-model)` at the table def; the model's `trend_series`
replaces those charts, and the table + `_VDOT_TABLE` are deleted then. Building a
throwaway race-VDOT time-series now was rejected; relabelling to a raw-VO2max axis
was rejected (changes the chart's meaning for an interim).

