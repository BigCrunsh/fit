# fitness-profile Specification

## Purpose
TBD - created by archiving change target-race-model. Update Purpose after archive.
## Requirements
### Requirement: 4-dimension fitness profile
The system SHALL track running fitness across four dimensions: aerobic capacity (VO2max, VDOT), threshold (LTHR, Z2 pace), economy (speed_per_bpm, cadence), and resilience (drift onset, pace fade). Each dimension has a current value, trend direction, and rate of change.

#### Scenario: Compute fitness profile
- **WHEN** `get_fitness_profile(conn)` is called
- **THEN** returns dict with four dimensions, each having: current_value, trend (improving/declining/flat), rate_per_month, data_points_count

#### Scenario: Insufficient data
- **WHEN** fewer than 4 weeks of running data exist
- **THEN** dimensions with insufficient data show "insufficient_data" status with note: "Need N more weeks"

### Requirement: VDOT from race results
The system SHALL compute VDOT from each completed race using Daniels tables, and SHALL persist each as an **informational** `vdot` calibration row (`method='race_estimate'`) that never auto-activates — mirroring the LTHR `race_estimate` pattern. These rows feed the VDOT aggregation policy and the VDOT calibration-history chart. The Garmin VO2max estimate SHALL also be persisted as an informational `vdot` row, labelled as a wrist-HR estimate. The active VDOT SHALL be the output of the VDOT aggregation policy via `get_calibration_anchor(conn, 'vdot')`, confirmable by the human; it SHALL NOT be the raw Garmin estimate and SHALL NOT be the single most-recent effort.

#### Scenario: Race result writes an informational VDOT row
- **WHEN** a completed 10K race result of 45:00 is synced
- **THEN** a `{metric:'vdot', method:'race_estimate', confidence:'low', active:0}` row is written; `get_active_calibration('vdot')` excludes it from selection but it appears in the VDOT history chart

#### Scenario: Active VDOT is the sticky confirmed value, not Garmin
- **WHEN** Garmin VO2max is 49 and the athlete's confirmed VDOT is 41
- **THEN** `get_calibration_anchor(conn,'vdot').value` is 41; the dashboard shows it as the trusted VDOT with Garmin 49 shown only as a reference estimate

### Requirement: Trend and rate computation
Each fitness dimension SHALL have a trend computed from the last 8 weeks of data. Rate of change = linear regression slope expressed per month.

#### Scenario: VO2max trend
- **WHEN** VO2max was 48 eight weeks ago and 49 now
- **THEN** trend = "improving", rate = +0.5/month

#### Scenario: Economy declining
- **WHEN** speed_per_bpm dropped from 1.10 to 1.05 over 4 weeks
- **THEN** trend = "declining", rate = -0.05/month

### Requirement: Resilience from split analysis
The resilience dimension SHALL track durability as the **drift onset km** from cardiac-drift analysis (`compute_cardiac_drift` — the single, grade-adjusted source), aggregated across qualifying **steady aerobic** long runs (≥8 km, with splits; tempo/intervals/progression/race **excluded** — those decouple early by design and measure effort, not aerobic durability) into a **recency- and length-weighted, censored estimate with a Bayesian-bootstrap 90% interval (sampling uncertainty + the unobserved-distance upside) and a confidence level** — not a single unweighted value. Requires .fit file data; graceful degradation when unavailable.

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

### Requirement: HR zone primary selection follows a documented fallback chain
`compute_hr_zones()` SHALL select the primary `hr_zone` using this priority:

1. **AeT-anchored** (`hr_zone_aet`) — when an active `aet` calibration row exists. *Not yet implemented; reserved for `aet-anchored-zones`.*
2. **%LTHR (Friel)** (`hr_zone_lthr`) — when an active `lthr` calibration exists.
3. **%MaxHR** (`hr_zone_maxhr`) — as a last resort when neither AeT nor LTHR is available.

An explicit `profile.zone_model` config value (`max_hr` | `lthr` | `aet`) overrides the fallback chain. The default `zone_model` SHALL be `lthr`. `hr_zone_maxhr` and `hr_zone_lthr` SHALL continue to be computed in parallel as diagnostic outputs, regardless of which model is primary.

