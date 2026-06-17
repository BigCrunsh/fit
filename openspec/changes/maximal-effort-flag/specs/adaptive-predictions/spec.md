## ADDED Requirements

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
