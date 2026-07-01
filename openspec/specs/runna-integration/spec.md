# runna-integration Specification

## Purpose
TBD — normalized from archived change deltas; update Purpose.
## Requirements
### Requirement: Auto-sync planned workouts from Garmin Calendar
The system SHALL sync planned workouts by fetching Garmin Calendar items via `/calendar-service/year/{y}/month/{m}`. Filter for workout-type items. Parse Runna naming convention ("W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)") to extract: week number, day (Mo/Di/Mi/Do/Fr/Sa/So), workout type (Dauerlauf/Tempo/Intervalle/Langer Lauf), target distance. Fetch structured segments via `get_workout_by_id()` for warmup/intervals/cooldown detail. The manual trigger is `fit plan sync-calendar` (named for what it does — pull Runna workouts from the Garmin Calendar, not re-sync activities); `fit plan sync` remains a hidden, deprecated alias that forwards to it for one release.

Garmin Calendar API is undocumented — implement as "best effort." CSV fallback (task 6.5) SHALL be equally robust, not an afterthought.

#### Scenario: Runna workout synced
- **WHEN** `fit sync` runs and Garmin Calendar has "W 2 Mi. Intervalle - 1-km-Wiederholungen (7,5 km)" on 2026-04-15
- **THEN** planned_workouts row: date=2026-04-15, workout_type=intervals, target_distance_km=7.5, plan_week=2, plan_day=Mi

#### Scenario: Garmin API unavailable
- **WHEN** Garmin Calendar returns an error
- **THEN** plan sync skipped with warning, existing planned_workouts preserved

#### Scenario: Deprecated `fit plan sync` alias still works
- **WHEN** user runs `fit plan sync` (the former subcommand name)
- **THEN** it behaves identically to `fit plan sync-calendar` and prints a one-line deprecation notice

### Requirement: Planned workouts schema with versioning
The `planned_workouts` table SHALL have columns: date, workout_name, workout_type, target_distance_km, target_zone, structure (JSON for segments), plan_week, plan_day, garmin_workout_id, plan_version, sequence_ordinal, imported_at, status. Unique constraint on (date, plan_version, sequence_ordinal) — allows multiple workouts per day.

Plan versioning: on re-sync, mark previous entries as superseded (not deleted).

#### Scenario: Multiple workouts same day
- **WHEN** Runna schedules morning easy run + evening strength on same date
- **THEN** two rows with different sequence_ordinal values

#### Scenario: Plan re-sync
- **WHEN** Runna updates the plan and fit sync runs again
- **THEN** old plan rows marked superseded, new rows inserted with incremented plan_version

### Requirement: CSV fallback import
`fit plan import <file>` SHALL provide equally robust CSV import when Garmin sync is unavailable. `fit plan validate <file>` dry-run checks format before import.

#### Scenario: CSV import
- **WHEN** user runs `fit plan import plan.csv`
- **THEN** planned workouts loaded, versioned, logged to import_log

### Requirement: Plan adherence with compliance score
Per-run, the system SHALL compute zone delta, distance delta, pace delta between planned and actual. Weekly compliance score (0-100%) = runs completed as prescribed / total planned. Detect systematic intensity override (>60% of easy runs overridden to Z3+ in 3 weeks). Track rest day compliance.

#### Scenario: Systematic override
- **WHEN** 4 of 5 planned Dauerlauf runs executed at Z3+ in 3 weeks
- **THEN** alert: "Systematic intensity override: 80% of easy runs executed too hard"

### Requirement: Readiness-gated plan recommendations
When readiness is below the adaptive threshold and planned workout is quality session (Tempo/Intervalle), the system SHALL recommend swapping to easy. Default threshold: readiness < 40. During return-to-run period (first 4 weeks after ≥14-day gap): threshold raised to < 50. Configurable via `coaching.readiness_gate_threshold`.

#### Scenario: Low readiness + planned tempo
- **WHEN** readiness=25 and planned=Tempo (established training)
- **THEN** coaching: "Readiness 25 — swap planned Tempo to easy Dauerlauf"