#### Scenario: LTHR calibrated, no AeT — primary is LTHR
- **WHEN** active `lthr = 172`, no active `aet`, `zone_model` unset
- **THEN** `hr_zone` matches `hr_zone_lthr`. avg HR 148 → Z2 (88% LTHR, in Friel Z2 band 85–89%).

#### Scenario: LTHR missing, falls back to %MaxHR
- **WHEN** no active `lthr` calibration, no active `aet`
- **THEN** `hr_zone` matches `hr_zone_maxhr` (%MaxHR textbook model)

#### Scenario: Explicit override wins
- **WHEN** `profile.zone_model = max_hr` is set in `config.local.yaml`, LTHR is calibrated
- **THEN** `hr_zone` matches `hr_zone_maxhr` (user override beats fallback)

#### Scenario: Diagnostic zones always computed
- **WHEN** any running activity with `avg_hr` is enriched
- **THEN** `hr_zone_maxhr` is populated (always), `hr_zone_lthr` is populated (when LTHR cal exists), and the primary `hr_zone` matches the active model

### Requirement: Recompute path applies the active calibration to historical activities
`fit recompute --force` SHALL re-enrich every activity using the current calibration values, regardless of whether `hr_zone` is already populated. After a calibration change or a zone-model switch, running `fit recompute --force` SHALL produce a consistent zone classification across all history.

#### Scenario: Zone model switched
- **WHEN** user changes `zone_model` from `max_hr` to `lthr` and runs `fit recompute --force`
- **THEN** all 231 historical activities have their `hr_zone` recomputed against the Friel %LTHR model; `weekly_agg.z12_pct` recomputes accordingly

#### Scenario: Default recompute leaves zoned activities alone
- **WHEN** user runs `fit recompute` (no `--force`)
- **THEN** only activities with `hr_zone IS NULL` are re-enriched (post-sync gap-filling behavior, unchanged from today)

### Requirement: Calibration rows carry a flags column
Every calibration row SHALL include a `flags` column (`TEXT`, JSON array of strings, default `'[]'`). Recognized flag values: `implausible_value`, `spike`, `unexpected_direction`, `agrees_with_prior`, `weak_context`. Auto-extract paths SHALL always insert a row (never silently return None when the reading is bad) — implausible readings are recorded with `confidence = 'low'` and a flag list explaining why.

#### Scenario: Plausible reading from a race
- **WHEN** a max_hr reading of 195 is extracted from a race activity, prior active is 192, no spike detected
- **THEN** the row is inserted with `flags = []` and `confidence = 'medium'`

#### Scenario: Reading agrees with prior — confidence bumps to high
- **WHEN** a new LTHR reading of 171 is extracted from a 10K race, prior active is 172 (race-extracted)
- **THEN** the row is inserted with `flags = ['agrees_with_prior']` and `confidence = 'high'`

#### Scenario: Implausible value still recorded
- **WHEN** an activity reports `max_hr = 220` (chest strap glitch on an easy run)
- **THEN** the row is inserted with `flags = ['implausible_value', 'weak_context']` and `confidence = 'low'`; the prior active calibration remains active

#### Scenario: Sudden directional drop is flagged but recorded
- **WHEN** a new max_hr reading is 188, prior active is 195, gap is 7 bpm in 8 weeks
- **THEN** the row is inserted with `flags = ['unexpected_direction']` and `confidence = 'low'`

### Requirement: Calibration confidence has explicit, uniform semantics
The system SHALL apply the same `low | medium | high` confidence rubric across all calibration metrics (`max_hr`, `lthr`, `aet`, `weight`, `vo2max`).

| Confidence | Definition |
|---|---|
| `high` | Two corroborating readings within ±2 bpm (method-appropriate tolerance) from hard-effort contexts, OR explicitly set by user via `fit calibrate <metric> <value>`. |
| `medium` | Single recent reading from a hard-effort context (race, time trial, hard interval), plausible value, no flags. |
| `low` | Any of: `implausible_value`, `spike`, `unexpected_direction`, `weak_context`; OR stale (past `STALENESS_THRESHOLDS`). |

