# fit

Personal fitness data platform for marathon training. Tracks your running fitness across four dimensions (aerobic capacity, threshold, economy, resilience), projects it onto a target race, and tells you what to do today.

Two interfaces: a **self-contained HTML dashboard** (visual, daily glance) and **Claude AI** (deep coaching, weekly).

## Mental Model

```
   Data Sources                    Fitness Engine                  You See
   ────────────                    ──────────────                  ───────

   Garmin watch ─┐                ┌──────────────┐
   FitDays scale ─┤── fit sync ──▶│ FITNESS      │     ┌──────────────────┐
   Apple Health  ─┤               │ PROFILE      │     │ DASHBOARD        │
   fit checkin   ─┘               │              │     │                  │
                                  │ Aerobic  ██░░│────▶│ Today: easy day  │
                                  │ Threshold █░░│     │ VO2max: 49/50 ✓  │
   Target Race ──────────────────▶│ Economy  ██░░│     │ S25 in 12d: 22:30│
   Berlin Marathon sub-4:00       │ Resilience█░░│     │ Weight: 3.6kg ⚠  │
   in 173 days                    └──────┬───────┘     └────────┬─────────┘
                                         │                      │
                                         ▼                      ▼
                                  ┌──────────────┐     ┌──────────────────┐
                                  │ OBJECTIVES   │     │ CLAUDE AI        │
                                  │ (auto-derived│     │ (coaching layer) │
                                  │  from Daniels│     │                  │
                                  │  + timeline) │     │ "Focus on 3 easy │
                                  └──────────────┘     │  runs this week" │
                                                       └──────────────────┘
```

**The key idea**: Your fitness is always being measured. The target race is a lens that projects those measurements into "what do I need?" and "am I on track?" The dashboard shows the gap. Claude interprets it.

## How It Works

```
  You                    fit CLI                  Claude
  ───                    ───────                  ──────
  
  Morning routine:
  1. fit sync            Garmin → enrich →        
                         weather → DB              
  2. fit checkin         hydration, legs,          
                         sleep quality, RPE        
  3. fit report          → dashboard.html          
  4. Open dashboard      Today tab: headline,      
                         cards, journey            
                                                   
  Deep analysis:                                   
  5.                                              "Analyze my training"
                                                   → get_coaching_context()
                                                   → execute_sql_query()
                                                   → save_coaching_notes()
  6. fit report          Coach tab now shows        
                         AI coaching insights       
```

### When to use what

| Need | Use | Why |
|------|-----|-----|
| Pull new data from Garmin | `fit sync` | Automated pipeline: health + activities + weather + enrichment |
| Log how you feel today | `fit checkin` | Subjective data (legs, sleep quality, RPE) joins with Garmin biometrics |
| See your training at a glance | `fit report` → open HTML | 5-tab dashboard: Today, Training, Body, Fitness, Coach |
| Quick status check in terminal | `fit status` | Counts, calibration, data health, phase, ACWR, streak, goals |
| Deep question about your data | **Claude Chat** | Ad-hoc SQL queries, cross-referencing, pattern detection |
| Weekly coaching analysis | **Claude Chat** or `/fit-coach` | AI reads all your data, generates structured insights |
| Update physiological baseline | `fit calibrate max_hr` or `lthr` | After a race or time trial |
| Fix derived metrics after changes | `fit recompute` | Re-enriches all activities, rebuilds weekly aggregations |
| See cross-metric correlations | `fit correlate` | Spearman rank: alcohol→HRV, sleep→readiness, temp→efficiency, etc. |
| Validate data pipeline | `fit doctor` | Schema, tables, freshness, calibrations, data sources, correlations |
| View race schedule | `fit races` | Calendar with official results, Garmin times, match status |
| Track a new goal | `fit goal add` | Race, metric (VO2max, weight), or habit (consistency streak) |

### First-time setup (init)

After installation and config, run the full pipeline once to populate everything:

```bash
fit sync --full       # pull ALL Garmin history (may take a few minutes)
fit recompute         # enrich all activities with zones, efficiency, run types + rebuild weekly_agg
fit calibrate max_hr  # enter your known max HR (from a race or lab test)
fit calibrate lthr    # optional: enter LTHR if you've done a 30-min time trial
fit report --daily    # generate first dashboard + daily snapshot
open ~/.fit/reports/dashboard.html
```

