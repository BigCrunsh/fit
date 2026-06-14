## ADDED Requirements

### Requirement: Long-Run Resilience shows censoring and uncertainty
The Long-Run Resilience drift-onset trend SHALL visually distinguish **observed** onsets (drift detected) from **censored lower bounds** (no-drift runs — "held to ≥ here") with distinct markers (e.g. a solid dot vs an open ▲), SHALL render the resilience estimate's **asymmetric uncertainty band**, and SHALL surface a **confidence level** (low / med / high) using the same chip pattern as the prediction confidence. The "best onset" marker SHALL read the same recency-/length-weighted, shrink-to-prior estimate the resilience dimension exposes (single source — the chart and the dimension never disagree).

#### Scenario: Observed and censored runs are visually distinct
- **WHEN** the drift-onset trend renders a no-drift run alongside a drift-detected run
- **THEN** the no-drift run is drawn as a lower-bound marker (e.g. open ▲, "≥") and the detected run as a solid onset point — the athlete can see which points are measured and which are floors

#### Scenario: The estimate's band and confidence are shown
- **WHEN** the resilience estimate has an asymmetric band and a confidence level
- **THEN** the chart renders the band (tight floor, wider upside) and a low/med/high confidence chip, so the reader sees how much the durability number is trusted, not just its value

#### Scenario: The one-sided, weighted nature is disclosed
- **WHEN** the athlete opens the Long-Run Resilience definition popover
- **THEN** it discloses that drift onset is a one-sided (right-censored) lower bound, recency- and length-weighted, and shrinks toward a prior when data is thin — so the figure reads as demonstrated durability with honest uncertainty, not a measured point
