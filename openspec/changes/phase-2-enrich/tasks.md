# Phase 2a: Race-Anchored Model + Storytelling

## 1. Bug Fixes + Tech Debt

- [ ] 1.1 Fix `_compute_acwr` year-boundary bug — ISO week 53 handling (prev_week += 52 wrong for 53-week years)
- [ ] 1.2 Fix alert SQL: `all_runs_too_hard` query only returns 1 week due to `WHERE >= MAX()` — fix to average last 2 weeks
- [ ] 1.3 Add FK constraint: `race_calendar.activity_id REFERENCES activities(id)`
- [ ] 1.4 Add tests for garmin.py (mock Garmin API responses, test fetch_health/activities/spo2 dict mapping)
- [ ] 1.5 Add tests for sync.py (mock pipeline: enrich → upsert → weather → weekly_agg)
- [ ] 1.6 Add tests for weather.py (mock Open-Meteo responses)
- [ ] 1.7 Add retry/backoff to weather.py — `_request_with_retry` wrapper for Open-Meteo API calls (garmin.py already has retry, weather.py has none)
- [ ] 1.8 Refactor generator.py (860+ lines) — extract into `fit/report/sections/` package: engine.py, cards.py, charts.py, predictions.py
- [ ] 1.9 Extend `_auto_import_weight()` to parse body_fat_pct, muscle_mass_kg, visceral_fat from FitDays CSV (column name detection). Skip BMI, bone mass, body water, metabolic age, protein, subcutaneous fat (BIA noise).
- [ ] 1.10 Add body fat % trend line to Body tab weight chart (second y-axis, faint line)
- [ ] 1.11 Include body comp trend in `get_coaching_context()` — "fat trending down + muscle stable = healthy cut"
- [ ] 1.12 Test: all bugs verified fixed, new tests pass

## 2. Race-Anchored Data Model

- [ ] 2.1 Add migration 007: `ALTER TABLE goals ADD COLUMN race_id INTEGER REFERENCES race_calendar(id)`. Note: training_phases.goal_id keeps the indirection (phase → goal → race) — no direct training_phases.race_id needed since phases already link through the goal.
- [ ] 2.2 Link existing goals to Berlin Marathon race_calendar entry (VO2max, Weight, Streak → race_id). Update training_phases to confirm they link through goal_id to the marathon goal.
- [ ] 2.3 Refactor `_goal_progress()` to read ALL targets from goals table (remove hardcoded 51, 75, 8)
- [ ] 2.4 Add target race resolution: `get_target_race(conn)` → next registered race from race_calendar
- [ ] 2.5 Refactor Today tab: race countdown as the anchor ("Berlin Marathon: 165 days"), objectives below, phase compliance, then prediction
- [ ] 2.6 Dashboard headline: "Berlin Marathon: 165 days — Phase 2 of 4 — prediction: 3:52"
- [ ] 2.7 `fit status` shows target race countdown, objective progress, phase position
- [ ] 2.8 Test: race-anchored model, goal progress from DB, target race resolution

## 3. Trend Narratives + Story Connectors

- [ ] 3.1 Implement `fit/narratives.py` — rule-based "This Month" summary: efficiency trend (%), VO2max delta, zone compliance change, volume trend
- [ ] 3.2 Add "This Month" narrative to Today tab below headline
- [ ] 3.3 Add "why" connectors — find the N worst/best runs and their preceding checkin data: "Your 3 worst runs all followed <6h sleep nights." Include sleep mismatches from dashboard (Garmin hours vs subjective quality) as input to narrative generation.
- [ ] 3.4 Week-over-week annotated against phase targets: "Volume up 15% — Phase 1 target is ≤10%"
- [ ] 3.5 Implement rolling 8-week correlation windows — show "this correlation is getting stronger/weaker" vs static r-values
- [ ] 3.6 Race countdown narrative: "165 days to Berlin. Phase 2 of 4. 3/4 objectives on track."
- [ ] 3.7 Test: narrative generation, why-connectors, rolling correlations

## 4. Improved Coaching Metrics

- [ ] 4.1 Replace linear VDOT approximation with Daniels lookup table (or polynomial fit accurate across VO2max 35-60)
- [ ] 4.2 Fix long run threshold — use % of weekly volume (>30% of weekly km) instead of hardcoded max(15, avg×0.75)
- [ ] 4.3 Add sRPE (session RPE × duration) as validated internal load metric alongside Garmin EPOC. Store in activities, show in weekly_agg
- [ ] 4.4 Implement training monotony (stdev of daily loads per week) and strain (weekly_load × monotony) — add to weekly_agg
- [ ] 4.5 Add SpO2 illness alert: avg_spo2 < 93% for 2+ consecutive days → "Possible illness or altitude effect — consider rest." Do NOT add SpO2 to dashboard charts (mostly flat 95-98% for sea-level runners).
- [ ] 4.6 Consider adding correlation pair: SpO2 → training_readiness (validate if useful signal for this user)
- [ ] 4.7 Test: Daniels table accuracy, long run classification, sRPE, monotony/strain, SpO2 alert

