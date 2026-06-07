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

- **T₀** — the duration at which a maximal effort sits *at* LTHR (offset 0). The physiological definition of LTHR (maximal lactate steady state, sustainable ~30–60 min). **Personalised**: pinned to the athlete's genuine maximal effort whose HR is nearest LTHR; population fallback ~55 min for a cold-start athlete.
- **β** — the fade slope (bpm per natural-log-unit of duration), a **population** constant (~−6.5). Reusable shape; learnable per-athlete later from multiple maximal efforts.

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

- **Forecast stays stable for the current athlete** — because T₀ derives from their data (maximal HM at ≈ LTHR ⇒ T₀ ≈ 111 min), the law reproduces the validated anchors, so the 4:03:55 headline does not shift materially. The marathon residual (−4.76 vs −6 bpm ≈ ~2 min) is the one flagged decision (single slope vs slight curvature).
- **Generalises across distance and goal with no special-casing** — changing the goal (marathon → HM) already works today (the schedule is distance-keyed, the goal only selects the point); this change makes the *per-distance* assumption itself fitness-aware.
- **Code**: `fit/marathon/predict.py` (`maximal_effort_h`, the one-pass solve, the five internal callers); the MaxHR cap (`hr_reserve`) carries over unchanged. No DB/schema change. The constants move from a four-row table to two justified parameters, updating the `design.md` "Constants & assumptions" justification.
- **Specs**: `adaptive-predictions` — a new requirement that the maximal-effort HR assumption is duration-keyed and generalises across distance/goal.

Affected capability: **adaptive-predictions**.
