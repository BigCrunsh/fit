# Design — resilience-uncertainty

## Context

`_compute_resilience(conn)` (fit/fitness.py) gathers, for each running activity ≥8 km with splits in the last 28 days, a drift point via `compute_cardiac_drift`: the onset km when drift is *detected*, or the run's full distance when *none* is detected ("held to at least here"). It returns `current_value = max(points)`, a separate `_compute_trend` direction, and an 8-point history. There is no uncertainty, the window is a hard cutoff, and every in-window run counts equally toward the `max`.

This change keeps the per-run source (`compute_cardiac_drift`) and replaces the **aggregation**: a recency- and length-weighted, censored estimate with an asymmetric band and a confidence level. It mirrors the shrinkage already used for `T₀` in the maximal-effort schedule.

## The censoring (one-sided signal)

Drift onset is **right-censored** and one-sided — three facts the estimator must respect:
- A *no-drift* run is a **lower bound**: true durability ≥ run distance, possibly much more (we can't observe past the run).
- A *detected* run is a point observation of the onset.
- Short / hot / fatigued runs only push onset **earlier**, and a short run physically caps how late onset can appear. So the *best* recent run is the truest demonstrated floor — which is why today's `max` is defensible as a floor, just not as a point with no band.

## The three weights (the athlete's intuition, formalized)

Each run `i` gets weight `w_i = recency_i × length_i`:
- **recency** — `0.5 ^ (age_days / HALF_LIFE_DAYS)`, `HALF_LIFE_DAYS ≈ 21`. A smooth decay replacing the binary 28-day cutoff; durability is trainable/detrainable, so stale runs inform *current* state less. (A long lookback cap, e.g. 120 d, bounds the query; beyond ~3 half-lives weight is negligible anyway.)
- **length** — increasing in distance (e.g. `distance / goal_long_km`, capped at 1): a 20 km run constrains late-km durability far more than a 9 km run, which is silent about km 20+.
- **effective sample size** `N_eff = (Σw)² / Σw²` (Kish) — the count that drives shrinkage and the band; many recent long runs → high `N_eff`, a lone stale run → ~1.

## The estimate

`current_value` = the **weighted best-demonstrated onset, shrunk toward a prior**:
- Take the censored points with weights `w_i`. The weighted estimate favours recent long runs and treats no-drift values as the lower bounds they are (they can only raise the floor). A single stale heroic run no longer sets the number outright — its low recency weight limits its pull.
- **Shrink to prior**: `est = λ·weighted_best + (1−λ)·prior`, `λ = N_eff / (N_eff + K)`, `K ≈ 2`. The prior is a conservative cold-start durability (a fraction of the athlete's recent typical long-run, falling back to a population default) — so a thin/cold history reports the prior, not a confident number, exactly like `T₀`.

## The band (asymmetric) and confidence

- **Lower bound** — a well-supported floor: the weighted high-confidence demonstrated distance (recent no-drift runs strongly support "at least here"). Close to the estimate.
- **Upper bound** — wider: the censored, unobserved upside. Widens with (i) the **censoring/coverage gap** (how far the longest run falls short of the goal long-run — unobserved late km), (ii) **staleness** (best evidence old → less sure of current state), and (iii) **thin `N_eff`**.
- **confidence** — `low / med / high` from `N_eff`, longest-run-vs-goal coverage, and recency of the best evidence; surfaced as a chip like `prediction_confidence`.

The band is one-sided-leaning: tight below (demonstrated), wide above (speculative) — never a symmetric ± that would imply downside the censored signal can't support.

## Decisions

### Decision 1 — recency-weight + smooth decay, not a hard window
Replace the 28-day cutoff with a half-life decay over a longer lookback. **Anti-recommendation: keep the hard 28-day max** — rejected: it is binary at the boundary, discards barely-out-of-window long runs (precious, since long runs are sparse), and gives every in-window run equal pull regardless of age. A decay is smoother and matches how durability actually fades.

### Decision 2 — keep "best demonstrated", weighted; do NOT switch to a weighted mean
The estimate stays a **best-demonstrated** (upper) quantity, now weighted — not the weighted mean of points. **Anti-recommendation: weighted mean of onsets** — rejected: it ignores censoring (averages a no-drift lower bound with detected onsets as if equivalent) and is downward-biased, since short/bad runs only push onset earlier. The one-sided signal calls for an upper estimate, shrunk.

### Decision 3 — shrink to a prior when thin (mirror T₀), don't report a lone run as fact
`λ = N_eff/(N_eff+K)` blends toward a conservative prior. **Anti-recommendation: report the raw best whenever ≥1 run exists** — rejected: a single recent 20 km no-drift run is real but weak evidence of marathon durability; reporting it unshrunk repeats the over-confidence this change exists to fix. Cold-start → prior, same as the schedule's `T₀`.

### Decision 4 — asymmetric band, not symmetric ±
The band leans up (censored upside) with a tight floor. **Anti-recommendation: symmetric ±σ** — rejected: drift onset cannot be meaningfully "X km too high" from this signal (lesser runs only lower it); a symmetric band would invent downside risk the data can't express and read as false precision.

### Decision 5 — `compute_cardiac_drift` stays the only onset source
The estimator consumes the canonical per-run onset/censoring; it does not re-derive drift. **Anti-recommendation: compute a weighted drift inline in the aggregator** — rejected: violates the CLAUDE.md "drift onset has ONE source" contract that the recent `chart-drift` fix just restored. This change is aggregation only.

### Decision 6 — constants are judgment-informed and named, like `effort-schedule-uncertainty`
`HALF_LIFE_DAYS`, the length-weight reference, the shrinkage `K`, and the cold-start prior are hand-set, documented, named constants — flagged as priors, not measured values — with sensible cold-start behaviour (thin/stale → prior + wide band). No new model fit.
