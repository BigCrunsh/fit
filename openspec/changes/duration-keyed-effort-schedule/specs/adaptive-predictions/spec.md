## ADDED Requirements

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
