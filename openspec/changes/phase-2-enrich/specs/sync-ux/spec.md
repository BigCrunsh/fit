## ADDED Requirements

### Requirement: Rich progress bar for fit sync
`fit sync` SHALL display Rich progress bars per step (health/activities/SpO2/weather/enrichment/weekly_agg), with item counts and ETA for `--full`. Progress bars SHALL not interleave with logging output (suppress console logging during progress, buffer to file).

#### Scenario: Normal sync with progress
- **WHEN** user runs `fit sync --days 7`
- **THEN** progress bar shows per-step: "Health [====    ] 4/7 days" → "Activities [========] 3/3" → etc.

#### Scenario: Full sync with ETA
- **WHEN** user runs `fit sync --full`
- **THEN** progress bar shows estimated time remaining based on API response rate

#### Scenario: No interleave with logs
- **WHEN** progress bars are active
- **THEN** Python logging output goes to file only (not console), avoiding garbled output

### Requirement: Shared retry/backoff utility
`fit/garmin.py` SHALL have a `_request_with_retry(func, max_retries=3)` wrapper that handles: 429 (rate limit) with countdown timer, 401 (re-auth prompt), transient 5xx with exponential backoff. All Garmin API calls use this wrapper.

#### Scenario: Rate limit with countdown
- **WHEN** Garmin API returns 429
- **THEN** sync shows "Rate limited. Waiting 60s..." with countdown, then retries

#### Scenario: Auth expired with instructions
- **WHEN** garth token refresh fails with 401
- **THEN** error: "Garmin auth expired. Run: python -c 'import garth; garth.login(email, pw); garth.save(path)'"

### Requirement: Post-sync hook system
The system SHALL support a `post_sync_hooks` config list. After sync completes, each hook is called. ioBroker JSON export is one hook (`fit.hooks.iobroker_json`), not hardcoded in sync.py.

#### Scenario: ioBroker hook configured
- **WHEN** config has `hooks.post_sync: ["fit.hooks.iobroker_json"]` and sync completes
- **THEN** `~/.fit/iobroker.json` is written with: readiness, ACWR, last run, weight, streak, headline

#### Scenario: No hooks configured
- **WHEN** no `hooks` section in config
- **THEN** sync completes normally, no hooks run

### Requirement: fit doctor diagnostic command
`fit doctor` SHALL validate the entire data pipeline: DB schema version matches code, all expected tables exist, no orphaned splits without activities, correlation freshness, plan import recency, weight staleness, calibration status, data source health.

#### Scenario: All healthy
- **WHEN** everything is in order
- **THEN** `fit doctor` shows all green checks

#### Scenario: Issues detected
- **WHEN** weekly_agg is stale or correlations are outdated
- **THEN** `fit doctor` shows warnings with remediation commands
