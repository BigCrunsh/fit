# adaptive-predictions Specification

## Purpose
TBD - created by archiving change target-race-model. Update Purpose after archive.
## Requirements
### Requirement: Prediction charts adapt to target distance
The Prediction Trend chart and Race Prediction table SHALL extrapolate to the target race distance (from `race_calendar WHERE is_target = 1`), not hardcoded 42.195km. Riegel formula uses target_km. VDOT scales from marathon equivalent.

#### Scenario: Marathon target
- **WHEN** target is Marathon (42.195km)
- **THEN** prediction trend shows marathon times, table shows "Marathon Target: 4:00:00"

#### Scenario: Half marathon target
- **WHEN** target is Half Marathon (21.1km)
- **THEN** prediction trend shows HM times, table shows "Halbmarathon Target: 1:47:00", Riegel extrapolates all races to 21.1km

#### Scenario: Target time annotation
- **WHEN** target is Marathon with target_time 4:00:00
- **THEN** prediction trend chart shows horizontal line at 4:00:00 (240 min) labeled "Target 4:00:00"

### Requirement: Pacing strategy adapts to target distance
The race-day pacing strategy SHALL generate splits appropriate for the target distance, not hardcoded marathon (9 × 5km). HM: 4 × 5km + 1.1km. 10K: 2 × 5km.

#### Scenario: HM pacing strategy
- **WHEN** target is HM sub-1:47
- **THEN** pacing shows 5 segments, HR ceilings for HM effort, fueling for HM duration

### Requirement: Prediction summary in race card adapts
The compact prediction in the Race Anchor Card SHALL show the range for the target distance, not always marathon.

#### Scenario: HM prediction range
- **WHEN** target is HM and Riegel predictions range from 1:42-1:55
- **THEN** Race Anchor Card shows "Prediction: 1:42–1:55"

### Requirement: Rename predict_marathon_time to predict_race_time
The function SHALL be renamed and accept `target_km` parameter. Default remains 42.195 for backward compatibility. All callers updated.

#### Scenario: Backward compatibility
- **WHEN** called without target_km
- **THEN** predicts marathon time (42.195km) as before

### Requirement: Maximal-effort HR is keyed to predicted duration, not distance
The maximal-effort heart rate the forecast assumes for a distance — which supplies the model's effort covariate `h` when no measured `avg_hr` exists — SHALL be a function of the predicted maximal-effort **duration** at that distance, not of the distance itself, via a two-parameter log-duration law `offset(t) = β·(log t − log T₀)` (bpm relative to LTHR) where `T₀` is the duration at which a maximal effort sits at LTHR and `β` is the fade slope. Both `T₀` and `β` SHALL be estimated as **population priors updated by the athlete's own maximal efforts** (a precision-weighted shrinkage estimate), weighted by recency and by representativeness (proximity to the goal duration), and SHALL shrink to the labelled population prior when the data is too thin to move off it — so the estimate is never staked on a single race. The existing MaxHR-reserve cap SHALL continue to apply so a maximal effort never exceeds MaxHR.

#### Scenario: Same distance, different fitness → different assumed HR
- **WHEN** two athletes (or one athlete at two fitness levels) would run the same distance in materially different times
- **THEN** the assumed maximal-effort HR differs accordingly (the slower/longer effort sits lower relative to LTHR), because the offset is read off predicted duration, not the kilometre count

#### Scenario: Reproduces the validated anchors
- **WHEN** the law is evaluated at the athlete's predicted maximal durations for 5 K / 10 K / HM / M
- **THEN** the offsets reproduce the previously validated distance schedule within tolerance (short-to-mid within ~0.5 bpm; the marathon within ~1.5 bpm), so the headline forecast does not shift materially