Then in Claude Chat: "Use get_coaching_context and give me a full coaching analysis." Ask Claude to save the insights. Regenerate the dashboard to see the Coach tab: `fit report`.

### Daily workflow

```
DAILY (30 seconds + 1 minute):
  fit sync                ← pulls Garmin, weather, body comp, plan, recomputes everything
  open dashboard          ← 10-second glance: headline tells you what to do
  fit checkin             ← after training: RPE, legs, sleep quality (builds correlation data)

WEEKLY:
  Ask Claude for coaching ← reads fitness profile + plan, gives specific recommendations
                            Saves to Coach tab automatically

AFTER A RACE (automatic on next sync):
  fit sync                ← detects race, computes VDOT, updates projections
                            "S25 result: 22:15 → VDOT 45.5 → marathon projection: 3:55"

WHEN CHANGING GOALS (rare):
  fit target set <id>     ← switch target race, objectives recalculate
  fit races add           ← add a new race to the calendar
```

**Design principle**: `fit sync` should be the only command you need to remember. Everything else either happens automatically (dashboard generation, VDOT updates, projection recalculation) or is prompted when needed (stale coaching, missing checkin, upcoming race).

1. **`fit sync`** — run daily (or cron it). Pulls health metrics, activities, SpO2, enriches with weather, computes zones/efficiency/run types/ACWR, updates weekly aggregations. Incremental by default (last 7 days). Use `--days 30` to catch up after a break.
2. **`fit checkin`** — run after training (or in the morning). Captures hydration, alcohol, legs, eating, energy, sleep quality, RPE, weight. RPE auto-writes to today's activity. Includes an RPE scale guide.
3. **`fit report`** — generates dashboard. The **Today tab** gives you the headline ("Ready for training" or "Recovery day recommended") plus status cards, ACWR safety, phase compliance, and a journey timeline. Use `--daily` for date-stamped snapshots.
4. **Claude Chat** — for questions the dashboard can't answer. "Why was my efficiency worse this week?", "Compare my alcohol vs next-day HRV", "What should my long run target be?" Claude has full SQL access via MCP.
5. **`/fit-coach`** (in Claude Code) or ask Claude Chat — generates coaching insights that persist to the dashboard Coach tab.

## Install

```bash
cd ~/.fit
pip install -e .
fit --version
```

## Setup

```bash
# 1. Create personal config (gitignored)
cp config.yaml config.local.yaml
# Edit config.local.yaml: max_hr, location, garmin token dir

# 2. Garmin auth (one-time)
# Tokens should be in ~/.fit/garmin-tokens/
# If migrating from garmy: cp ~/.garmy/oauth*.json ~/.fit/garmin-tokens/

# 3. First sync + enrichment
fit sync --full
fit recompute

# 4. Calibrate (recommended)
fit calibrate max_hr    # enter highest HR from a recent race
fit calibrate lthr      # after a 30-min time trial (avg HR of last 20 min)

# 5. Generate dashboard
fit report
open ~/.fit/reports/dashboard.html
```

### Garmin Settings Checklist

Enable these on your Garmin watch for full data coverage:

| Setting | Path | Why |
|---------|------|-----|
| Pulse Ox | Settings → Health → Pulse Oximeter → During Sleep | SpO2 tracking |
| Lactate Threshold | Settings → Physiological Metrics → Lactate Threshold | Auto LT detection |
| HRV Status | Settings → Health → HRV Status | Needs 3 weeks for baseline |
| Training Readiness | Usually on by default | Daily readiness score |
| Move IQ | Settings → Activity Tracking → Move IQ | Auto-detect cycling/walking |

The dashboard's data health panel shows which sources are active, stale, or missing.

## CLI Commands

