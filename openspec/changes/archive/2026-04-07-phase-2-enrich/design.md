## Context

Phase 1 + gaps delivered: 412 tests, 14 tables, 5-tab narrative dashboard, Spearman correlations, alerts engine, race calendar with 18 races, goal tracking CLI, `fit doctor`, Rich progress bars, enhanced `fit status`. The platform works end-to-end.

Phase 2 addresses three structural issues: (1) races and goals are disconnected, (2) the dashboard shows charts without narrative, (3) run analysis uses only per-run averages.

## Goals / Non-Goals

**Goals:**
- Race-anchored dashboard: everything radiates from the target race
- Trend narratives that answer "is it working?" in plain language
- Per-km run analysis from .fit files with cardiac drift detection
- Runna plan auto-sync from Garmin Calendar
- Training monotony/strain as leading injury predictors
- Race-day pacing strategy

**Non-Goals:**
- Apple Health integration (explicitly out of scope — FitDays CSV is better)
- Multi-race periodization (one target race at a time)
- Live/streaming dashboards
- Custom training plan generation (Runna generates, we track adherence)

## Decisions

### 1. Race as organizing anchor, goals as objectives

`race_calendar` owns the target race (next registered). `goals` become objectives linked via `race_id` FK. The Today tab orients: "Berlin Marathon: 174 days → Phase 1 of 4 → 3/4 objectives on track → prediction: 3:52."

`training_phases.goal_id` keeps the indirection (phase → goal → race). No direct training_phases.race_id needed — the link through goals is sufficient and avoids a schema change to training_phases.

**Naming convention:** The DB table remains `goals` and code uses `goals` (e.g., `_goal_progress()`, `create_goal()`). "Objectives" is used only in user-facing dashboard text and narratives (e.g., "3/4 objectives on track"). This avoids a disruptive rename while improving the user-facing language.

### 2. Consolidated migration strategy

Migration 007 **must be a Python migration** (not .sql): ONE migration for all Phase 2a schema changes — goals.race_id (via table rebuild for FK enforcement), activities.srpe, weekly_agg.monotony, weekly_agg.strain, weekly_agg.cycling_km, weekly_agg.cycling_min. Migration 008: activity_splits + fit_file columns. Migration 009: planned_workouts.

**Why Python, not SQL:** The migration runner uses `executescript()` for .sql files, which auto-commits after each statement. A table rebuild (CREATE new → INSERT INTO → DROP old → ALTER RENAME) that fails mid-way (e.g., after DROP but before RENAME) would leave the database in an unrecoverable state. Python migrations use explicit BEGIN/COMMIT/ROLLBACK, providing transactional safety for multi-step DDL.

SQLite `ALTER TABLE ADD COLUMN` doesn't enforce FKs. Use table rebuild (create new table with FK in CREATE TABLE, copy data, drop old, rename) for **both** goals.race_id **and** race_calendar.activity_id.

**activity_splits DDL** (migration 008):
```sql
CREATE TABLE activity_splits (
    activity_id TEXT NOT NULL REFERENCES activities(id),
    split_num INTEGER NOT NULL,
    distance_km REAL,
    time_sec REAL,
    pace_sec_per_km REAL,
    avg_hr REAL,
    avg_cadence REAL,
    elevation_gain_m REAL,
    avg_speed_m_s REAL,
    time_above_z2_ceiling_sec REAL,
    start_distance_m REAL,
    end_distance_m REAL,
    PRIMARY KEY (activity_id, split_num)
);
CREATE INDEX idx_splits_activity ON activity_splits(activity_id);
```
Activities table additions: `fit_file_path TEXT`, `splits_status TEXT CHECK(splits_status IN ('pending','parsed','failed','skipped'))`.

### 3. sRPE join strategy and pipeline timing

Checkin RPE is date-based (one RPE per day). If multiple runs on same day, sRPE (RPE × duration) goes to the activity with the highest training_load. This is a reasonable heuristic — the harder session is what the RPE likely reflects.

**Pipeline timing:** sRPE can only be computed when both activity and checkin exist. Checkins are user-entered (`fit checkin`), not fetched from Garmin. The sync pipeline adds an `enrich_srpe` stage after `store` that retroactively joins any unmatched checkin RPE to same-day activities. This stage also runs during `fit checkin` (after saving the checkin, check for same-day activities and compute sRPE). This ensures sRPE is computed regardless of whether checkin or sync happens first.

### 4. Trend narratives as pill badges, not paragraphs

"This Month" summary uses compact pill-style badges ("Efficiency +8%" green, "VO2max flat" gray) instead of full sentences. Avoids wall-of-text on the Today tab. Each metric has a minimum-data threshold (4+ weeks for trends). Below threshold: fallback message.

"Why" connectors mark worst/best runs on charts via Chart.js annotations — not just text narratives. Visual anchoring is stronger than prose.

### 5. Rolling correlations as sparkline small-multiples

One sparkline per correlation pair, arranged in a grid. NOT a single multi-line chart (spaghetti). Each sparkline shows 8-week trend with directional arrow. Incremental computation: only recompute pairs where new data arrived for the window.

### 6. Sync pipeline decomposition

`run_sync()` is currently 170+ lines and growing. Decompose into composable stages: fetch → enrich → store → weather → aggregate → correlate → alert → plan_sync. Each stage is independently testable. A stage failure doesn't crash the entire pipeline.

### 7. Garmin Calendar for Runna (best-effort + CSV fallback)

Runna pushes workouts to Garmin Connect calendar. The `garminconnect` library exposes `/calendar-service/year/{y}/month/{m}` with scheduled items. Workout details via `get_workout_by_id()` include structured segments.

