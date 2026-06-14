## MODIFIED Requirements

### Requirement: Durability and fitness-value are first-class dashboard readouts
The dashboard SHALL surface the marathon model's coefficients as an **added-variable (partial-regression) decomposition**, not bare numbers: after the Marathon Prediction Trend, the **model formula** (`log t = α + β_d·log(dist/goal) + φ·fitness + κ·effort`, with each term explained — including α = the baseline time at average fitness + threshold effort, fitness = chronic training load (CTL), effort = avg HR vs LTHR) is shown, then a **graph per coefficient, stacked vertically** — each plotting its covariate against marathon-equivalent time with the **other two netted out**, so the fitted line's **slope is that coefficient**. β_d's panel **is the durability collapse** (distance axis, keeping its extrapolation band); φ (fitness, CTL) and κ (effort, bpm above LTHR) are stacked below it. These complement (do not duplicate) the resilience drift-onset and speed/bpm efficiency metrics.

Each panel SHALL render the slope's **posterior**, not a point: a posterior median line plus an **HDI credible ribbon**. When a coefficient is **prior-dominated** (data too thin to inform it), its panel SHALL be visibly de-emphasised (greyed/dashed) and tagged as such — it SHALL NOT imply confidence the data does not support. Each panel SHALL include a **zero-slope reference** (so "no effect" is distinguishable), an **operating-point marker** (today's fitness / assumed race-HR / goal distance), a **rise/run slope triangle** with a plain-language impact label (e.g. "+10 CTL → −2 min"; for β_d the doubling reading "×2 dist → ×2.09 time" tied to the exponent), and SHALL share a **log-time y-axis** so a slope reads as a straight line and the panels are comparable. Points SHALL be **coloured by distance** (matching the collapse) and carry **run-identifying tooltips** (date · distance · finish time → marathon-equivalent), and the **most-recent run** SHALL be marked (a red ring) as a shared temporal reference across all panels. Partial-residual points SHALL be labelled as netted-out (not raw runs). When the model is not fit, the panels SHALL degrade gracefully (no broken layout), like the collapse chart.

#### Scenario: The formula, then a slope graph per coefficient
- **WHEN** the durability model is fit
- **THEN** the dashboard shows the model formula (α, β_d, φ, κ each explained) followed by a stacked graph per coefficient — β_d (the collapse), φ, κ — each with partial-residual points and a fitted line whose slope is that coefficient, on a shared log-time axis, with a slope triangle and a plain-language marathon-impact reading

#### Scenario: Points are distance-coloured, the recent run is marked, and tooltips identify the run
- **WHEN** a coefficient panel renders its efforts
- **THEN** each point is coloured by its distance (blue → red, like the collapse), the most-recent run carries a red ring (a shared reference across panels), and hovering a point shows the run (date · distance · finish time → marathon-equivalent)

#### Scenario: The slope's uncertainty is shown, not a point line
- **WHEN** a coefficient panel renders
- **THEN** it draws the posterior median line AND an HDI credible ribbon (the uncertainty is visible), and a zero-slope reference so the reader can see whether the effect is distinguishable from "no effect"

#### Scenario: A prior-dominated coefficient is visibly de-emphasised
- **WHEN** a coefficient is prior-dominated (thin data — e.g. φ for a new athlete)
- **THEN** its panel is greyed/dashed and tagged "prior-dominated", so the near-prior slope does not read as a confident, data-driven finding

#### Scenario: The line slope equals the coefficient
- **WHEN** the φ (or κ, or β_d) panel's median line is read in log-time
- **THEN** its slope equals the model's φ (or κ, or β_d) posterior median — the panel IS the coefficient, visualised

#### Scenario: Graceful when the model is not fit
- **WHEN** the durability model is not fit
- **THEN** the param panels are omitted without a broken layout (consistent with the durability-collapse chart's degradation)