#### Scenario: Return-to-run + moderate readiness
- **WHEN** return-to-run active, readiness=42, planned=Intervals
- **THEN** coaching: "Readiness 42 during return phase — swap Intervals to easy Dauerlauf"

### Requirement: Plan adherence visualization
The dashboard SHALL show a mirrored bar chart (planned vs actual) with own visual identity — NOT overlaid on run timeline. Left = planned (faded), right = actual (solid), color = match quality. Weekly compliance percentage card. Handle edge cases: missed workouts (planned bar with no actual = gray "missed" marker), unplanned workouts (actual bar with no plan = blue "extra" marker).

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
Synthesize splits + weather into a narrative paragraph for the most recent long run. Display on Coach tab. Run Story SHALL work without .fit data — degrade gracefully using per-run averages (pace, HR, efficiency) when splits are unavailable.

#### Scenario: Run Story with splits
- **WHEN** last long run was 18km with drift at km 14, preceded by 2 drinks + poor sleep
- **THEN** "Sunday's 18km: held 5:45 through km 14, then faded to 6:10. HR drifted +11%. 2 drinks Saturday, sleep quality poor. Consider staying dry before long runs."

#### Scenario: Run Story without .fit data
- **WHEN** last long run was 18km with avg pace 5:52 and avg HR 155, no .fit file, preceded by poor sleep
- **THEN** "Sunday's 18km: avg 5:52/km at HR 155 (efficiency 0.038). Sleep quality poor Saturday. Consider prioritizing sleep before long runs."

### Requirement: Periodization feedback loop
The system SHALL detect phase transition readiness: "Phase 1 objectives met (Z2 ≥80%, volume ≥25km, streak ≥4 weeks), suggest advancing to Phase 2." Also detect struggling: "Volume below target for 3+ weeks, consider extending Phase 1." Include deload week detection and taper model for final 2-3 weeks.

#### Scenario: Phase advance suggestion
- **WHEN** all Phase 1 targets met for 2+ weeks
- **THEN** coaching: "Phase 1 objectives achieved — ready to advance to Phase 2: Volume"

#### Scenario: Struggling detection
- **WHEN** weekly km below phase target for 3+ consecutive weeks
- **THEN** coaching: "Below volume target for 3 weeks — consider extending Phase 1"

### Requirement: Plan adherence tracks zone/intensity compliance
Plan adherence SHALL track not just distance compliance but also zone and intensity compliance per workout. Two new fields per adherence record: `zone_match` (boolean: did actual HR zone match planned zone?) and `intensity_override` (boolean: was a planned easy/Z2 workout executed at Z3+ intensity?).

#### Scenario: Zone match tracked
- **WHEN** planned workout is Dauerlauf (Z2) and actual run was in Z2
- **THEN** zone_match=True, intensity_override=False

#### Scenario: Intensity override detected
- **WHEN** planned workout is Dauerlauf (Z2) and actual run avg HR was in Z3
- **THEN** zone_match=False, intensity_override=True

### Requirement: Plan adherence chart colors
The plan adherence mirrored bar chart SHALL use semantic colors: green for zone match (planned and actual zones aligned), yellow for zone mismatch (different zone but not an intensity override), red for intensity override (easy plan executed as hard).

#### Scenario: Color coding in chart
- **WHEN** adherence chart renders 3 workouts: 1 zone match, 1 zone mismatch, 1 override
- **THEN** bars colored green, yellow, red respectively

### Requirement: Compliance detail table
A compliance detail table SHALL render below the plan adherence chart, showing per-workout breakdown: date, workout type, planned km vs actual km, planned HR zone vs actual HR zone, and compliance status (match/mismatch/override/missed/unplanned).

#### Scenario: Detail table content
- **WHEN** compliance detail table renders for a week with 4 planned workouts
- **THEN** table shows 4 rows with columns: date, type, planned km, actual km, HR zone, status

#### Scenario: Missed workout in table
- **WHEN** a planned Tempo workout was not executed
- **THEN** table row shows: date, "Tempo", "7.5 km", "--", "--", "missed"

