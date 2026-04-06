# Phase 2 — Enrich: Race-Anchored Model, Deep Analysis, Storytelling

## Why

Phase 1 + gaps delivered a working platform with 412 tests, 14 tables, 5-tab dashboard, correlations, alerts, and race calendar. But three fundamental issues remain:

1. **The data model has a conceptual split** — races and goals overlap without connecting. "Berlin Marathon sub-4:00" exists as both a goal AND a race_calendar entry, but they don't reference each other. Goal progress is hardcoded in the generator, not driven by the DB.

2. **The dashboard shows charts but doesn't tell stories** — no trend narratives ("your efficiency improved 8% in 6 weeks"), no "why" connectors ("your 3 worst runs all followed <6h sleep nights"), no race countdown narrative connecting phases to the finish line.

3. **Run analysis is surface-level** — avg HR per run loses information. Zone classification assigns the entire duration to one zone. No per-km splits, no cardiac drift detection, no form analysis.

## What Changes

Three sub-phases, ordered by architectural impact:

**Phase 2a — "Race-Anchored Model"**: Refactor goals → objectives linked to a target race. Dashboard reorients around race countdown + objectives + phase plan. Fix hardcoded goal progress. Add trend narratives.

**Phase 2b — "Deep Run Analysis"**: .fit file parsing for per-km splits, rolling cardiac drift detection, cadence drift, time-in-zone per split. Training monotony/strain metrics. Heat-adjusted zones.

**Phase 2c — "Plan + Story"**: Runna plan integration with adherence tracking. Run Story narrative. sRPE (session RPE × duration) as validated load metric. Periodization feedback loop.

## Capabilities

### Race-Anchored Model (Phase 2a)

- **race-model-refactor** — Add `race_id` FK to goals table. Target race = next registered in race_calendar. Objectives (renamed conceptually from goals) serve the race. Dashboard auto-orients: countdown + prediction + objectives + phase compliance. `_goal_progress()` reads targets from DB (no hardcoded 51, 75, 8). Phase lifecycle: auto-detect "Phase 1 complete, advance to Phase 2" based on objective achievement.

- **trend-narratives** — Rule-based "This Month" summary: "Your aerobic efficiency improved 8% over 6 weeks. VO2max stable at 49. Zone compliance improved from 0% to 72%." Displayed on Today tab below headline. Also: "Your 3 worst runs all followed nights with <6h sleep" — connecting correlations to actual experiences, not just r-values.

- **race-countdown-narrative** — "165 days to Berlin. Phase 2 of 4. 3 of 4 objectives on track. Current prediction: 3:52." Connects countdown to phase plan and objective progress.

- **wow-context** — Week-over-week annotated against phase targets: "Volume up 15% — but Phase 1 target increase is ≤10%."

- **rolling-correlations** — 8-week rolling window showing "this correlation is getting stronger/weaker." More actionable than static r-values.

### Deep Run Analysis (Phase 2b)

- **fit-file-analysis** — Parse .fit files for per-km splits with extended metrics: time_above_z2_ceiling per split, elevation profile, HR zones per km (not just avg HR for entire run). Fixes the zone-time underestimation problem.

- **training-monotony** — stdev(daily_load) per week = monotony. Weekly_load × monotony = strain. Classic Banister/Foster injury predictors. Add to weekly_agg.

- **heat-adjusted-zones** — Flag runs at >25°C or >70% humidity as "heat-affected." Adjust zone classification or add a "heat penalty" annotation. Run at 30°C is physiologically a zone harder than HR suggests.

- **srpe-load** — session RPE × duration_min = sRPE (validated internal load metric). Cross-validates against Garmin's EPOC-based training load. Requires RPE data from checkins.

- **improved-race-prediction** — Replace linear VDOT approximation with Daniels lookup table (or polynomial fit). Current formula diverges badly outside VO2max 45-55. Also: long run threshold as % of weekly volume (>30%), not hardcoded max(15, avg×0.75).

### Plan + Story (Phase 2c)

- **runna-integration** — Import plans with structure JSON for intervals. Weekly compliance. Systematic override detection. Rest day compliance. Connect readiness data to planned workouts for gating.

- **run-story** — Narrative paragraph for most recent long run: splits + correlations + checkin + weather synthesized. "Sunday's 18km: held 5:45 through km 14, then faded to 6:10. HR drifted +11%. 2 drinks Saturday, sleep quality poor."

- **periodization-feedback** — Detect "you completed Phase 1 objectives, time to advance" or "you're struggling, extend this phase." Currently phases are entirely manual.

### Tech Debt + Engineering

- **zero-test-coverage-paths** — Add tests for garmin.py (mock API), sync.py (mock pipeline), weather.py. These are the critical data entry point.

- **weather-retry** — Add retry/backoff to weather.py (garmin.py already has `_request_with_retry`, weather.py has none).

- **year-boundary-bug** — `_compute_acwr` has ISO week 53 handling bug. Fix.

- **race-calendar-fk** — Add proper FK constraint from race_calendar.activity_id to activities.id.

- **alert-sql-fix** — The all_runs_too_hard query only returns 1 week due to `WHERE >= MAX()`. Fix to actually average 2 weeks.

- **generator-refactor** — Extract 860-line generator.py into sections (engine, cards, charts, predictions).

### Design Notes

- **training_phases.goal_id indirection** — Phases link to races through goals (phase → goal → race via race_id). No direct training_phases.race_id needed; the indirection works and avoids a schema change to training_phases.

- **Heat-aware coaching** — Heat flags on runs (Phase 2b) must also feed into `get_coaching_context()` and `generate_headline()` so coaching advice accounts for heat-affected runs.

- **Sleep mismatches → narratives** — Existing sleep mismatch detection (Garmin hours vs subjective quality) feeds into the "why" connector narrative engine (task 3.3).

- **Migration numbering** — 007: goals.race_id. 008: activity_splits. 009: planned_workouts. No collisions.

## Impact

- **Race-anchored model** transforms the dashboard from "here are some charts" to "here's your race, here's your plan, here's where you are"
- **Trend narratives** answer "is it working?" without requiring chart interpretation
- **.fit analysis** enables per-km coaching: "your HR decoupled at km 14 — that's your aerobic ceiling"
- **Training monotony/strain** catch overtraining before ACWR does (leading indicator)
- **Bug fixes** prevent silent data errors in ACWR and alerts
