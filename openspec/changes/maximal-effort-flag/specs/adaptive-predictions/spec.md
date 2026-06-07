## ADDED Requirements

### Requirement: Maximal efforts are identified and drive the effort-fade fit
Each running effort SHALL carry a maximality determination (`is_maximal` with a recorded source), derived by precedence: explicit Garmin RPE/Feel (an all-out RPE or max-effort Feel) or a raced chip time; then a heuristic fallback (average HR near the distance-expected ceiling AND even-or-negative pacing) when RPE/Feel are absent; then a manual override that always wins. The fade slope `β` (and the threshold-duration `T₀`) of the maximal-effort schedule SHALL be estimated from **maximal-flagged efforts only**, so sub-maximal efforts (e.g. an easy parkrun run at threshold) cannot flatten or bias the fit. The fit SHALL remain regularised toward the population prior, so β stays at the prior when maximal efforts are too few, and personalises only as consistent maximal evidence accrues; the fitted β's uncertainty SHALL be available to the forecast interval.

#### Scenario: A sub-maximal effort does not bias the fade fit
- **WHEN** the athlete has both all-out short races and easy short races run at threshold
- **THEN** only the all-out efforts inform β, so the slope is not flattened by the easy efforts (no spuriously shallow fade)

#### Scenario: Explicit RPE/Feel determines maximality over the heuristic
- **WHEN** an effort has a Garmin RPE near maximal (or a max-effort Feel)
- **THEN** it is flagged maximal regardless of the HR/pacing heuristic; the heuristic is used only for efforts lacking RPE/Feel; a manual override supersedes both

#### Scenario: Sparse maximal data keeps β at the population prior
- **WHEN** too few maximal efforts exist to estimate the slope reliably
- **THEN** β stays at the population prior (labelled defaulted) — the forecast is never made less robust than the population-prior default, only more personalised when the evidence supports it

#### Scenario: Fitted β feeds the forecast interval
- **WHEN** β is fitted from maximal efforts
- **THEN** its posterior uncertainty replaces the population-prior standard deviation in the interval propagation, so the interval reflects how well the athlete's own fade is pinned down
