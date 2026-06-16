## ADDED Requirements

### Requirement: Forecast interval reflects maximal-effort-schedule uncertainty
The marathon forecast's credible interval SHALL incorporate the uncertainty in the maximal-effort schedule that supplies the effort covariate — both the fade slope `β` (a population prior with a standard deviation) and the threshold-duration `T₀` (the standard error of its data-driven shrinkage estimate) — propagated through the predicted time, IN ADDITION to the existing mean-curve posterior and extrapolation-wall penalty. This is estimation uncertainty of the mean curve, not race-day residual spread, so the interval's definition is unchanged in kind. The **median** forecast SHALL be unaffected (it uses the point β/T₀). The added width SHALL scale with the extrapolation distance from `T₀` (`|log t_goal − log T₀|`), so it is larger for goals far from the athlete's threshold-duration and negligible for goals near it.

#### Scenario: The marathon interval widens; the median does not move
- **WHEN** the forecast is produced with effort-schedule uncertainty propagation enabled
- **THEN** the 90% credible interval for a marathon (a goal far from `T₀`) is wider than without it, while the median is unchanged

#### Scenario: A goal near the threshold-duration widens materially less than the marathon
- **WHEN** the goal's predicted duration is close to `T₀` (e.g. a half-marathon)
- **THEN** the effort-schedule contribution to the interval is materially smaller than the marathon's: the β-slope term `(log t − log T₀)·σ_β` vanishes at the zero-crossing, so only the roughly-constant `T₀`-anchor term `|β|·σ_logT₀` remains (the half adds ~±0.9 min 1 SD vs the marathon's ~±2.3 min). It is not zero — `T₀`-anchor uncertainty shifts the whole fade law and therefore has leverage at every duration.

#### Scenario: A cold-start athlete has the widest effort-driven band
- **WHEN** the schedule is defaulted (no informative races to anchor `T₀`, β at the population prior)
- **THEN** the effort-schedule uncertainty is at its widest (prior σ_β, wide σ_T₀), so the interval honestly reflects how little the forecast knows about the athlete's fade

#### Scenario: Both β and T₀ uncertainty are propagated
- **WHEN** computing the marathon interval
- **THEN** both the slope (β) and the anchor (`T₀`) uncertainty contribute; omitting `T₀` would understate the interval for a sparse-race athlete whose threshold-duration is itself uncertain

### Requirement: Effort-schedule inspection panel
The dashboard SHALL provide a diagnostic panel that visualises the maximal-effort schedule — the fade law `offset(t) = β·(log t − log T₀)` — so the otherwise-hidden effort assumption is auditable. The panel SHALL plot effort duration (minutes, log axis) against heart-rate relative to LTHR (bpm, linear, zero-line = threshold), showing the median fade line, a 90% band from the propagated `(σ_β, σ_T₀)`, the athlete's race efforts as points (at/above-threshold efforts distinguished from sub-threshold ones), the `T₀` anchor, and the standard race distances at their model-predicted durations. The fade line SHALL be labelled as a population prior (not a per-athlete fit), and the band SHALL be presented as estimation uncertainty of the assumed effort in heart-rate — explicitly NOT race-day HR variability and NOT comparable to the minutes interval on the trend chart. The panel SHALL render only when the durability model is the forecast source, the schedule is not defaulted, and at least two at/above-threshold race efforts anchor `T₀`.

#### Scenario: The panel shows the fade law with its uncertainty band
- **WHEN** the durability model is the forecast source and the schedule is anchored by ≥2 at/above-threshold races
- **THEN** the panel renders the median fade line, the 90% `(σ_β, σ_T₀)` band fanning out from `T₀`, the race-effort points, and the standard-distance markers at their predicted durations, with the marathon marker sitting in the widest part of the band

#### Scenario: The panel is hidden when there is nothing to inspect
- **WHEN** the schedule is defaulted, the model is not the forecast source, or fewer than two at/above-threshold races exist
- **THEN** the panel is not rendered (a lone prior line through no data is value-free and misleading)