#### Scenario: Generalises across goal with no special-casing
- **WHEN** the target race changes (e.g. marathon → half-marathon)
- **THEN** the maximal-effort assumption for each distance is unchanged (it is keyed to that distance's predicted duration); only which distance is the headline changes

#### Scenario: Cold-start athlete degrades, not breaks
- **WHEN** no informative maximal efforts exist to update `T₀`/`β`
- **THEN** the population priors are used and labelled as defaulted, and the law still produces a duration-appropriate offset for every distance (never a distance-table lookup)

#### Scenario: A single sub-maximal or stale race cannot break the estimate
- **WHEN** the effort whose average HR is nearest LTHR is sub-maximal (e.g. an easy short race run at threshold) or stale
- **THEN** `T₀` is NOT pinned to that effort's duration — recency/representativeness weighting plus the population prior keep the estimate near the athlete's genuine threshold-duration, so the forecast does not collapse

#### Scenario: Tracks fitness via recency
- **WHEN** the athlete's recent races shift their threshold-duration or fade relative to older races
- **THEN** the estimate moves toward the recent evidence (recency-weighted), so the assumption adapts as fitness changes rather than averaging over stale history

### Requirement: Marathon prediction is a Bayesian durability model with an interval
The race-time prediction SHALL be produced by a Bayesian log-time model that regresses on distance (durability), fitness (CTL) and effort (HR), and SHALL return a **median, a 90% credible interval, and P(reaching the target time)** — never a bare point estimate. Maximality SHALL be inferred from the HR covariate, not assumed from the `run_type` label. LTHR SHALL come from `get_calibration_anchor('lthr')`, not a hardcoded constant.

#### Scenario: Forecast carries uncertainty and goal probability
- **WHEN** the model is fit and the target is a sub-4:00 marathon
- **THEN** `predict(...)` returns e.g. `{median: 3:59, lo: 3:49, hi: 4:09, p_sub_goal: 0.57}` and the dashboard renders all three (time, interval, probability)

#### Scenario: Headline moves with fitness, not with one stale race
- **WHEN** a maximal race was run at low CTL (e.g. after a layoff) and current CTL is higher
- **THEN** the headline reflects *current* CTL (faster), the stale race is explained by its low CTL rather than dragging the headline down, and leave-one-out influence of that race on the headline is small

#### Scenario: Durability, fitness and effort are separable outputs
- **WHEN** the posterior is summarised
- **THEN** it exposes `beta_d` (durability exponent, with interval), `phi` (race-time value of fitness/CTL), and `kappa` (HR→pace exchange) as distinct, individually reportable quantities

### Requirement: Prediction degrades gracefully without the model
When PyMC/ArviZ or a cached posterior is unavailable, the prediction SHALL fall back to the existing simple estimate and label itself as such, never blocking the dashboard.

#### Scenario: No posterior yet
- **WHEN** no `marathon_posterior.nc` exists and pymc is not installed
- **THEN** the dashboard shows the fallback prediction with a "model not yet fit" note and no error

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

### Requirement: Maximal efforts are identified and drive the effort-fade fit
Each running effort SHALL carry a maximality determination (`is_maximal` with a recorded `max_effort_source`), derived by precedence: explicit **Garmin RPE** (RPE ≥ 9 → maximal; a recorded RPE below it → explicitly not maximal); then a **manual override** that always wins (`source='manual'`, sticky across re-sync). Garmin `feel` SHALL NOT be used — it is a strong↔weak subjective scale orthogonal to exertion (an all-out RPE-10 race can read feel 1–2). Efforts with no RPE are left undetermined (`NULL`) for a manual override (or a future heuristic) to fill. The fade slope `β` of the maximal-effort schedule SHALL be estimated from **maximal-flagged RACES only** — sustained continuous efforts where average HR is the effort — never from tempo/interval sessions whose average HR is dragged below the sustained-effort HR by recoveries/warm-up. The fit SHALL remain regularised toward the population prior, so β stays at the prior when maximal races are too few or too narrow in duration range, and personalises only as consistent maximal evidence accrues; the fitted β's uncertainty SHALL be available to the forecast interval.

#### Scenario: A sub-maximal effort does not bias the fade fit
- **WHEN** the athlete has both all-out short races and easy short races run at threshold
- **THEN** only the all-out (maximal-flagged) races inform β, so the slope is not flattened by the easy efforts (no spuriously shallow fade)

#### Scenario: Garmin RPE determines maximality; a manual override supersedes it
- **WHEN** an effort has a Garmin RPE ≥ 9
- **THEN** it is flagged maximal (`source='rpe'`); a manual override (`fit effort maximal`) always wins and is preserved across re-derivation; `feel` is never consulted

#### Scenario: Only sustained races feed the slope, not workouts
- **WHEN** a tempo or interval session is flagged maximal (RPE ≥ 9) but its average HR is below the sustained-effort HR
- **THEN** it is excluded from the β fit (races only), so the duration–intensity slope is not distorted by a workout's recovery-diluted average HR

#### Scenario: Sparse maximal data keeps β at the population prior
- **WHEN** too few maximal races exist (or they span too narrow a duration range) to estimate the slope reliably
- **THEN** β stays at the population prior (not labelled fitted) — the forecast is never made less robust than the population-prior default, only more personalised when the evidence supports it

#### Scenario: Fitted β feeds the forecast interval
- **WHEN** β is fitted from maximal races
- **THEN** its posterior uncertainty replaces the population-prior standard deviation in the interval propagation, so the interval reflects how well the athlete's own fade is pinned down

