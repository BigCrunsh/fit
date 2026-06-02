## ADDED Requirements

### Requirement: A single standardizing anchor layer for all fitness metrics
The system SHALL expose one function, `get_calibration_anchor(conn, metric)`, that is the canonical way any consumer obtains the active value of a fitness anchor (`vdot`, `lthr`, `max_hr`, `aet`). It SHALL apply the metric's declared aggregation policy over that metric's observation rows and return a payload `{value, confidence, method, inputs, suggestion}` where `inputs` are the rows that contributed and `suggestion` is the heuristic-proposed value with its reasoning. No consumer SHALL re-derive an anchor by its own ad-hoc rule.

#### Scenario: All consumers read through the shared layer
- **WHEN** the dashboard VDOT Trend, Pace Zones, the marathon forecast, Fitness Dimensions, CLI `fit status`, and the MCP coaching context each need "current VDOT"
- **THEN** each calls `get_calibration_anchor(conn, 'vdot')` and receives the same `value` — there is exactly one current VDOT across the app

#### Scenario: Payload carries the suggestion and inputs for display/audit
- **WHEN** `get_calibration_anchor(conn, 'aet')` is called with four drift-test rows in window
- **THEN** the payload's `value` is the policy output, `inputs` lists the contributing rows, and `suggestion` describes the heuristic (e.g. "median of 4 drift tests in 90d = 152")

### Requirement: Per-metric aggregation policy matched to the metric's statistics
Each metric SHALL declare an aggregation policy. Performance and ceiling metrics (one-sided / bounded) SHALL use a **max** estimator; noisy central-threshold metrics (two-sided) SHALL use a **robust center** (median or trimmed mean). Each policy SHALL declare a window/memory model and a `min_samples` below which it falls back to the single best-confidence row at `confidence='low'`.

| Metric | Estimator | Window/memory | Notes |
|---|---|---|---|
| `vdot` | max, recency-decayed | exponential decay, no hard cliff | one-sided: a race is bounded above by fitness |
| `max_hr` | max, plausibility-gated | long (years) + age decay | true ceiling; reject high-side artifacts |
| `lthr` | median / trimmed mean | recent, recency-weighted | two-sided threshold |
| `aet` | median / trimmed mean | recent, recency-weighted | noisiest two-sided threshold |

#### Scenario: VDOT takes the best, recency-decayed — not the latest
- **WHEN** the qualifying VDOT estimates are a road effort 40.9 from ~8 months ago and a trail half 35.8 from this month
- **THEN** with recency decay applied, the 40.9 (lightly discounted) outranks the fresh 35.8 and the active VDOT is ~40, NOT 35.8

#### Scenario: LTHR takes a robust center — a hot-day high reading does not win
- **WHEN** recent qualifying LTHR estimates are 170, 172, 173 and one hot-day outlier 181
- **THEN** the active LTHR is the median (~172), NOT the max (181)

#### Scenario: MaxHR is a plausibility-gated all-time max with age decay
- **WHEN** validated MaxHR observations are 192, 194, 195 over two years and one strap-glitch reading of 217
- **THEN** the 217 is rejected as implausible and the active MaxHR is ~195 (minus age decay), drawn from long memory rather than a recent window

#### Scenario: Below min_samples, fall back to the best single row
- **WHEN** only one AeT drift-test estimate exists (below the policy's `min_samples`)
- **THEN** the anchor returns that single row's value with `confidence='low'` rather than a degenerate one-element median

## MODIFIED Requirements

### Requirement: VDOT from race results
The system SHALL compute VDOT from each completed race using Daniels tables, and SHALL persist each as an **informational** `vdot` calibration row (`method='race_estimate'`) that never auto-activates — mirroring the LTHR `race_estimate` pattern. These rows feed the VDOT aggregation policy and the VDOT calibration-history chart. The Garmin VO2max estimate SHALL also be persisted as an informational `vdot` row, labelled as a wrist-HR estimate. The active VDOT SHALL be the output of the VDOT aggregation policy via `get_calibration_anchor(conn, 'vdot')`, confirmable by the human; it SHALL NOT be the raw Garmin estimate and SHALL NOT be the single most-recent effort.

#### Scenario: Race result writes an informational VDOT row
- **WHEN** a completed 10K race result of 45:00 is synced
- **THEN** a `{metric:'vdot', method:'race_estimate', confidence:'low', active:0}` row is written; `get_active_calibration('vdot')` excludes it from selection but it appears in the VDOT history chart

#### Scenario: Active VDOT is the policy output, not Garmin
- **WHEN** Garmin VO2max is 49 and the recency-decayed best race VDOT is ~40
- **THEN** `get_calibration_anchor(conn,'vdot').value` is ~40; the dashboard shows it as the trusted VDOT with Garmin 49 shown only as a reference estimate

### Requirement: Effective VDOT blends sources
`effective_vdot` SHALL be defined as the output of the VDOT aggregation policy: the best recent race VDOT with **recency decay** (no hard window cliff), falling back to a discounted Garmin estimate only when no race evidence exists. It SHALL NOT drop a strong older race abruptly at a fixed day boundary.

#### Scenario: An older road best is not abruptly dropped by a window edge
- **WHEN** the strongest road race is 185 days old (just past the old 180-day window) and the only newer race is a slow trail effort
- **THEN** the older road best, recency-decayed, still contributes and the effective VDOT does not collapse to the trail value
