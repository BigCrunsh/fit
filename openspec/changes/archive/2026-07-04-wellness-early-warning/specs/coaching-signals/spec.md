# coaching-signals — delta for wellness-early-warning

## ADDED Requirements

### Requirement: Shared wellness baseline snapshot
The system SHALL provide a single wellness-baseline computation (`fit/wellness.py: wellness_snapshot`) used by all consumers (alert rules, coaching context, dashboard chart). For each signal (sleep respiration with waking-respiration fallback, RHR, HRV), the snapshot SHALL compute a personal baseline as the rolling median of the trailing `wellness_baseline_days` (default 28) observations that precede the evaluation window, requiring at least 14 observations; with fewer observations the baseline is undefined and no deviation state is reported. Deviation states SHALL compare each evaluated day against this fixed pre-window baseline. A day with missing data SHALL break a consecutive-deviation streak (no interpolation). The sleep-respiration series and waking-respiration series SHALL never be mixed within one baseline (each series deviates only against its own baseline).

#### Scenario: Baseline undefined with insufficient history
- **WHEN** only 10 days of RHR observations exist
- **THEN** the RHR baseline is undefined and no RHR deviation state (and no alert) is produced

#### Scenario: Baseline excludes the evaluation window
- **WHEN** the last 2 nights are being evaluated for respiration deviation
- **THEN** the baseline median is computed only from nights before those 2 nights

#### Scenario: Missing day breaks a streak
- **WHEN** RHR is elevated on day-3 and day-1 but day-2 has no RHR reading
- **THEN** the consecutive-elevation count is 1, not 3

#### Scenario: Waking fallback when sleep series is thin
- **WHEN** `avg_sleep_respiration` has fewer than 14 observations but `avg_respiration` (waking) has 28+
- **THEN** the respiration deviation state is computed from the waking series against the waking baseline

### Requirement: Respiration elevation alert
The system SHALL fire a `respiration_elevated` alert (severity: warning) when the latest 2 or more consecutive nights each show sleep respiration ≥ baseline + `respiration_delta_brpm` (default 2.0 brpm, configurable under `coaching:`). The alert message SHALL state the observed average, the baseline, and the possible-illness/overtraining interpretation. The auto-dismiss re-evaluation SHALL use the same shared snapshot computation as the fire rule.

#### Scenario: Two elevated nights fire the alert
- **WHEN** baseline sleep respiration is 15.0 and the last 2 nights read 17.2 and 17.5
- **THEN** `respiration_elevated` fires with severity warning

#### Scenario: Single elevated night does not fire
- **WHEN** baseline is 15.0, the previous night read 15.2, and last night read 18.0
- **THEN** no `respiration_elevated` alert fires

#### Scenario: Boundary — exactly baseline plus delta counts as elevated
- **WHEN** baseline is 15.0, delta is 2.0, and the last 2 nights each read exactly 17.0
- **THEN** `respiration_elevated` fires

#### Scenario: Auto-dismiss when respiration normalizes
- **WHEN** a `respiration_elevated` alert exists and the latest 2 nights are below baseline + delta
- **THEN** the alert is auto-dismissed by `get_recent_alerts`

### Requirement: Resting-heart-rate elevation alert
The system SHALL fire an `rhr_elevated` alert (severity: warning) when the latest 3 or more consecutive days each show RHR ≥ baseline + `rhr_delta_bpm` (default 5 bpm, configurable under `coaching:`). The auto-dismiss re-evaluation SHALL use the same shared snapshot computation as the fire rule.

#### Scenario: Three elevated days fire the alert
- **WHEN** baseline RHR is 55 and the last 3 days read 61, 60, 62
- **THEN** `rhr_elevated` fires with severity warning

#### Scenario: Two elevated days do not fire
- **WHEN** baseline RHR is 55 and only the last 2 days are ≥ 60
- **THEN** no `rhr_elevated` alert fires

#### Scenario: Elevated streak interrupted by a normal day
- **WHEN** the last 4 days read 61, 54, 61, 62 against baseline 55
- **THEN** the consecutive count is 2 and no alert fires

### Requirement: Recovery-cliff compound alert
The system SHALL fire a `recovery_cliff` alert (severity: critical) when, on the most recent day with data, ALL of the following hold: (1) RHR ≥ baseline + `rhr_delta_bpm`; (2) HRV status is `LOW`, or — when status is missing — `hrv_last_night` < 0.85 × the HRV baseline; (3) training readiness < 50. This is a same-day compound signal and fires independently of the consecutive-day rules. The auto-dismiss re-evaluation SHALL use the same shared snapshot computation as the fire rule.

#### Scenario: All three conditions met fires critical
- **WHEN** RHR is 62 (baseline 55), HRV status is LOW, and readiness is 38
- **THEN** `recovery_cliff` fires with severity critical

#### Scenario: Two of three conditions do not fire
- **WHEN** RHR is 62 (baseline 55) and readiness is 38, but HRV status is BALANCED and HRV is at baseline
- **THEN** no `recovery_cliff` alert fires

#### Scenario: HRV ratio fallback when status missing
- **WHEN** HRV status is NULL, HRV baseline is 40, `hrv_last_night` is 32, RHR is elevated, and readiness is 42
- **THEN** `recovery_cliff` fires (32 < 0.85 × 40)

#### Scenario: No readiness reading blocks the compound rule
- **WHEN** RHR is elevated and HRV status is LOW but the latest day has no readiness value
- **THEN** no `recovery_cliff` alert fires

### Requirement: Coaching context includes respiration
The coaching context health section (`_ctx_health`) SHALL include a respiration line with the 7-day average of the active respiration series (sleep preferred, waking fallback, labelled accordingly), the personal baseline when defined, and an ELEVATED flag with the consecutive-night count when the deviation state is active. When no respiration data exists, the line SHALL be omitted.

#### Scenario: Respiration line with baseline and flag
- **WHEN** the sleep-respiration 7d average is 17.1, baseline is 15.0, and the last 2 nights are elevated
- **THEN** the context contains a line reporting 17.1 brpm, baseline 15.0, and an ELEVATED flag with 2 nights

#### Scenario: No respiration data omits the line
- **WHEN** `daily_health` has no respiration values in the window
- **THEN** the context has no respiration line
