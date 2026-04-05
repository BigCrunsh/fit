## Context

Phase 1 delivered the complete ingest → store → analyze → visualize loop. The database has 400+ health days, 100+ activities with parallel zones and derived metrics, weekly aggregations with ACWR, and a 5-tab dashboard. Claude can query via MCP and generate coaching notes.

Phase 2 adds depth: cross-domain correlations, training plan integration, automated weight sync, per-km run analysis, and UX improvements.

## Goals / Non-Goals

**Goals:**
- Answer "why was this run slow?" with cross-domain evidence
- Close the gap between planned and executed training (Runna)
- Automate weight data ingestion
- Enable per-km analysis from .fit files
- Make `fit sync` pleasant to use

**Non-Goals:**
- Real-time streaming / live dashboards
- Multi-user support
- Training plan generation (Runna generates, we track adherence)
- Garmin watch face or widget

## Decisions

### 1. Correlation engine: precomputed + on-demand

Correlations are precomputed by `fit correlate` (or as part of sync) and stored in a `correlations` table. This avoids recomputing on every dashboard render. Claude can also compute ad-hoc correlations via SQL.

Predefined correlation pairs:
- alcohol (drinks) → next-day HRV (lag 1)
- alcohol → next-day readiness (lag 1)
- sleep_quality → readiness (lag 0)
- weight (weekly avg) → pace (weekly avg, lag 0)
- temp_at_start_c → speed_per_bpm (lag 0, same run)
- water_liters → next-day HRV (lag 1)

Uses scipy.stats.pearsonr or a simple numpy correlation. Minimum sample size: 10. Stored with coefficient, p-value, sample size, and last_computed timestamp.

### 2. Runna plan: manual import, structured storage

Runna doesn't have a public API. Plan import via CSV or JSON file that the user exports/creates from the Runna app. Format:

```csv
date,workout_type,target_distance_km,target_zone,target_pace_min_km,notes
2026-04-07,easy,5,Z2,,
2026-04-09,easy,6,Z2,,
2026-04-12,long,10,Z2,,Build gradually
```

`planned_workouts` table with: date, workout_type, target_distance_km, target_zone, target_pace_range, notes. Plan adherence computed by joining activities with planned_workouts on date.

### 3. Fitdays: Apple Health CSV with auto-detection

The Fitdays app syncs to Apple Health. Apple Health can export to CSV. The system auto-detects weight CSVs in `~/Downloads/` or a configured path during `fit sync`. More sophisticated: use the Apple Health XML export, or investigate the Fitdays API directly.

For Phase 2: start with CSV auto-detection (simplest). Weight calibration auto-updated on new measurements.

### 4. .fit files: garminconnect download + fitparse library

The `garminconnect` library can download .fit files via `api.download_activity(activity_id)`. Parse with the `fitparse` Python library. Extract per-km records from `record` messages, aggregate into splits by distance milestones.

New `activity_splits` table:
```
activity_id TEXT, split_num INTEGER, distance_km REAL, time_sec REAL,
pace_sec_per_km REAL, avg_hr INTEGER, avg_cadence REAL,
elevation_gain_m REAL, PRIMARY KEY (activity_id, split_num)
```

Cardiac drift = (avg_hr_second_half - avg_hr_first_half) / avg_hr_first_half * 100.

New dependency: `fitparse>=0.6.0`.

### 5. Sync UX: Rich progress with Live display

Replace print statements with `rich.progress.Progress` context manager. Each sync step (health, activities, SpO2, weather, enrichment, weekly_agg) as a separate task with progress bar.

For `--full`: estimate total days from date range, update progress per day fetched. Show ETA.

API rate limit: catch 429 responses, wait with countdown timer, retry.

### 6. ioBroker: simple JSON file export

Write `~/.fit/iobroker.json` after each sync with key metrics. ioBroker reads this via the JSON adapter or a custom script. No MQTT needed for v1 — file-based is simpler and sufficient.

## Risks / Trade-offs

**[Runna plan maintenance]** Plans change weekly. Manual CSV import means re-importing when Runna adjusts the plan.
→ Mitigation: Simple import command, overwrite existing future dates. Investigate Runna API for automation later.

**[.fit file download volume]** Downloading .fit files for all historical activities could be slow and hit API limits.
→ Mitigation: Only download for runs (not Move IQ), only process new activities, cache .fit files locally.

**[fitparse dependency]** Adds a new C-extension dependency.
→ Mitigation: fitparse is well-maintained, pure Python fallback available.

**[Correlation validity]** With small samples (10-20), correlations can be spurious.
→ Mitigation: Display sample size and p-value alongside coefficient. Flag low-confidence correlations.
