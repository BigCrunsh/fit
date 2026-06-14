## 1. Weighted, censored estimator (fitness.py)

- [x] 1.1 Add judgment-informed named constants (flagged as priors, not measured): `RESILIENCE_HALF_LIFE_DAYS` (≈21), a length-weight reference (the goal long-run km, or a default), the shrinkage `RESILIENCE_SHRINK_K` (≈2), and a cold-start `RESILIENCE_PRIOR` rule (a fraction of recent typical long-run, fallback population default).
- [x] 1.2 Widen the `_compute_resilience` query lookback (e.g. 120 d) and stop relying on the hard 28-day cutoff; keep the ≥8 km + splits gate and the `compute_cardiac_drift` per-run call (the ONE onset source — do NOT recompute drift inline).
- [x] 1.3 For each qualifying run, carry `(value, censored: bool, age_days, distance_km)` — `censored=True` for the no-drift full-distance lower bound, `False` for a detected onset.
- [x] 1.4 Compute weights `w = recency_decay(age) × length_factor(distance)` and `N_eff = (Σw)²/Σw²` (Kish).
- [x] 1.5 Point estimate = weighted best-demonstrated onset (one-sided, censoring-aware — not a weighted mean) shrunk to the prior: `λ = N_eff/(N_eff+K)`, `est = λ·weighted_best + (1−λ)·prior`.

## 2. Asymmetric band + confidence (fitness.py)

- [x] 2.1 Lower floor = weighted high-confidence demonstrated distance (close to the estimate); upper bound widens with the censoring/coverage gap (longest run vs goal long-run), staleness (recency of the best evidence), and thin `N_eff`. Band is asymmetric (never symmetric ±).
- [x] 2.2 `confidence` = low/med/high from `N_eff`, longest-run-vs-goal coverage, and recency of the best evidence (mirror the `prediction_confidence` level/reason shape).
- [x] 2.3 Extend the resilience dict: keep `current_value` (now the weighted/shrunk estimate) + `trend`/`rate`; add `band` (`{lo, hi}`), `confidence` (`{level, reason}`), and per-point `censored` flags for the chart. Keep the no-splits graceful path.

## 3. Chart — censored markers + band (charts.py)

- [x] 3.1 `chart-drift-trend`: draw no-drift runs as lower-bound markers (open ▲ / "≥") and detected runs as solid onset points — distinct, legible in the legend.
- [x] 3.2 Render the estimate's asymmetric band (shaded region / error bar) and a confidence chip; the "best onset" marker reads the dimension's weighted estimate (single source).
- [x] 3.3 No regression to `chart-drift` (the per-km curves just fixed) — it keeps the cumulative-km axis + steady-run gate.

## 4. Dashboard surfacing + disclosure (cards.py)

- [x] 4.1 Resilience tile / Fitness Dimensions + Distance Ceiling read the new estimate; show the band + confidence compactly (not a wall of numbers).
- [x] 4.2 Update the Long-Run Resilience def-box to disclose: one-sided (right-censored) lower bound, recency- and length-weighted, shrinks to a prior when thin.
- [x] 4.3 Keep MCP/coaching context (`get_run_context` et al.) in sync if it reads the resilience value (SSOT contract).

## 5. Tests (2:1 unhappy:happy)

- [x] 5.1 Happy: a recent long no-drift run → estimate near its distance, tight floor, wider upside, confidence reflects N_eff.
- [x] 5.2 Unhappy — recency: a stale best run + only short recent runs → estimate pulled below the stale value and/or band widens.
- [x] 5.3 Unhappy — censoring: a no-drift run contributes a lower bound, never averaged with a detected onset as equivalent.
- [x] 5.4 Unhappy — thin/cold-start: one run (or zero) → shrinks to prior / low confidence / wide band (and the no-splits graceful path unchanged).
- [x] 5.5 Unhappy — length: a long run outweighs a short run for the same recency; a short run cannot set a late-km estimate it never reached.
- [x] 5.6 Unhappy — asymmetry: `hi − est ≥ est − lo` (the band leans up; never symmetric).
- [x] 5.7 Chart guard: no-drift vs detected markers are distinct; the "best onset" marker == the dimension estimate; `chart-drift` per-km axis still real-km (no regression).

## 6. Validation

- [x] 6.1 Full suite green; `ruff` clean.
- [x] 6.2 `fit report` builds; spot-check the resilience estimate, band, confidence, and censored markers on real data; def-box disclosure present.
- [x] 6.3 GLOSSARY / DATA_LINEAGE note for the resilience estimator (one-sided, weighted, shrink-to-prior) if those docs describe the dimension.
