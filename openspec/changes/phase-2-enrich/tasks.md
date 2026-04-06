# Phase 2a: Race-Anchored Model + Storytelling

## 1. Bug Fixes + Tech Debt

- [ ] 1.1 Fix `_compute_acwr` year-boundary bug — ISO week 53 handling (prev_week += 52 wrong for 53-week years)
- [ ] 1.2 Fix alert SQL: `all_runs_too_hard` query only returns 1 week due to `WHERE >= MAX()` — fix to average last 2 weeks
- [ ] 1.3 Add FK constraints via table rebuild migrations (SQLite ALTER TABLE ADD COLUMN doesn't enforce FKs): race_calendar.activity_id, goals.race_id
- [ ] 1.4 Add tests for garmin.py (mock Garmin API responses, test fetch_health/activities/spo2 dict mapping)
- [ ] 1.5 Add tests for sync.py (mock pipeline: enrich → upsert → weather → weekly_agg)
- [ ] 1.6 Add tests for weather.py (mock Open-Meteo responses)
- [ ] 1.7 Add retry/backoff to weather.py — shared `_request_with_retry` wrapper for Open-Meteo API calls
- [ ] 1.8 Refactor generator.py (860+ lines) — extract into `fit/report/sections/` package: engine.py, cards.py, charts.py, predictions.py
- [ ] 1.9 Refactor sync.py (170+ lines growing) — decompose `run_sync()` into composable pipeline stages (fetch, enrich, store, weather, aggregate, correlate, alert) so each step is independently testable and new steps don't increase blast radius
- [ ] 1.10 Fix SpO2 alert threshold: change from <93% to <95% for sea-level runners (93% is severe desaturation — athlete would already feel terrible). Make threshold configurable.
- [ ] 1.11 Fix long run threshold: >30% of weekly volume AND absolute minimum floor (12km or 75min for sub-4:00). Current proposal removes floor entirely — wrong.
- [ ] 1.12 Define `[analysis]` extra in pyproject.toml for fitparse. Ensure `fit sync --splits` degrades gracefully with clear error if fitparse not installed.
- [ ] 1.13 Test: all bugs verified fixed, new tests pass

## 2. Race-Anchored Data Model

- [ ] 2.1 Add migration 007: goals.race_id (via table rebuild for FK enforcement), sRPE column on activities, monotony + strain + cycling_km + cycling_min columns on weekly_agg. Consolidate all Phase 2a schema changes into ONE migration.
- [ ] 2.2 Link existing goals to Berlin Marathon race_calendar entry (VO2max, Weight, Streak → race_id)
- [ ] 2.3 Refactor `_goal_progress()` to read ALL targets from goals table (remove hardcoded 51, 75, 8). Define join strategy for sRPE: checkin RPE → most recent same-day activity (if 2 runs same day, RPE goes to the harder one by training_load).
- [ ] 2.4 Add target race resolution: `get_target_race(conn)` → next registered race from race_calendar
- [ ] 2.5 Refactor Today tab: race countdown as anchor ("Berlin Marathon: 174 days"), objectives below, phase compliance, prediction. Define visual hierarchy: headline → race countdown → alerts → objectives → "This Month" → phase compliance → journey. Use progressive disclosure for narratives (collapse after 2 items).
- [ ] 2.6 Dashboard headline: "Berlin Marathon: 174 days — Phase 1 of 4 — prediction: 3:52"
- [ ] 2.7 `fit status` shows target race countdown, objective progress, phase position
- [ ] 2.8 Pull milestone/PB tracking into 2a (was 7.2 in Phase 2c): detect new longest run, best efficiency, streak milestones, VO2max peak. Display as celebration cards on Today tab.
- [ ] 2.9 Test: race-anchored model, goal progress from DB, target race resolution, milestones

## 3. Trend Narratives + Story Connectors

- [ ] 3.1 Implement `fit/narratives.py` — rule-based "This Month" summary as pill-style badges (not paragraph): "Efficiency +8%" green, "VO2max flat" gray, "Z2 compliance 72% ↑" green, "Volume 28km/wk" blue. Expandable detail on click. Define minimum-data threshold per metric (e.g., need 4+ weeks for efficiency trend).
- [ ] 3.2 Add "This Month" narrative to Today tab below headline. Fallback message for insufficient data: "Keep logging — 3 more weeks until trends emerge."
- [ ] 3.3 Add "why" connectors — find the N worst/best runs and preceding data (sleep <6h, cycling >30km, alcohol >1). Include sleep mismatches. Mark these runs on the Training Load chart via Chart.js annotations (not just text narrative). Define empty-state: "Need 10+ runs with checkin data to detect patterns."
- [ ] 3.4 Week-over-week annotated against phase targets: "Volume up 15% — Phase 1 target is ≤10%"
- [ ] 3.5 Implement rolling 8-week correlation windows — sparkline small-multiples grid (one per pair, not spaghetti chart). Incremental computation: only recompute if new data arrived for the window. Define empty-state for <8 weeks of data.
- [ ] 3.6 Race countdown narrative: "174 days to Berlin. Phase 1 of 4. 3/4 objectives on track." Include taper rules for final 2-3 weeks (volume drop 40-60%, last quality session ~10 days out).
- [ ] 3.7 Add walk-break detection: if Z2 runs show cardiac drift before km 5, suggest structured run-walk intervals as training tool (not failure). Add as narrative rule.
- [ ] 3.8 Add end-to-end integration test: sync with race-anchored goals → produces correct dashboard narratives. Test the full chain: sync layer → model layer → narrative layer.
- [ ] 3.9 Test: narrative generation (with specific edge cases: zero-variance weeks, single data point, division by zero in rolling windows), why-connectors, rolling correlations, empty states

## 4. Improved Coaching Metrics

- [ ] 4.1 Replace linear VDOT approximation with Daniels lookup table (or polynomial fit accurate across VO2max 35-60)
- [ ] 4.2 Fix long run threshold — >30% of weekly km AND ≥12km absolute floor (dual condition)
- [ ] 4.3 Add sRPE (session RPE × duration) as validated internal load metric. Store on activities (from migration 007). Join strategy: checkin RPE → most recent same-day activity by training_load.
- [ ] 4.4 Implement training monotony (stdev of daily loads per week) and strain (weekly_load × monotony) — add to weekly_agg (from migration 007)
- [ ] 4.5 Add cycling volume to training model — `cycling_km`, `cycling_min` in weekly_agg (from migration 007). Show in fit status and Training tab. Factor into headline, "why" connectors, and new correlation pair.
- [ ] 4.6 Add SpO2 illness alert: avg_spo2 < 95% (configurable) for 2+ consecutive days → "Possible illness — consider rest."
- [ ] 4.7 Consider adding correlation pair: SpO2 → training_readiness
- [ ] 4.8 Extend FitDays CSV import to parse body_fat_pct, muscle_mass_kg, visceral_fat. Add body fat trend to Body tab weight chart (second y-axis). Include body comp in coaching context.
- [ ] 4.9 Add deload/recovery week logic: every 3rd or 4th week, volume should drop 30-40%. Alert if no deload in 4+ consecutive build weeks.
- [ ] 4.10 Test: Daniels table, long run dual condition, sRPE join, monotony/strain, cycling, SpO2, body comp, deload detection

---

# Phase 2b: Deep Run Analysis

## 5. .fit File Analysis

- [ ] 5.1 Add `fitparse` to `[analysis]` optional dependencies in pyproject.toml (new extras group)
- [ ] 5.2 Add migration 008: `activity_splits` table + `fit_file_path`, `splits_status` columns on activities
- [ ] 5.3 Add `sync.download_fit_files` config toggle (default false) + `sync.max_fit_downloads: 20`
- [ ] 5.4 Implement `fit/fit_file.py` — download .fit via garminconnect (using retry), parse with fitparse, per-km splits, per-file failure handling. Use minimal synthetic .fit fixture for tests (not real files — keep tests fast, avoid licensing).
- [ ] 5.5 Extract per-split zone time: time_above_z2_ceiling_sec per split (fixes the "entire run = one zone" problem)
- [ ] 5.6 Implement rolling 1km cardiac drift detection — find drift_onset_km, constant-pace filter (CV > 15% = inconclusive)
- [ ] 5.7 Implement pace variability (CV across splits), cadence drift metrics
- [ ] 5.8 Implement heat-adjusted zone flags — runs at >25°C or >70% humidity flagged, zone penalty annotation. Update `get_coaching_context()` and `generate_headline()` for heat-affected runs.
- [ ] 5.9 Integrate into `fit sync --splits` + `fit splits --backfill` with rate control (max 20 per batch, 2s delay between downloads to avoid Garmin throttling)
- [ ] 5.10 Add split visualization: dual-panel (top: pace bars zone-colored, bottom: HR line with expected-HR reference). Drift onset marked with vertical annotation. Most recent long run only inline; historical behind "View splits" link. Drift gauge card above.
- [ ] 5.11 Add split analysis to `get_coaching_context()` — drift_onset_km, pace_cv, cadence_drift, heat flag
- [ ] 5.12 Bundle minimal synthetic .fit fixture in tests/fixtures/. Test full pipeline: parse → splits → drift → DB.
- [ ] 5.13 Test: zone-time per split aggregation, heat adjustment, drift with variable pace

---

# Phase 2c: Plan + Story

## 6. Runna Training Plan Integration (auto-sync from Garmin)

- [ ] 6.1 Add migration 009: `planned_workouts` table (date, workout_name, workout_type, target_distance_km, target_zone, structure JSON, plan_week, plan_day, garmin_workout_id, plan_version, sequence_ordinal, imported_at, status). Unique (date, plan_version, sequence_ordinal) — allows 2 workouts same day.
- [ ] 6.2 Implement `fit/plan.py` — `sync_planned_workouts(api, conn, month_range)`: fetch Garmin calendar items, parse Runna names → week/day/type/distance, fetch segments via `get_workout_by_id()`. Garmin Calendar API is undocumented — implement as best-effort with CSV fallback as equally robust path.
- [ ] 6.3 Integrate plan sync into `fit sync` — pull next 4 weeks after activity sync. Version on re-sync.
- [ ] 6.4 Implement `fit plan` — show next 7 days with type, distance, segments
- [ ] 6.5 Implement `fit plan import <file>` — CSV fallback, equally robust (not afterthought). `fit plan validate` dry-run.
- [ ] 6.6 Plan adherence: per-run deltas, weekly compliance (0-100%), systematic override detection, rest day compliance
- [ ] 6.7 Readiness gate: recommend swap when readiness < 30 and planned = quality session
- [ ] 6.8 Dashboard: plan adherence as mirrored bar chart (planned vs actual) with own visual identity — NOT overlaid on run timeline. Weekly compliance percentage card.
- [ ] 6.9 Coaching context: weekly compliance, rest compliance, override detection, next planned workout
- [ ] 6.10 Test: Garmin calendar parsing, Runna name extraction, plan sync, CSV fallback, adherence, override

## 7. Run Story + Periodization

- [ ] 7.1 Implement Run Story narrative — synthesize splits + correlations + checkin + weather for most recent long run
- [ ] 7.2 Implement periodization feedback loop — detect "Phase 1 objectives met, suggest advancing" or "struggling, suggest extending." Include deload week detection (from 4.9). Include taper model for final 2-3 weeks.
- [ ] 7.3 Heat acclimatization tracker — temperature-adjusted efficiency, project race day conditions
- [ ] 7.4 Add race-day pacing strategy: translate prediction into target splits per 5km, HR ceiling per segment, fueling timing. Display in Race Prediction section.
- [ ] 7.5 Test: Run Story, periodization logic (phase advance/extend/deload), heat projection, pacing strategy

## 8. Dashboard Improvements + Documentation

- [ ] 8.1 Chart readability fixes (15 items from viz review):
  - Sleep chart: change Deep to `rgba(14,165,233,0.7)` (bright blue), Light to `rgba(148,163,184,0.25)` (visible gray) — currently near-invisible on dark bg
  - Readiness combo: move HRV to y1 axis (currently overlaps bars), change HRV color to `#a78bfa`, widen RHR axis range to 40-85 (currently clips at 45-75)
  - Efficiency "All runs": increase to `Z3+"50"` opacity or replace with faint dots — currently invisible at 12% opacity
  - Training load: default zoom to 3mo (not all), add `maxBarThickness:12` — hundreds of 1px bars are unreadable
  - ACWR: change from bar to line chart with colored point markers — bars wrong for trend data
  - Stress/Battery: increase Battery fill to 20% opacity (currently 6%, invisible)
  - Cadence: set explicit y-axis 155-190 to prevent misleading auto-scale
  - Marathon prediction: add goal zone band (230-240min shaded green) alongside the line
  - RPE: change Garmin effort to gray `#94a3b8` (baseline), keep actual RPE as orange — same blue used everywhere currently
  - Volume/RunTypes: shorten week labels to "W14", add maxRotation:45 + autoSkip
  - Zone chart: add tooltip callback showing percentage (not just raw minutes)
  - Weight: reduce pointRadius to 1.5, add tension:0.3 for smoothing, consider 7-day rolling avg
- [ ] 8.2 Update README: race-anchored model, narratives, .fit analysis, Runna auto-sync, monotony/strain
- [ ] 8.3 Update CLAUDE.md: new tables, refactored architecture, new metrics, migration strategy
- [ ] 8.4 Update all specs to match implementation
- [ ] 8.5 Comprehensive tests for all Phase 2 modules (specific edge cases for statistics: zero-variance, single point, div-by-zero)
- [ ] 8.6 Verify all tests pass, ruff clean, CI green
