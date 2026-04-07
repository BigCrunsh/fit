## ADDED Requirements

### Requirement: Auto-sync planned workouts from Garmin Calendar
The system SHALL sync planned workouts by fetching Garmin Calendar items via `/calendar-service/year/{y}/month/{m}`. Filter for workout-type items. Parse Runna naming convention ("W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)") to extract: week number, day (Mo/Di/Mi/Do/Fr/Sa/So), workout type (Dauerlauf/Tempo/Intervalle/Langer Lauf), target distance. Fetch structured segments via `get_workout_by_id()` for warmup/intervals/cooldown detail.

Garmin Calendar API is undocumented — implement as "best effort." CSV fallback (task 6.5) SHALL be equally robust, not an afterthought.

#### Scenario: Runna workout synced
- **WHEN** `fit sync` runs and Garmin Calendar has "W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)" on 2026-04-15
- **THEN** planned_workouts row: date=2026-04-15, workout_type=intervals, target_distance_km=7.5, plan_week=2, plan_day=Mi

#### Scenario: Garmin API unavailable
- **WHEN** Garmin Calendar returns an error
- **THEN** plan sync skipped with warning, existing planned_workouts preserved

### Requirement: Planned workouts schema with versioning
`planned_workouts` table: date, workout_name, workout_type, target_distance_km, target_zone, structure (JSON for segments), plan_week, plan_day, garmin_workout_id, plan_version, sequence_ordinal, imported_at, status. Unique constraint on (date, plan_version, sequence_ordinal) — allows multiple workouts per day.

Plan versioning: on re-sync, mark previous entries as superseded (not deleted).

#### Scenario: Multiple workouts same day
- **WHEN** Runna schedules morning easy run + evening strength on same date
- **THEN** two rows with different sequence_ordinal values

#### Scenario: Plan re-sync
- **WHEN** Runna updates the plan and fit sync runs again
- **THEN** old plan rows marked superseded, new rows inserted with incremented plan_version

### Requirement: CSV fallback import
`fit plan import <file>` provides equally robust CSV import when Garmin sync is unavailable. `fit plan validate <file>` dry-run checks format before import.

#### Scenario: CSV import
- **WHEN** user runs `fit plan import plan.csv`
- **THEN** planned workouts loaded, versioned, logged to import_log

### Requirement: Plan adherence with compliance score
Per-run: compute zone delta, distance delta, pace delta between planned and actual. Weekly compliance score (0-100%) = runs completed as prescribed / total planned. Detect systematic intensity override (>60% of easy runs overridden to Z3+ in 3 weeks). Track rest day compliance.

#### Scenario: Systematic override
- **WHEN** 4 of 5 planned Dauerlauf runs executed at Z3+ in 3 weeks
- **THEN** alert: "Systematic intensity override: 80% of easy runs executed too hard"

### Requirement: Readiness-gated plan recommendations
When readiness is below the adaptive threshold and planned workout is quality session (Tempo/Intervalle), recommend swapping to easy. Default threshold: readiness < 40. During return-to-run period (first 4 weeks after ≥14-day gap): threshold raised to < 50. Configurable via `coaching.readiness_gate_threshold`.

#### Scenario: Low readiness + planned tempo
- **WHEN** readiness=25 and planned=Tempo (established training)
- **THEN** coaching: "Readiness 25 — swap planned Tempo to easy Dauerlauf"

#### Scenario: Return-to-run + moderate readiness
- **WHEN** return-to-run active, readiness=42, planned=Intervals
- **THEN** coaching: "Readiness 42 during return phase — swap Intervals to easy Dauerlauf"

### Requirement: Plan adherence visualization
Dashboard: mirrored bar chart (planned vs actual) with own visual identity — NOT overlaid on run timeline. Left = planned (faded), right = actual (solid), color = match quality. Weekly compliance percentage card. Handle edge cases: missed workouts (planned bar with no actual = gray "missed" marker), unplanned workouts (actual bar with no plan = blue "extra" marker).

#### Scenario: Plan vs actual display
- **WHEN** week has 3 planned workouts, 2 on-plan, 1 deviated
- **THEN** mirrored bars show 3 pairs, compliance card shows "67%"

#### Scenario: Missed workout
- **WHEN** planned Tempo on Tuesday but no run recorded
- **THEN** planned bar shown with gray "missed" marker on actual side

#### Scenario: Unplanned workout
- **WHEN** Sunday long run not in plan
- **THEN** actual bar shown with blue "extra" marker on planned side

### Requirement: Run Story narrative
Synthesize splits + correlations + previous-night checkin + weather into a narrative paragraph for the most recent long run. Display on Coach tab. Run Story SHALL work without .fit data — degrade gracefully using per-run averages (pace, HR, efficiency) when splits are unavailable.

#### Scenario: Run Story with splits
- **WHEN** last long run was 18km with drift at km 14, preceded by 2 drinks + poor sleep
- **THEN** "Sunday's 18km: held 5:45 through km 14, then faded to 6:10. HR drifted +11%. 2 drinks Saturday, sleep quality poor. Consider staying dry before long runs."

#### Scenario: Run Story without .fit data
- **WHEN** last long run was 18km with avg pace 5:52 and avg HR 155, no .fit file, preceded by poor sleep
- **THEN** "Sunday's 18km: avg 5:52/km at HR 155 (efficiency 0.038). Sleep quality poor Saturday. Consider prioritizing sleep before long runs."

### Requirement: Periodization feedback loop
Detect phase transition readiness: "Phase 1 objectives met (Z2 ≥80%, volume ≥25km, streak ≥4 weeks), suggest advancing to Phase 2." Also detect struggling: "Volume below target for 3+ weeks, consider extending Phase 1." Include deload week detection and taper model for final 2-3 weeks.

#### Scenario: Phase advance suggestion
- **WHEN** all Phase 1 targets met for 2+ weeks
- **THEN** coaching: "Phase 1 objectives achieved — ready to advance to Phase 2: Volume"

#### Scenario: Struggling detection
- **WHEN** weekly km below phase target for 3+ consecutive weeks
- **THEN** coaching: "Below volume target for 3 weeks — consider extending Phase 1"
