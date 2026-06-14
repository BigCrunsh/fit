## MODIFIED Requirements

### Requirement: Resilience from split analysis
The resilience dimension SHALL track durability as the **drift onset km** from cardiac-drift analysis (`compute_cardiac_drift` — the single, grade-adjusted source), aggregated across qualifying long runs (≥8 km, with splits) into a **recency- and length-weighted, censored estimate with an asymmetric uncertainty band and a confidence level** — not a single unweighted value. Requires .fit file data; graceful degradation when unavailable.

Each qualifying run SHALL contribute either an **observed** onset (drift detected) or a **right-censored lower bound** at the run's full distance (no drift — "durable to at least here"); the censoring SHALL be preserved, not collapsed to a point. Runs SHALL be weighted by **recency** (a smooth half-life decay rather than a hard window cutoff — durability is trainable and detrainable, so stale runs inform current state less) and by **run length** (longer runs constrain late-km durability more; short runs are silent about distances they never reached). The point estimate SHALL be the weighted **best-demonstrated** onset (an upper, one-sided quantity — not a downward-biased weighted mean) **shrunk toward a conservative prior when the effective sample is thin or stale**, so a cold-start or single-run history reports the prior, not a confident number. The estimate SHALL carry an **asymmetric band** — a well-supported lower floor and a wider upper bound that widens with staleness, thin data, and the gap between the longest observed run and the goal long-run — never a symmetric interval implying downside the one-sided signal cannot support.

#### Scenario: Recent qualifying long run, with band
- **WHEN** a recent long run holds to its full distance with no drift (a censored lower bound) over a window with several qualifying runs
- **THEN** the resilience estimate sits near that demonstrated distance with a tight lower floor and a wider upper bound, and the confidence reflects the effective sample size, the longest-run-vs-goal coverage, and the recency of the best evidence

#### Scenario: A stale best run is discounted (recency)
- **WHEN** the strongest evidence is an old long run and only shorter runs are recent
- **THEN** the estimate is pulled below that stale value and/or the band widens — because durability is trainable/detrainable and old evidence is less representative of the current state

#### Scenario: Censoring is preserved, not collapsed
- **WHEN** a run finishes with no detected drift
- **THEN** it contributes a lower bound ("durable to at least the run distance"), not an onset point, and is never averaged with detected onsets as if equivalent

#### Scenario: Thin data shrinks to the prior
- **WHEN** only one qualifying long run exists (or the history is cold-start)
- **THEN** the estimate shrinks toward the conservative prior, confidence is low, and the band is wide — the dimension does not report a single run as a confident durability figure

#### Scenario: Resilience without splits
- **WHEN** no .fit split data available
- **THEN** resilience shows "Enable fit sync --splits for resilience tracking"
