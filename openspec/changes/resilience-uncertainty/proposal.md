## Why

The Long-Run Resilience metric (drift onset km) is the marathon **limiter** — the single dimension currently holding the forecast back — yet it is the least honest about how much it actually knows. It is reported as one number: the `max` drift onset over recent qualifying runs in a hard 28-day window, with **no uncertainty** and **no recency or length weighting**. Three problems, all of which the athlete correctly intuited:

- **It's a right-censored lower bound presented as a point.** A *no-drift* run only tells us durability is **≥** the run distance — we can't see past the end of the run; a *drift-detected* run is a real observation of where decoupling began. Today the value and the chart don't distinguish "observed onset at km 11" from "held to ≥ 20 km," so "20.1 km" reads as a measured point when it is a floor.
- **No recency weighting, though durability is trainable and detrainable.** A stale heroic long run overstates *current* durability after a down block / illness / taper. The 28-day window is also a **hard cutoff** (a 27-day-old run counts fully, a 29-day-old counts zero) over a thin sample — long runs come ~weekly, so ~4 points.
- **No length weighting.** Only long runs can reveal *late* drift — a 9 km run is silent about km 20+, the very distances the marathon depends on — yet every in-window run counts equally toward the `max`.

So the platform's most decision-relevant dimension is point-only and un-weighted.

## What Changes

Replace the raw-max point with a **recency- and length-weighted, censored estimate plus an asymmetric uncertainty band**, and make the chart show the censoring — the same shrinkage shape already used for **T₀** (the maximal-effort schedule) and the **VDOT anchor**:

- Each qualifying run contributes either an **observed** onset (drift detected) or a **right-censored lower bound** at its full distance (no drift) — the censoring is carried, not collapsed.
- Each run is **weighted** by recency (a smooth half-life decay replacing the hard cutoff) × length (longer runs inform late-km durability more).
- The point estimate is the weighted best-demonstrated onset, **shrunk toward a prior when the effective sample is thin or stale** (cold-start → the prior, not a confident number).
- An **asymmetric band**: a well-supported lower floor ("demonstrated to at least …") and a wider upper bound (censored upside — unobserved late km), **widening with staleness, thin data, and short-run coverage**.
- The drift-onset **trend chart distinguishes observed vs ≥-bound markers** (solid dot vs open ▲), draws the band, and shows a **confidence badge** (low/med/high) — the same pattern as the prediction-confidence chip.

Drift onset still comes from `compute_cardiac_drift` (the ONE source, grade-adjusted, pace-CV-gated); this change only alters how the per-run points are **aggregated** into the dimension value + band.

## Impact

- The resilience `current_value` semantics change from **raw recent max → weighted, shrink-to-prior estimate** (the headline can move slightly and is now defensible); new `band` (asymmetric lo/hi) and `confidence` fields are exposed. The Distance Ceiling ("What You Can Run Today") reads the new estimate.
- The athlete sees *how much* the durability read is trusted and *why* (recent long evidence vs stale/thin), and the chart no longer implies a measured point where it is a floor.
- Consistency: mirrors T₀'s recency-/representativeness-weighted shrink-to-prior, so resilience stops being the one un-weighted, point-only dimension.
- **Code**: `fit/fitness.py` (`_compute_resilience` → weighted censored estimator + band + confidence; new judgment-informed constants for the recency half-life, length weighting, shrinkage strength, and cold-start prior), `fit/report/sections/charts.py` (`chart-drift-trend` censored markers + band), `fit/report/sections/cards.py` (dimension band/confidence surfacing + def-box disclosure). No DB/schema change.
- **Specs**: `fitness-profile` (MODIFY the resilience requirement), `dashboard` (ADD censored-markers + band + confidence + disclosure).

Affected capabilities: **fitness-profile**, **dashboard**. Depends on: nothing (self-contained). Complements `marathon-durability-model` (the *performance* durability band) and `effort-schedule-uncertainty` (same shrink-to-prior shape).
