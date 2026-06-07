# Tasks — maximal-effort-flag

## 1. Schema + ingest
- [ ] Migration: add `is_maximal` (bool) + `max_effort_source` (rpe/feel/race/heuristic/manual) to `activities`
- [ ] Derivation (sync + a `fit backfill maximal` one-shot): set `is_maximal` by precedence — RPE≈9–10 / max Feel / raced chip time → heuristic (avg HR near distance-expected ceiling AND even/negative pacing via split CV) → leave False; record `max_effort_source`. Idempotent; never clobbers a manual override.
- [ ] `fit effort maximal <activity_id> [--no]` CLI for manual override (source=manual, sticky)

## 2. Fit β from maximal efforts (`fit/marathon/predict.py`)
- [ ] `effort_schedule`: fit β = recency-/representativeness-weighted slope of (avg_hr − LTHR) vs log(duration) over `is_maximal` efforts, **prior-regularized** toward `EFFORT_BETA_PRIOR` (pseudo-count shrinkage, like T₀); return β + its standard error
- [ ] T₀ uses `is_maximal` efforts (replacing the "avg HR ≥ LTHR" proxy)
- [ ] Cold-start / too few maximal efforts → β stays the population prior, `defaulted=True` (today's behaviour — never less robust)
- [ ] β's SE feeds `effort-schedule-uncertainty` propagation (replaces the prior σ_β when fitted)

## 3. Tests
- [ ] Determination precedence: RPE 9 → maximal; max Feel → maximal; raced chip time → maximal; easy parkrun (RPE 4) → not; heuristic only when RPE/Feel absent; manual override beats all
- [ ] β fit excludes sub-maximal efforts: the easy 5 Ks don't flatten β (no −2.5 result); β lands between the prior and the maximal-only data slope
- [ ] Prior-regularization: 1–2 maximal efforts → β ≈ prior; many consistent → β moves toward the data
- [ ] 2:1 unhappy: no maximal efforts → prior + defaulted; all-sub-maximal → prior; one maximal only → prior-dominated; manual unset restores derived value
- [ ] Backfill is idempotent and preserves manual overrides

## 4. Validation (real data)
- [ ] Show which of the athlete's efforts flag maximal (expect the 3 K all-out, not the threshold 5 Ks)
- [ ] Fitted β is sane (between −6.5 and the maximal-data slope; NOT the contaminated −2.3); headline stays stable
- [ ] Confirm β's SE flows into the forecast interval (with `effort-schedule-uncertainty`)
- [ ] Regenerate dashboard; cross-surface consistency holds

## 5. Docs
- [ ] `CLAUDE.md`: β is now fitted from maximal-flagged efforts (prior-regularized); maximality source precedence
- [ ] `DATA_LINEAGE.md`: add the `is_maximal` flag + its sources to the effort-schedule lineage
- [ ] marathon `design.md`: Decision-4 (fit β) is now implemented, gated on the maximality flag