This is an undocumented Garmin API — implement as best-effort. CSV import (`fit plan import`) is the equally-robust fallback path. Both produce the same `planned_workouts` rows.

### 8. Plan adherence as mirrored bar chart

NOT overlaid on the run timeline (which is already dense). Separate mirrored bar chart: left side = planned (faded), right side = actual (solid), color-coded match quality. Gives the plan concept its own visual identity.

### 9. .fit files opt-in with rate control

Not downloaded on every sync (too slow, hits API limits). Gated behind config toggle or `--splits` flag. Cached locally. Per-file failures don't crash sync. Backfill rate-limited: 20 per batch, 2s delay between downloads.

### 10. Dual-condition thresholds

Long run: >30% weekly volume AND ≥12km. SpO2 alert: <95% for 2+ consecutive days (not 93%). These dual conditions prevent false positives from single-condition rules at edge cases.

### 11. Training monotony/strain as leading indicators

Foster's monotony = mean(daily_loads) / stdev(daily_loads). High monotony means every training day has similar load (low variation). Strain = weekly_load × monotony. Standard thresholds: monotony > 2.0 = warning, strain > 6000 = danger zone. These flag overtraining 5-10 days before ACWR spikes — true leading indicators. Added to weekly_agg alongside ACWR.

Guard: if stdev = 0 (e.g., only one training day, or identical loads), monotony = NULL (not infinity). Do not alert on NULL.

### 12. Heat-adjusted zone flags feeding coaching

Runs at >25°C or >70% humidity flagged heat_affected. This MUST feed into `get_coaching_context()` and `generate_headline()` so coaching advice adjusts: "Last run was in 30°C heat — HR was ~1 zone higher than true effort."

### 13. Empty states for every narrative

Every narrative feature (trends, why-connectors, rolling correlations, Run Story) has a defined minimum-data threshold and a fallback message. Never render misleading results from sparse data. Never show a broken chart.

### 14. Today tab visual hierarchy

DOM order: headline → **alerts** (safety first) → race countdown → milestone celebrations → objectives → "This Month" badges → phase compliance → journey timeline. Alerts are above race countdown because safety information (return-to-run caps, injury risk, illness warnings) takes priority over motivational content. Narratives beyond 2 items collapse via progressive disclosure (<details>).

### 15. Chart readability principles

Codified in CLAUDE.md Design Principles. Key rules: no pie/donut charts, dark-bg contrast audit, trend=line/categorical=bar, semantic colors, goal zone bands, smoothed noisy data, empty states.

### 16. Return-to-run protocol replaces ACWR after gaps

When chronic load is near-zero (≥14 day training gap), ACWR divides by ~0 and is meaningless. The system switches to absolute volume caps (50% of pre-gap average, ramping 10-15%/week for 4 weeks). During this period, ACWR alerts are suppressed. This avoids both false-alarm ACWR spikes and dangerous over-ramping.

### 17. Cycling as weighted load contribution

Cycling contributes 0.3× equivalent running load (by duration) to total training load calculations (monotony, strain, weekly volume context). This prevents understating total load for athletes who cycle heavily. The 0.3 factor is configurable. Cycling does NOT factor into ACWR (which is running-specific) but DOES factor into monotony/strain (which measure total body stress).

### 18. Race prediction as range, not point estimate

Predictions always show a range (e.g., "3:48-4:05") with a confidence qualifier. Range width = base ± uncertainty factor. Uncertainty factors: weeks of data (<8 = wide), training phase (base = wider), calibration source (recent race = narrow, VO2max estimate = wide). This prevents misleading precision during early training.

### 19. Safety-first implementation sequencing

Within each phase, safety-critical features ship before narrative/visualization features. Phase 2a order: bug fixes (ACWR, alerts) → return-to-run protocol → monotony/strain → sRPE → race model → narratives. This ensures the coaching engine gives safe advice before it gives pretty advice.

### 20. sRPE pipeline as dual-trigger computation

sRPE depends on both activity (from sync) and checkin RPE (from user input). Rather than requiring a specific order, sRPE computation triggers from both paths: (1) during sync's enrich stage (check for unmatched checkins), and (2) during `fit checkin` (check for same-day activities). First trigger that finds both inputs computes sRPE.

### 21. Rolling correlation invalidation via window hash

Each rolling correlation stores `window_end_date` and `data_hash` (hash of the relevant data points in the 8-week window). On recompute, check if the hash changed — if not, skip. This is more reliable than counting data points (which misses updates to existing data).

### 22. Heat data fallback chain

Heat-adjusted zone flags use temperature/humidity from this priority chain: (1) .fit file recorded data (most accurate), (2) Open-Meteo hourly weather already stored in the activities table (always available for synced runs), (3) if neither available, skip heat flag (don't guess). Since Open-Meteo weather is already in the sync pipeline, most runs will have heat data even without .fit files.

## Risks / Trade-offs

**[Garmin Calendar API instability]** Undocumented endpoint.
→ Mitigation: CSV fallback is equally robust.

**[.fit download volume]** Backfill of 200+ files.
→ Mitigation: Rate-limited, opt-in, cached.

**[Migration complexity]** Table rebuild for FK enforcement.
→ Mitigation: Test on copy of production DB first.

**[Narrative overload]** Too many text items on Today tab.
→ Mitigation: Progressive disclosure, pill badges, collapse after 2 items.

**[Rolling correlation cost]** Recompute on every sync.
→ Mitigation: Incremental — skip pairs with unchanged data.