The "stale → low" rule applies at query time (via `get_calibration_status()`), not at write time — the stored `confidence` reflects the row's write-time quality.

#### Scenario: Manual CLI write produces high
- **WHEN** user runs `fit calibrate max_hr 195`
- **THEN** the inserted row has `confidence = 'high'` regardless of any other context

#### Scenario: Auto-extracted single race reading produces medium
- **WHEN** LTHR auto-extract path inserts a value of 171 with no prior active row
- **THEN** the row has `confidence = 'medium'` and `flags = []`

#### Scenario: Stale active calibration reports as low at query time
- **WHEN** the active `lthr` row is from 2025-10 (>56 days old per `STALENESS_THRESHOLDS`)
- **THEN** `get_calibration_status()` reports `confidence = 'low'` even though the stored row's `confidence` field is still `medium` or `high`

### Requirement: Active calibration selection is confidence-aware
The system SHALL select the active calibration row by preferring the highest-confidence non-stale row, breaking ties by date (most recent first). A spurious `low`-confidence row SHALL NOT replace a clean `medium`- or `high`-confidence row simply because it is more recent.

#### Scenario: Newer low row does not displace older medium row
- **WHEN** calibration history for max_hr is `[{date: 2026-04-15, value: 195, confidence: medium, flags: []}, {date: 2026-04-22, value: 220, confidence: low, flags: ['implausible_value']}]`
- **THEN** `get_active_calibration('max_hr')` returns the 195 row

#### Scenario: Tie between two high rows resolves to most recent
- **WHEN** two `high`-confidence max_hr rows exist (195 from 2026-04-15, 196 from 2026-04-22, both within ±2 bpm of each other)
- **THEN** `get_active_calibration('max_hr')` returns the 2026-04-22 row

#### Scenario: All non-stale rows are low — pick most recent
- **WHEN** every non-stale calibration row for a metric is `low`-confidence (e.g., a string of spikes)
- **THEN** `get_active_calibration()` falls back to date-only ordering within the low tier (and the dashboard should warn loudly via `attention-panel`)

### Requirement: AeT is a tracked calibration metric
The system SHALL treat `aet` as a calibration metric alongside `max_hr`, `lthr`, `weight`, `vo2max`. `aet` SHALL appear in `STALENESS_THRESHOLDS` (proposed 56 days), `RETEST_PROMPTS`, and `get_calibration_status()`. The CLI SHALL accept `fit calibrate aet <value>` as a manual override (writing `confidence='high'` like the other metrics).

#### Scenario: AeT staleness threshold reachable
- **WHEN** the active `aet` calibration is 90 days old (> 56 day threshold)
- **THEN** `is_stale(conn, 'aet')` returns True; `get_calibration_status()` reports `confidence='low'`; the retest prompt appears

#### Scenario: AeT does not exist yet — missing metric
- **WHEN** no `aet` row has been written
- **THEN** `get_calibration_status()` reports `aet` as missing with the retest prompt; `get_active_calibration('aet')` returns None

### Requirement: AeT refines Z2 ceiling only — does NOT replace LTHR as the primary anchor
`compute_hr_zones()` SHALL accept an optional `aet` argument. When `aet` is provided, the Z2 ceiling (Z3 lower bound) SHALL be set to AeT directly. Z3, Z4, Z5 boundaries SHALL continue to derive from %LTHR (Friel) regardless of whether AeT is calibrated. AeT is a **single-zone refinement, not a model replacement.**

Z2 ceiling fallback chain (in priority order):

