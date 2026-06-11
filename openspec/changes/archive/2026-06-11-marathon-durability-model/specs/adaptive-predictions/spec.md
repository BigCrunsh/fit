## ADDED Requirements

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
