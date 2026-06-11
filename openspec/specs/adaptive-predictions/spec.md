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