| Command | Description |
|---------|-------------|
| `fit sync [--days N] [--full] [--splits]` | Pull Garmin data, enrich, weather, sRPE, monotony/strain, plan sync, correlations, alerts |
| `fit checkin` | Interactive check-in: hydration, legs, eating, energy, sleep quality, RPE, weight + sRPE |
| `fit report [--daily] [--weekly]` | Generate HTML dashboard (5 tabs: Today/Training/Body/Fitness/Coach) |
| `fit status` | Race countdown, objective progress, phase position, ACWR, streak |
| `fit doctor` | Validate pipeline: schema (9 migrations), 16 tables, freshness, calibrations, correlations |
| `fit correlate` | Compute Spearman correlations (6 pairs + rolling 8-week windows with effect size filter) |
| `fit recompute [--all]` | Re-enrich all activities and rebuild weekly aggregations |
| `fit calibrate max_hr` | Calibrate max HR from race observation |
| `fit calibrate lthr` | Calibrate LTHR from 30-min time trial |
| `fit races` | Show race calendar with match status, official times, and Garmin times |
| `fit goal add` | Add a new goal interactively (race, metric, or habit type) |
| `fit goal list` | Show all active goals with progress linked to target race |
| `fit goal complete <id>` | Mark a goal as achieved |
| `fit plan` | Show next 7 days of planned workouts (auto-synced from Runna/Garmin) |
| `fit plan import <file>` | Import planned workouts from CSV (equally robust fallback) |
| `fit plan validate <file>` | Dry-run validate CSV format |
| `fit splits --backfill` | Batch download + parse .fit files for per-km splits (rate-limited) |

## Dashboard

5 story-driven tabs, each answering a different question:

| Tab | Question | Key visualizations |
|-----|----------|-------------------|
| **Today** | How am I doing? What should I do? | Headline, status cards (4-week deltas), ACWR, phase compliance, journey timeline, calibration/data health panel |
| **Training** | What have I been doing? | Weekly volume (with longest run), training load, run timeline viz, week-over-week comparison |
| **Body** | How is my body recovering? | Readiness + RHR + HRV, sleep composition, stress vs body battery, weight trend, sleep quality mismatches |
| **Fitness** | Am I getting faster? | Speed per BPM (hero chart), VO2max, zone distribution vs phase targets, cadence trend, race predictions (Riegel + VDOT), RPE predicted vs actual |
| **Coach** | What does the AI think? | Claude-generated coaching insights (via `/fit-coach` or Claude Chat) |

Uses two color palettes to avoid confusion: **safety** (green/yellow/red for "is this good?") and **intensity** (blue/amber/orange for "how hard?"). Event annotations mark races, training gaps, and phase transitions on time-series charts.

## Zone Model

Two models computed in parallel on every activity:

**Max HR model** (default, stable over time):

| Zone | % Max HR | HR (192) | Effort |
|------|----------|----------|--------|
| Z1 | < 60% | < 115 | Recovery |
| Z2 | 60-70% | 115-134 | Easy |
| Z3 | 70-80% | 134-154 | Moderate |
| Z4 | 80-90% | 154-173 | Hard |
| Z5 | 90-100% | 173-192 | Very Hard |

**LTHR model** (Friel, shifts with fitness — requires calibration):

| Zone | % LTHR | Effort |
|------|--------|--------|
| Z1 | < 85% | Recovery |
| Z2 | 85-89% | Aerobic |
| Z3 | 90-94% | Tempo |
| Z4 | 95-99% | Threshold |
| Z5 | 100%+ | VO2max |

Calibrate LTHR via a 30-min time trial or auto-extracted from races >= 10km. The system tracks calibration staleness and prompts for recalibration.

## MCP Server

Exposes `fitness.db` to Claude Chat and Claude Code (read-only).

**Data tools:** `execute_sql_query`, `get_health_summary`, `get_run_context`, `explore_database_structure`, `get_table_details`

**Coaching tools:** `check_dashboard_freshness` → `get_coaching_context` (returns zone boundaries, ACWR, phase targets, trends) → `save_coaching_notes` (atomic write to coaching.json)

The coaching context explicitly includes configured zone boundaries so Claude never defaults to incorrect HR thresholds.

