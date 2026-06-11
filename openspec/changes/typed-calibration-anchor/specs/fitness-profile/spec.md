## MODIFIED Requirements

### Requirement: A single standardizing anchor layer for all fitness metrics
The system SHALL expose one function, `get_calibration_anchor(conn, metric)`, that is the canonical way any consumer obtains the active value of a calibration anchor (`vdot`, `lthr`, `max_hr`, `aet`). It SHALL apply the metric's declared aggregation policy over that metric's observation rows and SHALL return a typed `CalibrationAnchor` value object carrying `{metric, value, confidence, method, source_date, stale, inputs, suggestion}` — where `value` is ALWAYS a real number, `inputs` are the rows that contributed, and `suggestion` is the heuristic-proposed value with its reasoning. When no anchor-eligible value exists for the metric, the function SHALL return `None`. The system SHALL NOT return an anchor whose `value` is `None` — a valueless anchor is not an anchor. No consumer SHALL re-derive an anchor by its own ad-hoc rule, and no consumer SHALL need to re-check whether the returned anchor has a value.

#### Scenario: All consumers read through the shared layer
- **WHEN** the dashboard VDOT Trend, Pace Zones, the marathon forecast, Fitness Dimensions, CLI `fit status`, and the MCP coaching context each need "current VDOT"
- **THEN** each calls `get_calibration_anchor(conn, 'vdot')` and receives the same `CalibrationAnchor` (or `None`) — there is exactly one current VDOT across the app

#### Scenario: Anchor object carries the suggestion and inputs for display/audit
- **WHEN** `get_calibration_anchor(conn, 'aet')` is called with four drift-test rows in window
- **THEN** the returned `CalibrationAnchor`'s `value` is the policy output, `inputs` lists the contributing rows, and `suggestion` describes the heuristic (e.g. "median of 4 drift tests in 90d = 152")

#### Scenario: No anchor-eligible value returns None, never a valueless anchor
- **WHEN** a metric has only reference-only/informational rows (e.g. a Garmin VO2max `device_vo2max` row) and no confirmed, device, policy, or legacy value
- **THEN** `get_calibration_anchor` returns `None` — not an object with `value=None` — and consumers treat `None` as "no anchor" with a single `anchor is None` check

## ADDED Requirements

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

#### Scenario: Reference and informational rows are never the anchor
- **WHEN** a `vdot` metric has only a `device_vo2max` (reference) row and `race_observation` (informational) rows, with no confirmed/device/policy/legacy value
- **THEN** `get_calibration_anchor(conn, 'vdot')` returns `None`

#### Scenario: An unknown legacy method degrades, it does not crash
- **WHEN** a historical calibration row carries a `method` string outside the taxonomy
- **THEN** it resolves to `TrustTier.LEGACY`, remains selectable only as a last resort, and no error is raised
