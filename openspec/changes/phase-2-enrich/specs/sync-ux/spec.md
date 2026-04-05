## ADDED Requirements

### Requirement: Rich progress bar for fit sync
`fit sync` SHALL display a Rich progress bar showing: current step (health/activities/SpO2/weather/enrichment/weekly_agg), items processed vs total, elapsed time, ETA for `--full`. Each step shows a sub-progress bar.

#### Scenario: Normal sync with progress
- **WHEN** user runs `fit sync --days 7`
- **THEN** a progress bar shows: "Health [====    ] 4/7 days" → "Activities [========] 3/3" → etc.

#### Scenario: Full sync with ETA
- **WHEN** user runs `fit sync --full`
- **THEN** progress bar shows estimated time remaining based on API response rate

### Requirement: Better error messages
Sync errors SHALL include clear context: what was being fetched, which date failed, and whether the error is transient (retry) or permanent (fix config).

#### Scenario: Auth token expired
- **WHEN** garth token refresh fails
- **THEN** error shows: "Garmin auth expired. Run: python -c 'import garth; garth.login(email, pw); garth.save(path)'"

#### Scenario: API rate limit
- **WHEN** Garmin API returns 429
- **THEN** sync pauses with: "Rate limited. Waiting 60s..." and retries

### Requirement: ioBroker integration (optional)
The system SHALL optionally expose daily metrics via a JSON file or MQTT endpoint for ioBroker home automation dashboards. Metrics: readiness, ACWR, last run summary, weight, streak. Configured via `config.yaml` `iobroker` section.

#### Scenario: JSON export for ioBroker
- **WHEN** `iobroker.enabled: true` in config and `fit sync` completes
- **THEN** a `~/.fit/iobroker.json` file is written with key daily metrics

#### Scenario: ioBroker not configured
- **WHEN** no `iobroker` section in config
- **THEN** no JSON file is written (no impact on normal operation)
