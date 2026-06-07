# Tasks — effort-schedule-uncertainty

## 1. Schedule uncertainty (`fit/marathon/predict.py`)
- [ ] `EFFORT_BETA_PRIOR_SD` (~1.25) constant, justified per design (within-curve slope spread + Riegel analogues); documented as a judgment-informed prior, not measured
- [ ] `effort_schedule(ds)` also returns `beta_sd` (= `EFFORT_BETA_PRIOR_SD`) and `t0_sd` (log-space SE of the weighted implied-T₀ estimate, shrunk by the same λ; wide at cold-start)

## 2. Propagation (interval only; median unchanged)
- [ ] `effort_h_for_distance` per-draw mode: sample `β_i ~ N(β, σ_β)`, `log T₀_i ~ N(log T₀, σ_logT₀)` across the forecast's N draws → array of `h_i`; reuse the wall-penalty RNG/seed path
- [ ] `predict`/`forecast` interval uses the sampled `h`; the **median** uses point (β, T₀) so the headline doesn't move
- [ ] Apply to `derived_metrics`, `durability_panel`, `trend_series` interval bands too (consistency across surfaces)

## 3. Tests (`tests/test_marathon_model.py`)
- [ ] Median forecast unchanged vs the point-(β,T₀) path (≤ rounding)
- [ ] Marathon 90% interval is WIDER with propagation on than off; HM interval ≈ unchanged (widening scales with |log t_goal − log T₀|)
- [ ] Cold-start athlete (defaulted schedule) → widest effort-driven band; a many-hard-race athlete → tighter
- [ ] β-only vs β+T₀: T₀ contributes materially at the marathon (guard against dropping it)
- [ ] Seed-determinism; 2:1 unhappy (σ=0 → no widening; missing schedule → falls back to prior SD)

## 4. Validation (real data)
- [ ] Before/after: median 3:59:30 unchanged; marathon 90% interval widens ~±2–3 min; HM ≈ flat
- [ ] Confirm not double-counted with the wall penalty (combined interval still sane/calibrated)
- [ ] Regenerate dashboard; the wider band shows on the Overview hero + Profile Panel A/B; CLI matches

## 5. Docs
- [ ] marathon `design.md`: add the effort-schedule uncertainty term to the interval definition
- [ ] `DATA_LINEAGE.md`: note the interval = mean-curve posterior + wall penalty + effort-schedule (β,T₀) uncertainty
- [ ] `CLAUDE.md`: the forecast interval now reflects effort-assumption uncertainty (grows with extrapolation from T₀)
