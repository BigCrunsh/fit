## Why

The marathon forecast assumes a **maximal-effort heart rate** for each distance — the HR you would actually race at — because a forecast has no measured `avg_hr` to feed the model's effort covariate `h = (avg_hr − LTHR)/H_DIV`. Today that assumption is a hardcoded four-point table keyed on **distance**:

```python
_MAXIMAL_HR_OFFSET = [(5.0, 10.0), (10.0, 5.0), (21.0975, 0.0), (42.195, -6.0)]  # (km, bpm vs LTHR)
```

Distance is the wrong axis. The physiology is **duration**-driven: how far above or below threshold you can hold depends on how long you are out there, not on the kilometre count. "Half-marathon ≈ LTHR" is only true if your HM takes ~the threshold-sustainable time; a slower runner's HM lasts much longer and sits *below* LTHR. Mapping fixed distances to fixed HR offsets silently bakes in an assumption about *how fast you cover the distance* — i.e. it assumes a fitness level. That is exactly the distance↔fitness confound the durability model exists to remove, so re-introducing it in the effort assumption is self-defeating. It also forces interpolation for any non-anchor distance (15 K, 30 K) and is a four-number hardcoding rather than a parameterised law.

A duration-keyed law fixes all of this with **fewer, more meaningful constants** and reproduces the validated table almost exactly.

## What Changes

Replace the four-point distance table with a two-parameter **log-duration** law:

```
offset(t) = β · ( log t − log T₀ )        # bpm vs LTHR, t = predicted maximal-effort duration
h(d)      = offset( t(d) ) / H_DIV         # t(d) = the model's own predicted time at distance d
```

Both parameters are **population priors the athlete's data updates** (a precision-weighted shrinkage estimate — the same prior+data treatment the durability model already gives `β_d`). Sparse/noisy data stays at the population value; enough consistent race data personalises. This dissolves the "measure durability but *assume* the effort-fade" inconsistency and is robust by construction — no single race can break it.

- **T₀** — the duration at which a maximal effort sits *at* LTHR (offset 0). Prior ~55 min (textbook threshold-sustainable duration); updated by where the athlete's races cross LTHR, weighted by **recency** (so it tracks fitness) and **representativeness** (efforts nearer the goal duration count more). Lands ≈ the athlete's half (~110–120 min) from several recent HMs near threshold — not a hand-picked race. (A single-point "nearest-LTHR race" rule breaks on the real data: LTHR is now 171, so the nearest is a sub-maximal 25-min 5 K → a ~15-min-too-slow forecast. The prior makes that impossible.)
- **β** — the fade slope (bpm per natural-log-unit of duration). Prior ~−6.5 (population duration–intensity fade); updated by the athlete's race HR-vs-log-duration slope, regularised by the prior so a sparse/noisy fit can't run away.

`maximal_effort_h` becomes keyed on duration; its callers do a **one-pass coupling** (predict `t(d)` with a seed `h`, recompute `h` from `t(d)`, predict once more — the correction is <0.5 % because `κ` is small).

### Why this is correct, not just different

Expressed in **this athlete's own predicted maximal durations** (5 K 22.5 min, 10 K 48.6 min, HM 111 min, M 244 min), fitting (T₀, β) to two anchors reproduces the rest:

| Distance | duration | table offset | duration-law offset |
|---|---|---|---|
| 5 K | 22.5 min | +10.0 | **+9.65** |
| 10 K | 48.6 min | +5.0 | +5.00 *(anchor)* |
| HM | 111 min | 0.0 | 0.00 *(anchor)* |
| M | 244 min | −6.0 | **−4.76** |

The four-point table *was* a two-parameter log-duration curve all along. The duration law recovers it **and** generalises it — speed-aware, goal-independent, defined for every distance.

## Impact

- **Forecast stays stable for the current athlete** — the shrinkage estimate lands T₀ ≈ the athlete's half (~110–120 min, from several recent HMs near threshold), so the law reproduces the validated anchors and the headline does not shift materially. The marathon residual (−4.8 vs −6 bpm ≈ ~2 min) is the one flagged decision (single slope vs slight curvature) and rides on the prior at cold-start.
- **Robust by construction** — population priors + recency-/representativeness-weighted updates mean no single race breaks the estimate; the literal "nearest-LTHR race" rule (earlier draft) would have produced T₀ = 25 min on the current data — the prior makes that impossible.
- **Generalises across distance and goal with no special-casing** — keyed to predicted duration, so changing the goal (marathon → HM) needs no special case; the per-distance assumption is itself fitness-aware.
- **Code**: `fit/marathon/predict.py` (`effort_schedule` shrinkage estimate, `maximal_effort_h` re-keyed on duration, the `effort_h_for_distance` two-pass solve, the five internal + two display callers); the MaxHR cap carries over unchanged. No DB/schema change. Plus **D15** (route the three hardcoded Riegel `1.06`s through one constant — separate, mechanical).
- **Specs**: `adaptive-predictions` — the maximal-effort HR assumption is duration-keyed, prior+data, and generalises across distance/goal.

Affected capability: **adaptive-predictions**.