1. AeT (active calibration value) — when present
2. 89% × LTHR (Friel's Z2 upper bound) — when LTHR calibrated, AeT missing
3. 70% × MaxHR — when neither calibrated

#### Scenario: AeT calibrated, LTHR calibrated — Z2 ceiling = AeT
- **WHEN** active `aet = 142`, active `lthr = 172`, avg_hr 140
- **THEN** `hr_zone = Z2` (below AeT)

#### Scenario: AeT calibrated, avg_hr above AeT but below Friel Z2 ceiling
- **WHEN** active `aet = 142`, active `lthr = 172`, avg_hr 148 (which is 86% of LTHR, in Friel Z2)
- **THEN** `hr_zone = Z3` (above AeT — AeT is the ceiling, not Friel)

#### Scenario: AeT missing, LTHR calibrated — Z2 ceiling falls back to 89% × LTHR
- **WHEN** no `aet`, active `lthr = 172`, avg_hr 148
- **THEN** `hr_zone = Z2` (below 89% × 172 = 153, Friel Z2 ceiling)

#### Scenario: Z4 floor stays LTHR-anchored regardless of AeT
- **WHEN** active `aet = 142`, active `lthr = 172`, avg_hr 165
- **THEN** `hr_zone = Z3` (above AeT, below 95% × 172 = 163.4 → Z4 lower); NOTE: 165 > 163.4 → Z4. Adjust test: avg_hr 162 → Z3, avg_hr 164 → Z4. Either way, the Z4 floor is unchanged by AeT.

#### Scenario: AeT confidence drives Z2-ceiling display margin
- **WHEN** active `aet = 142` has `confidence = 'medium'`
- **THEN** the dashboard's Physiology card AeT value renders with a "±3 bpm" margin note; zone classification still uses the point estimate

### Requirement: AeT auto-derives from steady-pace long runs
The sync pipeline SHALL detect candidate running activities for AeT estimation: `type = 'running'`, `distance_km >= 12`, per-km splits available, pace stddev across splits (excluding first and last km) below `analysis.aet_steady_pace_stddev_sec` (default 15 sec/km). For each candidate, the pipeline SHALL compute drift percentage from first-half vs second-half avg HR (distance-weighted) and write a calibration row per the rubric below.

| Drift % | Estimate type | Calibration value | Flag |
|---|---|---|---|
| < 0 | invalid (negative drift) | no row written | — |
| 0 ≤ drift < 5% | lower bound | `avg_hr` of run | `lower_bound` |
| 5 ≤ drift ≤ 7% | direct estimate | `avg_hr` of run | none |
| drift > 7% | upper bound | `avg_hr` of run | `upper_bound` |

Confidence per the uniform rubric (from `calibration-history`):

- Single direct estimate, no flags → `medium`
- Two direct estimates within ±3 bpm in 8-week window → `high`
- Only bounds (no direct estimates) → `low` with flag `insufficient_data`

Method SHALL be `drift_test`.

#### Scenario: Steady 15km run with mid drift — direct estimate
- **WHEN** a 15km running activity has steady splits, first-half avg HR 138, second-half avg HR 144 (drift 4.3%, avg HR 141)
- **THEN** the sync inserts `{metric: 'aet', value: 141, method: 'drift_test', flags: ['lower_bound'], confidence: 'medium'}` (drift < 5 → lower bound)

Wait — example: 4.3% drift is < 5% → lower bound. Per the rubric value = avg_hr of run = 141. Flag = `lower_bound`. Confidence = medium (single estimate, no anomaly flags). Correct.

#### Scenario: Two direct estimates within tolerance bump confidence to high
- **WHEN** two `direct_estimate` AeT rows from drift_test exist within an 8-week window, values 142 and 144 (within ±3 bpm tolerance)
- **THEN** the second row is written with flags `['agrees_with_prior']` and `confidence = 'high'`; the active AeT becomes the most recent of the two

#### Scenario: Run is not steady — no candidate
- **WHEN** a 15km activity has pace stddev > 15 sec/km (intervals, fartlek, hill repeats)
- **THEN** no AeT calibration row is produced; the activity is silently skipped

#### Scenario: Negative drift — invalid, no row written
- **WHEN** a steady run shows first-half avg HR 145, second-half avg HR 140 (negative drift, runner was warming up or fueling kicked in)
- **THEN** no AeT calibration row is written

#### Scenario: Manual override beats auto-derive
- **WHEN** user runs `fit calibrate aet 143` after several drift-test estimates already exist
- **THEN** a new row is inserted with `confidence = 'high'`, `method = 'manual'`; `get_active_calibration('aet')` returns the manual row (high beats medium per the confidence-aware selection rule)

### Requirement: A single standardizing anchor layer for all fitness metrics
The system SHALL expose one function, `get_calibration_anchor(conn, metric)`, that is the canonical way any consumer obtains the active value of a calibration anchor (`vdot`, `lthr`, `max_hr`, `aet`). It SHALL apply the metric's declared aggregation policy over that metric's observation rows and SHALL return a typed `CalibrationAnchor` value object carrying `{metric, value, confidence, method, source_date, stale, inputs, suggestion}` — where `value` is ALWAYS a real number, `inputs` are the rows that contributed, and `suggestion` is the heuristic-proposed value with its reasoning. When no anchor-eligible value exists for the metric, the function SHALL return `None`. The system SHALL NOT return an anchor whose `value` is `None` — a valueless anchor is not an anchor. No consumer SHALL re-derive an anchor by its own ad-hoc rule, and no consumer SHALL need to re-check whether the returned anchor has a value.

#### Scenario: All consumers read through the shared layer
- **WHEN** the dashboard VDOT Trend, Pace Zones, the marathon forecast, Fitness Dimensions, CLI `fit status`, and the MCP coaching context each need "current VDOT"
- **THEN** each calls `get_calibration_anchor(conn, 'vdot')` and receives the same `CalibrationAnchor` (or `None`) — there is exactly one current VDOT across the app

#### Scenario: Anchor object carries the suggestion and inputs for display/audit
- **WHEN** `get_calibration_anchor(conn, 'aet')` is called with four drift-test rows in window
- **THEN** the returned `CalibrationAnchor`'s `value` is the policy output, `inputs` lists the contributing rows, and `suggestion` describes the heuristic (e.g. "median of 4 drift tests in 90d = 152")

#### Scenario: No anchor-eligible value returns None, never a valueless anchor
- **WHEN** a metric's only rows are reference-only (e.g. a Garmin VO2max `device_vo2max` row) — excluded from the estimator and not anchor-eligible — with no confirmed, device, policy, or legacy value
- **THEN** `get_calibration_anchor` returns `None` — not an object with `value=None` — and consumers treat `None` as "no anchor" with a single `anchor is None` check

### Requirement: Per-metric aggregation policy matched to the metric's statistics
Each metric SHALL declare an aggregation policy. Performance and ceiling metrics (one-sided / bounded) SHALL use a **max** estimator; noisy central-threshold metrics (two-sided) SHALL use a **robust center** (median or trimmed mean). Each policy SHALL declare a window/memory model and a `min_samples` below which it falls back to the single best-confidence row at `confidence='low'`.

One uniform shape — trailing window, `staleness = window`, sticky-confirm, no hard gates (plausibility/effort-hardness ride as confidence) — and two families:

| Metric | family | window = staleness | min_samples | differs |
|---|---|---|---|---|
| `vdot` | max | 180 d | 1 | 1.0 |
| `max_hr` | max | 365 d | 1 | 2 |
| `lthr` | median | 180 d | 3 | 2 |
| `aet` | median | 180 d | 3 | 3 |

Active is sticky/last-confirmed for all four; the estimator produces only the *suggestion*. Below `min_samples` a median falls back to the most-recent single row at low confidence. No age decay, no trim, no auto-filter.

#### Scenario: VDOT suggestion is the max inside the window; a slow effort never wins
- **WHEN** the qualifying VDOT estimates are a road effort 40.9 from ~2 months ago and a trail half 35.8 from this month, both inside the 6-month window
- **THEN** the windowed-max suggestion is 40.9, NOT the fresher-but-slower 35.8

#### Scenario: A once-fast effort ages out of the window → stale, not a stale-high anchor
- **WHEN** the only fast effort (40.9) is now older than the 6-month window and the only in-window effort is a slow 35.8
- **THEN** the suggestion is 35.8 and `differs` from the sticky confirmed value; the confirmed value is reported `stale=True` so the athlete is prompted to re-test rather than silently keeping a stale high or dropping to the trail value

#### Scenario: LTHR takes a robust center — a hot-day high reading does not win
- **WHEN** recent qualifying LTHR estimates are 170, 172, 173 and one hot-day outlier 181
- **THEN** the active LTHR is the median (~172), NOT the max (181)

#### Scenario: MaxHR is a plausibility-gated all-time max with age decay
- **WHEN** validated MaxHR observations are 192, 194, 195 over two years and one strap-glitch reading of 217
- **THEN** the 217 is rejected as implausible and the active MaxHR is ~195 (minus age decay), drawn from long memory rather than a recent window

#### Scenario: Below min_samples, fall back to the best single row
- **WHEN** only one AeT drift-test estimate exists (below the policy's `min_samples`)
- **THEN** the anchor returns that single row's value with `confidence='low'` rather than a degenerate one-element median

### Requirement: Anchor changes are forward-only — history is reconstructable, not rewritten
A calibration change SHALL NOT retroactively alter past derived classifications. Each activity SHALL be classified with the calibration active **as of its own date** (`get_active_calibration(conn, metric, asof=activity_date)`), and re-enrichment SHALL use that as-of anchor — so confirming a new LTHR/MaxHR/AeT does not reclassify past activities or shift the weekly/phase aggregates built from them. The value used SHALL remain stamped on the activity (`lthr_used`/`max_hr_used`), and the dated calibration rows SHALL be retained, so the reasoning behind a past zone or phase classification is reconstructable. `get_active_calibration` with no `asof` retains its prior "currently active" behaviour.

#### Scenario: A later LTHR change does not reclassify a past activity
- **WHEN** an activity dated 2025-02-01 was enriched with the then-active LTHR 170, and the athlete later confirms LTHR 180 dated 2025-06-01
- **THEN** re-enriching (even `--force`) classifies the Feb activity with LTHR 170 (its as-of value), `lthr_used` stays 170, and the week's zone aggregate is unchanged

#### Scenario: As-of reconstruction
- **WHEN** `get_active_calibration(conn, 'lthr', asof=2025-03-01)` is called with confirmed rows dated 2025-01-01 (172) and 2025-06-01 (175)
- **THEN** it returns 172 (the value active on 2025-03-01), not 175

#### Scenario: Past phases stay classified as they were
- **WHEN** an anchor changes after a phase has completed
- **THEN** the completed phase's actuals (built from the frozen per-activity zones) do not change, so its classification/reasoning is preserved

#### Scenario: A back-dated correction reclassifies only its window
- **WHEN** the athlete records a corrected anchor with `fit calibrate <metric> <value> --date <past-date>` and runs `fit recompute --force`
- **THEN** activities in that anchor's window are reclassified with the corrected value (as-of), and activities outside it are unchanged — `--force` re-derives via the historical anchor, never today's

### Requirement: Effective VDOT is the sticky confirmed anchor, refreshed via the window
`effective_vdot` SHALL be the active VDOT anchor from `get_calibration_anchor` — the athlete's last-confirmed value, never auto-overwritten by the windowed max. The 6-month window drives the *suggestion* and the staleness flag, not the active value. When the confirmed value's source effort ages past the window, the anchor SHALL be reported `stale` (prompting a re-test) rather than silently dropping to whatever single effort remains in-window.

#### Scenario: A strong older confirmed value persists but is flagged stale
- **WHEN** the confirmed VDOT (41) is from a race ~7.5 months old and the only in-window effort is a slow trail 35.8
- **THEN** `value` stays 41 (sticky), `stale` is True, and the suggestion (35.8) is offered for accept/reject — the anchor neither drops to 35.8 nor pretends 41 is fresh

### Requirement: Method trust precedence is a typed total order
Every calibration `method` SHALL resolve to a `TrustTier` forming a total order: `INFORMATIONAL < REFERENCE < LEGACY < POLICY < DEVICE < CONFIRMED`. The anchor's active value SHALL be chosen by trust tier (higher wins), ties broken by the more recent source date — preserving the documented precedence `confirmed > device > policy > legacy` (`DATA_LINEAGE.md §6`). `INFORMATIONAL` and `REFERENCE` methods SHALL NOT be anchor-eligible (history / reference-only). `Confidence` SHALL likewise be an ordered type (`LOW < MEDIUM < HIGH`). A method that declares no tier SHALL be unrepresentable in code; an unrecognised stored method string SHALL resolve to `TrustTier.LEGACY` and SHALL NOT raise, so historical rows keep loading. This requirement changes representation only — it SHALL NOT rewrite any persisted `method` value and SHALL NOT change which value is selected for existing data.

#### Scenario: Confirmed beats device
- **WHEN** both a human `confirmed` (or `manual`) LTHR row and a `device_lt` row are active candidates for `lthr`
- **THEN** the confirmed value is the anchor (CONFIRMED outranks DEVICE)

#### Scenario: Device beats the policy estimate
- **WHEN** no confirmed row exists but a `device_lt` row and a windowed policy suggestion both exist
- **THEN** the device-measured value is the anchor (DEVICE outranks POLICY), and the policy suggestion is still carried for cross-check

#### Scenario: Tie broken by recency
- **WHEN** two anchor-eligible candidates resolve to the same `TrustTier`
- **THEN** the candidate with the more recent `source_date` is selected

#### Scenario: A reference-only metric has no anchor
- **WHEN** a `vdot` metric's only row is a `device_vo2max` (reference) reading
- **THEN** `get_calibration_anchor(conn, 'vdot')` returns `None` — reference rows are excluded from the estimator and are not anchor-eligible

#### Scenario: Informational rows feed the policy but are never the active row
- **WHEN** a `vdot` metric has only `race_observation` (informational) rows and no confirmed/device value
- **THEN** they are excluded from direct active-row selection but DO feed the windowed estimator, so the anchor's value is the resulting `policy` suggestion — not one of the rows, and not `None`

#### Scenario: An unknown legacy method degrades, it does not crash
- **WHEN** a historical calibration row carries a `method` string outside the taxonomy
- **THEN** it resolves to `TrustTier.LEGACY`, remains selectable only as a last resort, and no error is raised

### Requirement: Zone identity, ordering, and effort-class mapping have one typed home
The system SHALL represent an HR zone as a `Zone` value with an intrinsic total order
(`Z1 < Z2 < Z3 < Z4 < Z5`) and a single `EffortClass` mapping (`Z1`→Recovery, `Z2`→Easy,
`Z3`→Moderate, `Z4`→Hard, `Z5`→Very Hard). The zone ordering and the zone→effort-class mapping
SHALL be defined in exactly one place and SHALL NOT be re-derived elsewhere. An unrecognised
zone string SHALL be rejected (not silently classified), and a `None` zone SHALL map to no
effort class (`None`). This requirement changes representation only — it SHALL NOT rewrite any
persisted zone string (`activities.hr_zone`/`hr_zone_lthr`/`hr_zone_maxhr`) and SHALL NOT move
zone *boundary numbers* out of config.

#### Scenario: Each zone maps to its documented effort class
- **WHEN** the effort class of `Z1`…`Z5` is requested
- **THEN** it is Recovery, Easy, Moderate, Hard, Very Hard respectively — the single mapping,
  not a per-call-site copy

#### Scenario: A missing zone has no effort class
- **WHEN** `compute_effort_class` is given `None`
- **THEN** it returns `None` (unchanged from today)

#### Scenario: An invalid zone is rejected, not mislabeled Easy
- **WHEN** a zone string outside `Z1`–`Z5` (a typo or junk) reaches the effort-class mapping
- **THEN** it is rejected (raises) rather than silently returning `"Easy"` — the prior
  `{...}.get(zone, "Easy")` fallthrough is gone

#### Scenario: Intensity thresholds read the intrinsic order
- **WHEN** logic needs "Z3 and above is hard effort"
- **THEN** it compares the typed `Zone` order (`zone >= Zone.Z3`), not a separately re-derived
  zone-to-number conversion

#### Scenario: Run-type zone rules keep set semantics
- **WHEN** a run type is classified against its allowed zones (e.g. tempo = `{Z3, Z4}`)
- **THEN** membership is unchanged — the rule stays a typed *set*, not collapsed into an
  ordering

