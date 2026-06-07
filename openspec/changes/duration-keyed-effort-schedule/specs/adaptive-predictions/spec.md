## ADDED Requirements

### Requirement: Maximal-effort HR is keyed to predicted duration, not distance
The maximal-effort heart rate the forecast assumes for a distance — which supplies the model's effort covariate `h` when no measured `avg_hr` exists — SHALL be a function of the predicted maximal-effort **duration** at that distance, not of the distance itself, via a two-parameter log-duration law `offset(t) = β·(log t − log T₀)` (bpm relative to LTHR) where `T₀` is the duration at which a maximal effort sits at LTHR and `β` is the fade slope. `T₀` SHALL be personalised from the athlete's genuine maximal effort nearest LTHR, with a labelled population fallback when none exists; `β` MAY be a population constant. The existing MaxHR-reserve cap SHALL continue to apply so a maximal effort never exceeds MaxHR.

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
- **WHEN** no genuine maximal effort near LTHR exists to personalise `T₀`
- **THEN** the population fallback `T₀` is used and labelled as defaulted, and the law still produces a duration-appropriate offset for every distance (never a distance-table lookup)