**Setup:** Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "fit-mcp": {
      "command": "python3",
      "args": ["/path/to/fit/mcp/server.py"]
    }
  }
}
```

## Database

SQLite at `~/.fit/fitness.db`. 17 tables, 2 views, 13 migrations.

### How the tables relate

Three primary axes of data, joined by date and/or activity ID:

```
                          ┌─ daily_health ─┐
                          │ (one per date) │
                          └────────┬───────┘
                                   │ date
       ┌─────────────┐  date  ┌────┴────┐  date  ┌──────────┐
       │  checkins   │────────│  DATE   │────────│ weather  │
       │ (subjective │        │  axis   │        │ (daily)  │
       │   inputs)   │        └────┬────┘        └──────────┘
       └─────────────┘             │ date
                                   │
                          ┌────────┴───────────┐  date  ┌────────────────┐
                          │     activities     │────────│  body_comp     │
                          │ (one per workout)  │        │ (weight, fat%) │
                          └────┬───────────┬───┘        └────────────────┘
                               │ id        │ id              ▲
                               ▼           ▼                 │
                     ┌──────────────┐  ┌──────────────────┐  │ date
                     │ activity_    │  │ race_calendar    │  │
                     │   splits     │  │ (activity_id FK) │  │
                     │ (per-km)     │  └──────────────────┘  │
                     └──────────────┘                         │
                                                              │
       ┌─────────────────┐   date   ┌────────────────────────────────┐
       │ planned_        │──────────│       Aggregates & coaching    │
       │   workouts      │          │  weekly_agg (per ISO week)     │
       │ (Runna plans)   │          │  training_phases (date ranges) │
       └─────────────────┘          │  goals / goal_log              │
                                    │  correlations / alerts         │
                                    │  calibration (max_hr, LTHR…)   │
                                    └────────────────────────────────┘
