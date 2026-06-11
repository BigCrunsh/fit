## ADDED Requirements

### Requirement: Marathon Prediction section shows interval, probability, and influence
The Marathon Prediction section SHALL render the median forecast, its 90% credible interval, and P(sub-goal); a fitness-tracking trend (marathon-equivalent at maximal effort vs CTL over time) with per-effort points coloured by distance; and SHALL flag any single effort whose removal moves the headline by more than ~5 minutes (leave-one-out influence), so no race silently owns the number. The def-box SHALL state the model assumptions (durability exponent, the maximal-marathon HR is an input, the interval is estimation uncertainty not race-day spread).

#### Scenario: Headline never stands alone
- **WHEN** the Marathon Prediction section renders with a fit model
- **THEN** the median is shown together with the 90% interval and P(sub-goal); the point estimate is never shown by itself

#### Scenario: Influential race is flagged
- **WHEN** removing one effort would move the headline > 5 min
- **THEN** that effort is flagged in the section so the athlete sees the number isn't owned by a single race

### Requirement: Durability and fitness-value are first-class dashboard readouts
The dashboard SHALL surface the durability exponent `beta_d` (with interval) and the race-time value of fitness `phi` (e.g. "+10 CTL ≈ −6 min at the marathon") as tracked readouts — signals the platform otherwise lacks — positioned to complement (not duplicate) the resilience drift-onset and speed/bpm efficiency metrics.

#### Scenario: Durability readout present
- **WHEN** the model is fit
- **THEN** the dashboard shows `beta_d` with its credible interval and a plain-language reading ("every doubling of distance ×2.09 time")
