## ADDED Requirements

### Requirement: Forecast interval reflects maximal-effort-schedule uncertainty
The marathon forecast's credible interval SHALL incorporate the uncertainty in the maximal-effort schedule that supplies the effort covariate — both the fade slope `β` (a population prior with a standard deviation) and the threshold-duration `T₀` (the standard error of its data-driven shrinkage estimate) — propagated through the predicted time, IN ADDITION to the existing mean-curve posterior and extrapolation-wall penalty. This is estimation uncertainty of the mean curve, not race-day residual spread, so the interval's definition is unchanged in kind. The **median** forecast SHALL be unaffected (it uses the point β/T₀). The added width SHALL scale with the extrapolation distance from `T₀` (`|log t_goal − log T₀|`), so it is larger for goals far from the athlete's threshold-duration and negligible for goals near it.

#### Scenario: The marathon interval widens; the median does not move
- **WHEN** the forecast is produced with effort-schedule uncertainty propagation enabled
- **THEN** the 90% credible interval for a marathon (a goal far from `T₀`) is wider than without it, while the median is unchanged

#### Scenario: A goal near the threshold-duration barely widens
- **WHEN** the goal's predicted duration is close to `T₀` (e.g. a half-marathon)
- **THEN** the effort-schedule contribution to the interval is negligible, because the offset is read near the fade law's zero-crossing where β and `T₀` uncertainty have little leverage

#### Scenario: A cold-start athlete has the widest effort-driven band
- **WHEN** the schedule is defaulted (no informative races to anchor `T₀`, β at the population prior)
- **THEN** the effort-schedule uncertainty is at its widest (prior σ_β, wide σ_T₀), so the interval honestly reflects how little the forecast knows about the athlete's fade

#### Scenario: Both β and T₀ uncertainty are propagated
- **WHEN** computing the marathon interval
- **THEN** both the slope (β) and the anchor (`T₀`) uncertainty contribute; omitting `T₀` would understate the interval for a sparse-race athlete whose threshold-duration is itself uncertain