```

Joins:
- **By date**: most cross-domain queries (e.g., "did high stress correlate with low Z2 efficiency?") join `activities` ↔ `daily_health` ↔ `checkins` ↔ `weather` on the `date` column. The `v_run_days` view materializes this join.
- **By activity ID**: `activity_splits.activity_id` and `race_calendar.activity_id` foreign-key into `activities.id`.
- **Idempotent inserts**: every table uses `INSERT … ON CONFLICT DO UPDATE` so re-syncing preserves derived metrics (e.g., `activities.run_type`, `srpe`, `hr_zone`).

### Per-table reference

#### Core measurement tables

| Table | Grain | Purpose |
|-------|-------|---------|
| **`activities`** | one per workout (id = Garmin activity ID) | The central training log. Stores every workout (running, cycling, hiking…). Garmin-sourced fields: distance, duration, pace, HR, cadence, power, vo2max, training_load, aerobic_te. Derived in pipeline: `hr_zone` (Z1-Z5), `effort_class`, `run_type` (auto-classified), `speed_per_bpm` / `speed_per_bpm_z2` (efficiency), `srpe` (RPE × duration). RPE/Feel/Compliance imported from Garmin (`directWorkoutRpe/Feel/ComplianceScore`). Race linkage: `run_type='race'` is set by `race_calendar` matching. |
| **`daily_health`** | one per date | Daily Garmin health snapshot. Resting HR (`resting_heart_rate`), sleep stages (deep/light/REM hours), HRV (`hrv_weekly_avg`, `hrv_last_night`, status), training readiness (score + level), stress (avg, max), body battery (high/low), SpO2. Read by readiness alerts, dashboard cards, ACWR overlays. |
| **`checkins`** | one per date | User-entered subjective inputs split across morning/run/evening. Morning: `sleep_quality`, `legs`, `energy`. Evening: `hydration`, `eating`, `alcohol`, `alcohol_detail`, `water_liters`. Run section currently captures `notes` only. Legacy `rpe`, `weight` columns retained for historical data — RPE is now sourced per-activity from Garmin (see `activities.rpe`); weight goes to `body_comp`. |
| **`body_comp`** | one per measurement | Body composition history: `weight`, `body_fat_pct`, `muscle_mass`, `visceral_fat`, etc. Sources: Fitdays CSV, Apple Health export, manual entry. Joined to dashboard via latest-by-date. Used for weight trend, calibration adjustments. |
| **`weather`** | one per date | Daily weather from Open-Meteo: temp, humidity, precipitation, wind, conditions. Activities additionally store `temp_at_start_c` / `humidity_at_start_pct` from the hourly endpoint. Used for heat-stress correlations and dashboard context. |
| **`activity_splits`** | one per km per activity (FK → `activities.id`) | Per-km breakdown from .fit file or Garmin splits API: pace, HR (avg/max), cadence, elevation gain/loss, zone, intensity_type, wkt_step_index. Drives the splits chart in dashboard run cards. |

#### Plans, phases, races

| Table | Grain | Purpose |
|-------|-------|---------|
| **`planned_workouts`** | one per planned session per day | Runna plan sync from Garmin Calendar + CSV import. `workout_name`, `workout_type` (easy/tempo/intervals/long/race/recovery), `target_distance_km`, `target_zone`, `structure`, `plan_week`, `plan_day`, `garmin_workout_id` (links to `activities.id` when Garmin pushes the workout). `plan_version` + `sequence_ordinal` allow multiple plans per day with stable ordering. `status` ∈ {active, completed, skipped}. Used for plan adherence cards and activity-vs-plan matching. |
| **`training_phases`** | one per phase (date range) | Phased training calendar: planned ranges, targets per phase (volume, long_run, z2_compliance, etc.), actual results, lifecycle status (planned → active → completed/revised). Drives phase-specific dashboard targets — comparisons use the **active** phase, not fixed thresholds. |
| **`race_calendar`** | one per race | Manual race registry. `name`, `date`, `distance` / `distance_km`, `target_time`, `result_time` (official, manual entry), `garmin_time` (auto-set when matched), `result_pace`, `activity_id` (FK to `activities.id`), `status` ∈ {planned, registered, completed, dns, dnf}. Sync auto-completes registered races whose date has passed and matches them by closest distance to the day's activity. |

#### Aggregates

| Table | Grain | Purpose |
|-------|-------|---------|
| **`weekly_agg`** | one per ISO week | Pre-aggregated weekly metrics: `total_km`, `runs_count`, `cycling_km`, ACWR (`acwr_acute_load_7d`, `acwr_chronic_load`), monotony, strain, zone distribution by time (`z1_minutes`…`z5_minutes`), longest run, weekly load. Recomputed after every sync via `compute_weekly_agg()`. Used for trend charts, ACWR gauge, ramp-rate alerts, streaks. |

#### Calibration & goals

| Table | Grain | Purpose |
|-------|-------|---------|
| **`calibration`** | one row per (kind, version) | Tracks the active value of physiological constants: `max_hr`, `lthr`, `weight`, `vo2max`. Each entry has `value`, `confidence`, `source` (race_extract / garmin_estimate / manual / time_trial), `effective_date`, and `notes`. Staleness tracker fires retest prompts via alerts. Zone boundaries always derive from the active calibration row, never from defaults. |
| **`goals`** | one per active objective | Current training objectives (auto-derived from target race via `derive_objectives()` — no manual CRUD). Examples: weekly_volume, long_run_km, z2_compliance, consistency_streak, vdot, etc. Each has `current_value`, `target_value`, `delta`, `status`. |
| **`goal_log`** | append-only | Event history for objectives: every change (target adjustment, milestone hit, status change) is appended with timestamp + reason. Drives the journey timeline visualization. |

#### Coaching signals

| Table | Grain | Purpose |
|-------|-------|---------|
| **`correlations`** | one row per metric pair | Spearman rank correlations between health/behavior/performance metrics (e.g., sleep_hours × next_day_speed_per_bpm). Computed by `fit correlate`. Effect size + sample size filter is applied before display so only actionable correlations surface. |
| **`alerts`** | one per fired alert | Real-time coaching alerts: volume ramp, zone compliance, adaptive readiness gate, low SpO2, deload overdue, calibration stale. Each has `kind`, `severity`, `message`, `fired_at`, `acknowledged`. Today tab shows unacknowledged alerts from the last 7 days. |

#### Infrastructure

| Table | Purpose |
|-------|---------|
| **`import_log`** | CSV import dedup. Stores `file_hash`, `row_counts`, `imported_at` to skip already-processed FitDays/Apple Health exports. |
| **`schema_version`** | Migration tracking (currently 13 applied). Auto-applied on every `get_db()` call. Each row: `version` + `name`. |

### Views

- **`v_run_days`** — activities + daily_health + checkins + weather + body_comp joined by date. Convenience view for cross-domain queries (e.g., "what was sleep + RHR + weather like the morning of each long run?").
- **`v_all_training`** — all activity types (not just running) flattened with the same shape as `v_run_days` for cross-training analysis.
