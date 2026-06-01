## MODIFIED Requirements

### Requirement: Alert severity is explicit
Every alert returned by `run_alerts()` SHALL include an explicit `severity` field with value `critical`, `warning`, or `info`. Severity SHALL be a property of the alert *rule*, not derived at render time.

| Rule | Severity |
|---|---|
| `acwr_spike_danger` (ACWR > 1.5) | `critical` |
| `readiness_gate` (<40 or <50 during return-to-run) | `critical` |
| `volume_ramp` (>10% increase AND streak <8) | `critical` |
| `all_runs_too_hard` (z12_pct <50%) | `warning` |
| `alcohol_hrv_drop` | `warning` |
| `monotony_high` | `warning` |
| `feel_compliance_low` | `info` |
| (any rule not listed) | `info` |

#### Scenario: Critical alert fires with severity
- **WHEN** ACWR rises above 1.5
- **THEN** the fired alert dict contains `{..., 'severity': 'critical', ...}`

#### Scenario: Warning alert fires with severity
- **WHEN** `all_runs_too_hard` fires because z12_pct is 30%
- **THEN** the fired alert dict contains `{..., 'severity': 'warning', ...}`

#### Scenario: Unknown rule defaults to info
- **WHEN** a future alert rule is added without an explicit severity
- **THEN** the alert dict still contains `'severity': 'info'` — never absent
