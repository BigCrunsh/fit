## ADDED Requirements

### Requirement: The marathon posterior is refit and cached, not recomputed per read
`fit sync` SHALL (after ingest) refit the marathon model and cache the posterior to `~/.fit/marathon_posterior.nc`; prediction, trend, and derived-metric reads SHALL reuse the cached draws without resampling. Refitting SHALL NOT block the core sync when PyMC is unavailable — it logs and skips. CTL/ATL features SHALL be computed from daily `training_load` using loads strictly *before* each effort day (incoming fitness, excluding the effort's own load).

#### Scenario: Sync refits and caches
- **WHEN** `fit sync` completes ingest and PyMC is installed
- **THEN** the model is refit and the posterior written to `~/.fit/marathon_posterior.nc`; a subsequent `fit report` reads that file with no resampling

#### Scenario: Sync without the forecast extra does not break
- **WHEN** `fit sync` runs and PyMC is not installed
- **THEN** the refit step logs a skip and sync completes normally; the dashboard uses the fallback prediction

#### Scenario: Incoming fitness excludes the effort's own load
- **WHEN** computing CTL for an effort on day D
- **THEN** only loads from days strictly before D contribute, so a hard effort does not inflate its own incoming-fitness covariate