---

# Phase 2b: Deep Run Analysis

## 5. .fit File Analysis

- [ ] 5.1 Add `fitparse` to optional dependencies (`[analysis]` extra)
- [ ] 5.2 Add migration 008: `activity_splits` table + `fit_file_path`, `splits_status` columns on activities. (Phase 2c planned_workouts goes in migration 009.)
- [ ] 5.3 Add `sync.download_fit_files` config toggle (default false) + `sync.max_fit_downloads: 20`
- [ ] 5.4 Implement `fit/fit_file.py` — download .fit via garminconnect (using retry), parse with fitparse, per-km splits, per-file failure handling
- [ ] 5.5 Extract per-split zone time: time_above_z2_ceiling_sec per split (fixes the "entire run = one zone" problem)
- [ ] 5.6 Implement rolling 1km cardiac drift detection — find drift_onset_km, constant-pace filter (CV > 15% = inconclusive)
- [ ] 5.7 Implement pace variability (CV across splits), cadence drift metrics
- [ ] 5.8 Implement heat-adjusted zone flags — runs at >25°C or >70% humidity flagged, zone penalty annotation. Also update `get_coaching_context()` and `generate_headline()` to mention when recent runs were heat-affected ("Last run was in 30°C heat — HR was ~1 zone higher than true effort").
- [ ] 5.9 Integrate into `fit sync --splits` + `fit splits --backfill`
- [ ] 5.10 Add split visualization to Training tab (collapsible) — dual-axis bar+line, elevation background, fade point annotation, drift gauge card
- [ ] 5.11 Add split analysis to `get_coaching_context()` — drift_onset_km, pace_cv, cadence_drift, heat flag
- [ ] 5.12 Bundle test .fit fixture, test full pipeline: parse → splits → drift → DB
- [ ] 5.13 Test: zone-time per split aggregation, heat adjustment, drift with variable pace

---

# Phase 2c: Plan + Story

## 6. Runna Training Plan Integration (auto-sync from Garmin)

- [ ] 6.1 Add migration 009: `planned_workouts` table (date, workout_name, workout_type, target_distance_km, target_zone, structure JSON, plan_week, plan_day, garmin_workout_id, plan_version, imported_at, status). Unique (date, plan_version).
- [ ] 6.2 Implement `fit/plan.py` — `sync_planned_workouts(api, conn, month_range)`: fetch Garmin calendar items, filter workout type, parse Runna names ("W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)") → extract week, day, type (Intervalle/Dauerlauf/Langer Lauf/Tempo), distance. Fetch workout segments via `get_workout_by_id()` for structured steps.
- [ ] 6.3 Integrate plan sync into `fit sync` — pull next 4 weeks of planned workouts from Garmin Calendar after activity sync. Plan versioning: mark previous entries as superseded on re-sync.
- [ ] 6.4 Implement `fit plan` — show next 7 days of planned workouts with type, distance, segments summary
- [ ] 6.5 Implement `fit plan import <file>` — CSV fallback if Garmin sync unavailable. `fit plan validate` dry-run.
- [ ] 6.6 Plan adherence: per-run deltas (planned vs actual zone/distance/pace), weekly compliance (0-100%), systematic override detection (>60% easy overridden in 3 weeks), rest day compliance
- [ ] 6.7 Connect readiness data to planned workouts: readiness gate recommends swap when readiness < 30 and planned = quality session
- [ ] 6.8 Dashboard: plan indicators on run timeline (green/red) + sparkline adherence (28 dots)
- [ ] 6.9 Coaching context: weekly compliance, rest compliance, override detection, next planned workout
- [ ] 6.10 Test: Garmin calendar parsing, Runna name extraction, plan sync, adherence, override detection

## 7. Run Story + Periodization

- [ ] 7.1 Implement Run Story narrative — synthesize splits + correlations + checkin + weather for most recent long run
- [ ] 7.2 Implement milestone/PB tracking — new longest run, best efficiency, streak milestones, VO2max peak
- [ ] 7.3 Implement periodization feedback loop — detect "Phase 1 objectives met, suggest advancing" or "struggling, suggest extending"
- [ ] 7.4 Heat acclimatization tracker — temperature-adjusted efficiency, project race day conditions
- [ ] 7.5 Test: Run Story, milestones, periodization logic, heat projection

## 8. Documentation + Tests

- [ ] 8.1 Update README: race-anchored model, narratives, .fit analysis, Runna, monotony/strain
- [ ] 8.2 Update CLAUDE.md: new tables, refactored architecture, new metrics
- [ ] 8.3 Update all specs to match implementation
- [ ] 8.4 Comprehensive tests for all Phase 2 modules
- [ ] 8.5 Verify all tests pass, ruff clean, CI green
