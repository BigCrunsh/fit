## ADDED Requirements

### Requirement: Sync auto-derives AeT from candidate steady-pace long runs
The sync pipeline SHALL include a stage that walks new running activities ≥12km with per-km splits, identifies "steady" candidates by pace stddev (default <15 sec/km, configurable via `analysis.aet_steady_pace_stddev_sec`), computes first-half vs second-half HR drift (distance-weighted), and writes an `aet` calibration row per the drift-classification rubric (see `fitness-profile` spec delta).

The stage SHALL be enabled by default. Failures (e.g., missing splits) SHALL be logged as debug and SHALL NOT block the rest of the sync pipeline.

#### Scenario: Steady long run triggers AeT row on sync
- **WHEN** a new 18km running activity has per-km splits with pace stddev 12 sec/km and computable drift
- **THEN** the sync inserts an `aet` calibration row per the rubric; `counts['aet']` is incremented; the sync log records the value, method, and flags

#### Scenario: Non-steady run is skipped silently
- **WHEN** a new 15km running activity has pace stddev 25 sec/km (e.g., hill repeats packaged as a long run)
- **THEN** the sync produces no `aet` row; no warning; debug log records "skipped: pace_stddev exceeds threshold"

#### Scenario: Activity without splits is skipped silently
- **WHEN** a 20km running activity has no rows in `activity_splits` (splits download disabled / failed)
- **THEN** the sync produces no `aet` row; no warning; debug log records "skipped: no splits"

#### Scenario: Sync pipeline keeps working when AeT stage fails
- **WHEN** the AeT auto-derive stage raises an unexpected exception
- **THEN** the exception is caught, logged as a warning, and the rest of the sync pipeline completes normally
