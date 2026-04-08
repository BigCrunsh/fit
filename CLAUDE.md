# CLAUDE.md — Project Context for Claude Code

## Project

**fit** — Personal fitness data platform. SQLite database, Python CLI, MCP server for Claude, HTML dashboard.

## Quick Commands

```bash
pip install -e .              # install (first time or after pyproject.toml changes)
pip install -e '.[analysis]'  # install with fitparse for .fit file analysis
fit sync --days 7             # daily: pull Garmin data + enrich + weather + weekly_agg + plan_sync
fit sync --full && fit recompute  # init: pull all history + enrich everything
fit sync --splits             # sync with .fit file download for per-km splits
fit checkin                   # daily: interactive check-in (after training) + sRPE computation
fit report                    # generate dashboard → ~/.fit/reports/dashboard.html
fit report --daily            # snapshot: reports/YYYY-MM-DD.html
fit status                    # quick overview: race countdown, objectives, phase, ACWR, goals
fit doctor                    # validate pipeline: schema, tables, freshness, calibration, data sources
fit correlate                 # compute cross-domain Spearman correlations (6 pairs + rolling 8-week)
fit calibrate max_hr          # after a race: update max HR
fit calibrate lthr            # after a 30-min time trial: update LTHR
fit recompute                 # after config changes: re-enrich all activities
fit races                     # show race calendar with match status
fit goal add                  # add a goal interactively (race/metric/habit)
fit goal list                 # show active goals with progress (linked to target race)
fit goal complete <id>        # mark a goal as achieved
fit plan                      # show next 7 days of planned workouts (from Runna/Garmin)
fit plan import <file>        # import planned workouts from CSV
fit plan validate <file>      # dry-run validate CSV format
fit splits --backfill         # batch download + parse .fit files (rate-limited)
```

## Architecture

```
fit/                 # Python package (pip install -e .)
  cli.py             # Click group: sync, checkin, report, status, doctor, correlate, recompute, calibrate, races, goal, plan, splits
  config.py          # Three-layer: config.yaml → config.local.yaml → env vars
  db.py              # SQLite + transaction-safe migration runner (FK disabled during Python migrations for table rebuilds)
  garmin.py          # Garmin Connect API via garminconnect + garth + retry/backoff
  weather.py         # Open-Meteo daily + hourly weather with retry/backoff
  sync.py            # Composable pipeline: fetch → enrich → store → weather → sRPE → aggregate → correlate → alert → plan_sync
  analysis.py        # Zones, speed_per_bpm, run types, ACWR (year-boundary safe), Daniels VDOT, monotony/strain, return-to-run
  checkin.py         # Interactive check-in with RPE, sleep quality + sRPE trigger
  goals.py           # Training phases, phase compliance, goal log, CRUD + get_target_race()
  calibration.py     # Max HR, LTHR staleness tracking + auto-extraction from races
  data_health.py     # Data source health check (what Garmin settings are missing)
  correlations.py    # Spearman rank correlation engine (6 pairs, rolling 8-week windows, effect size filter)
  alerts.py          # Alerts: zone compliance, volume ramp, readiness gate (adaptive), alcohol+HRV, SpO2 illness, deload overdue
  narratives.py      # Rule-based trend badges, "why" connectors, WoW context, race countdown, walk-break detection, Z2 remediation
  milestones.py      # PB detection: longest run, best efficiency, streak milestones, VO2max peak
  plan.py            # Runna plan sync (Garmin Calendar + CSV fallback), plan adherence, readiness gate, compliance scoring
  fit_file.py        # .fit file download/parse, per-km splits, cardiac drift, cadence drift, heat flags
  periodization.py   # Run Story narrative, periodization feedback loop, heat acclimatization, race-day pacing
  fitness.py         # 4-dimension fitness profile, Daniels VDOT formula, objective derivation, checkpoint enrichment
  logging_config.py  # Logging setup
  report/
    generator.py     # Thin wrapper re-exporting from sections/
    headline.py      # Race-anchored headline engine
    sections/        # Decomposed dashboard generator
      engine.py      # Main generate_dashboard() + template loading
      cards.py       # Status cards, milestone cards, alert cards
      charts.py      # All chart data generation
      predictions.py # Race prediction + pacing strategy section
    templates/       # dashboard.html Jinja2 template
    chartjs.min.js   # Vendored Chart.js 4.4.7
    chartjs-annotation.min.js  # Event annotation plugin
    chartjs-date-adapter.min.js  # Date adapter for time-scaled x-axes
mcp/
  server.py          # MCP server: 8 tools + split analysis + plan adherence in coaching context
migrations/          # Numbered .sql/.py migrations (001-009)
  001_schema.sql     # Core tables (activities, daily_health, checkins, body_comp, etc.)
  005_correlations_alerts.sql  # correlations, alerts, import_log tables
  006_race_calendar.sql        # race_calendar table
  007_phase2a_schema.py        # Python: goals.race_id FK, race_calendar FK rebuild, srpe, monotony/strain, cycling
  008_activity_splits.py       # Python: activity_splits table, fit_file_path/splits_status on activities
  009_planned_workouts.py      # Python: planned_workouts table for Runna integration
tests/               # pytest suite (500+ tests)
```

## Key Design Decisions

- **INSERT ON CONFLICT**, not INSERT OR REPLACE — derived metrics (zones, efficiency, run_type) are preserved on re-sync
- **Parallel zone models**: both max_hr and LTHR zones computed and stored on every activity
- **Frozen at insert time**: zones use max_hr_used/lthr_used from when the activity was first enriched, not current config
- **5-level effort class**: Recovery / Easy / Moderate / Hard / Very Hard (not 3-level)
- **speed_per_bpm** (higher = better), not cardiac_efficiency (lower = better) — intuitive direction
- **Zone distribution by TIME** (duration_min per activity), not by run count
- **Phase-specific targets**: dashboard compares actual zone distribution to the active training phase's targets, not a fixed 80/20
- **3 coaching MCP tools** (not 1 monolithic): check_dashboard_freshness → get_coaching_context → save_coaching_notes
- **coaching context includes zone boundaries** — Claude must never default to "HR 150 for easy" when Z2 ceiling is 134
- **Spearman correlations zero-dependency** — no scipy; custom rank + Pearson implementation in `correlations.py`
- **Alerts deduplicated** by date + type — same alert won't fire twice on the same day
- **Race calendar separate from activities** — `race_calendar` stores official results/organizer, linked to Garmin activities via `activity_id`
- **Goal CLI is a Click group** — `fit goal add/list/complete` subcommands
- **Dashboard uses 3 vendored JS files** — Chart.js + annotation plugin + date-fns adapter, all inlined into the HTML
- **Race as organizing anchor** — dashboard orients around target race countdown, objectives linked via race_id FK
- **Goals = "objectives" in UI** — DB table stays `goals`, user-facing text says "objectives"
- **Monotony = mean/stdev** (Foster's formula), NOT stdev alone. Strain = weekly_load × monotony
- **sRPE dual-trigger** — computed from both sync (check for unmatched checkins) and checkin (check for same-day activities)
- **Return-to-run protocol** — ≥14-day gap → absolute volume caps for 4 weeks, ACWR alerts suppressed
- **Adaptive readiness gate** — default <40, raised to <50 during return-to-run
- **Daniels VDOT lookup table** — interpolated, not linear approximation. Accurate across VO2max 35-60
- **Long run dual condition** — (>30% weekly AND ≥8km) OR ≥12km absolute override
- **Prediction = conservative (upper bound)** — the dashboard shows the *slowest* prediction across all sources (Riegel from each past race + VDOT from VO2max) as THE prediction. Gap is computed against this upper bound. The chart's confidence band shows the full method spread (half-width = (max-min)/2). This is deliberately pessimistic — better to be pleasantly surprised than to blow up on race day.
- **Correlation effect size filter** — n≥15 AND |r|≥0.2 before surfacing in coaching/narratives
- **Rolling correlations** — 8-week windows with data_hash invalidation, sparkline grid (not spaghetti)
- **Trend narratives as pill badges** — compact "Efficiency +8%" not paragraph text. Progressive disclosure
- **Alerts above race countdown** — safety first in Today tab visual hierarchy
- **Plan adherence as mirrored bars** — separate from run timeline, shows missed/unplanned workouts
- **.fit files opt-in** — `sync.download_fit_files` config toggle, cached, rate-limited (20/batch)
- **Heat data fallback chain** — .fit file → Open-Meteo weather → skip
- **Python migrations for table rebuilds** — executescript auto-commits, Python gets transactional safety
- **FK disabled during Python migrations** — SQLite can't DROP parent table with FK checks ON
- **5-zone color palette** — Z1=#93c5fd (light blue), Z2=#60a5fa (blue), Z3=#fbbf24 (amber), Z4=#f97316 (orange), Z5=#ef4444 (red). Safety: emerald/amber/red.
- **Fitness profile = 4 dimensions** — aerobic (VO2max/VDOT), threshold (Z2 pace), economy (speed_per_bpm), resilience (drift onset)
- **VDOT from Daniels formula** — not lookup table. `compute_vdot_from_race(distance_km, time_seconds)`. More accurate for 5K-HM. Marathon underestimates by ~2.
- **Objectives auto-derive from target race** — Daniels inverse + distance heuristics + timeline. `derive_objectives(conn, race_id)`. Achievability = current + trend × time vs required.
- **Checkpoints = fitness calibration** — pre-target races with derived target times (Riegel back-calculation). VDOT from results updates projection.
- **Target race via goals.race_id** — `fit target set <id>` updates all active goals. No is_target flag needed.
- **Coaching notes body validation** — `save_coaching_notes` rejects insights with missing/short body text (<20 chars)

## Design Principles

### Data Visualization

- **No pie or donut charts. Ever.** They are the worst chart type for comparison. Use bars, lines, or small multiples instead.
- **Dark background readability**: every dataset must be clearly visible against `#07070c`. Audit any color below 30% opacity — if you can't see it on a dark screen, increase it.
- **One chart, one story**: if a chart has 3+ datasets competing on mixed axes, split it. A chart should answer one question, not three.
- **Trend data = line chart**: ACWR, efficiency, cadence, weight are trends over time — use lines with point markers. Bars are for discrete/categorical data (volume per week, load per run, zone distribution).
- **Semantic color differentiation**: machine/baseline data = muted/gray. Human/subjective data = bright/warm. Safety signals = green/yellow/red. Intensity = blue/amber/orange. Never reuse the same color for unrelated datasets.
- **Show percentages alongside absolutes**: zone distribution should show % in tooltips, not just raw minutes. Goal progress should show % alongside current/target values.
- **Smooth noisy daily data**: weight, HRV — show 7-day rolling average as the primary line. Raw data as faint dots for context. Reduces visual noise without hiding information.
- **Goal zone visualization**: where a target exists (sub-4:00, Z2 ≥90%, weight ≤75kg), show it as a shaded band — not just a thin reference line. Bands are visible at a glance.
- **Readable time windows**: charts with many data points default to 3-6 months, not "all time." Ensure zoom controls work. Long labels (ISO weeks) must auto-skip or rotate.
- **Axis scaling**: never hardcode axis min/max that could clip real data. Use auto-scale with padding, or set conservative ranges that cover expected extremes.
- **Progressive disclosure for definitions**: ⓘ icons collapsed by default. Definitions reference the user's actual values, not generic text.
- **Every chart needs an empty state**: if there's insufficient data, show a clear message ("Need 4+ weeks of data") — never render a broken or misleading chart.

### Software Engineering

- **Single source of truth**: never hardcode values that exist in the database. Goal targets, zone boundaries, calibrations — always read from DB.
- **INSERT ON CONFLICT, not INSERT OR REPLACE**: preserve derived metrics on re-sync. OR REPLACE deletes the row.
- **Composable functions over monoliths**: if a function exceeds ~100 lines, split it. sync.py and generator.py are the main candidates.
- **Transaction safety**: every migration runs in an explicit transaction (BEGIN/COMMIT/ROLLBACK). SQL migrations use executescript for DDL. Python migrations use conn.execute().
- **Graceful degradation**: missing data, missing config, unavailable APIs — handle with warnings, not crashes. `fit sync` should never fail entirely because one data source is unavailable.
- **Tests for the critical path**: every data entry point (Garmin API, weather API, CSV import) needs mock-based tests. Statistical functions need edge case tests (zero variance, single point, division by zero).
- **Schema changes in one migration**: don't modify the same table in multiple migrations within one phase. Consolidate into one migration per phase.
- **External APIs are "best effort"**: Garmin and Open-Meteo APIs are undocumented and can change. Always have a fallback path. Retry with backoff on transient errors.
- **Rate limiting**: respect API rate limits. Cap downloads per sync (e.g., max 20 .fit files). Add delays between batch requests.

### Coaching Methodology

- **Zone boundaries from config, never from memory**: always use the actual Z2 ceiling from config (134 bpm), never default to common values like 150 bpm.
- **Race calendar is the source of truth for races**: activities are NOT auto-classified as races from names. Only race_calendar entries determine which activities are races.
- **Leading indicators over trailing**: training monotony/strain predict overtraining before ACWR spikes. Cardiac drift predicts aerobic ceiling before pace declines.
- **Dual conditions for thresholds**: long run = >30% weekly volume AND ≥12km. Never use just one condition — edge cases break single-condition rules.
- **Phase-specific targets**: always compare against the active training phase's targets, not generic 80/20 rules. Base building and peak training have different zone distributions.

## Zone Model

Standard 5-zone, % of max HR (default). Z2 ceiling at 134 bpm (not 150 — the old config was wrong):

```
Z1: <60%  (<115)   Recovery
Z2: 60-70% (115-134) Easy     ← THIS is the real easy ceiling
Z3: 70-80% (134-154) Moderate
Z4: 80-90% (154-173) Hard
Z5: 90-100% (173-192) Very Hard
```

## Data Flow

```
fit sync → Garmin API → health, activities, SpO2
         → enrich_activity() → parallel zones, speed_per_bpm, run_type, effort_class
         → upsert (ON CONFLICT — preserves derived metrics)
         → Open-Meteo (with retry) → daily weather + hourly per-activity weather
         → enrich_srpe() → join checkin RPE to same-day activities
         → compute_weekly_agg() → ACWR, monotony/strain, cycling_km, zone distribution, streak
         → .fit file download (opt-in) → per-km splits, cardiac drift, zone time per split
         → auto-extract LTHR from races ≥ 10km
         → weight + body comp CSV auto-import (FitDays: weight, body_fat, muscle_mass, visceral_fat)
         → plan_sync → Garmin Calendar (Runna) → planned_workouts
         → correlations → 6 pairs + rolling 8-week windows
         → alerts → zone compliance, volume ramp, readiness gate, SpO2 illness, deload overdue

fit checkin → save check-in → sRPE computation → link RPE to same-day activities

fit correlate → 6 predefined pairs (Spearman rank, lagged pairing, effect size filter)
             → rolling 8-week windows with data_hash invalidation
             → upsert into correlations table

fit report → sections/ package queries all tables
           → narratives.py → trend badges, why-connectors, race countdown, WoW, walk-break
           → milestones.py → PB detection, celebration cards
           → periodization.py → Run Story, phase advance/extend, taper, pacing strategy
           → Jinja2 template + inlined Chart.js → self-contained HTML

fit doctor → schema version check (9 migrations)
           → table presence (16 expected)
           → weekly_agg freshness
           → calibration staleness
           → data source health
           → correlation count
```

## Database Tables (16)

`activities` (+ srpe, fit_file_path, splits_status), `daily_health`, `checkins`, `body_comp`, `weather`, `goals` (+ race_id FK), `training_phases`, `goal_log`, `calibration`, `weekly_agg` (+ monotony, strain, cycling_km, cycling_min), `schema_version`, `correlations`, `alerts`, `import_log`, `race_calendar` (+ garmin_time, activity_id FK enforced), `activity_splits`, `planned_workouts`

Views: `v_run_days`, `v_all_training`

## Testing

```bash
pytest tests/ -v              # run all tests
pytest tests/ -v --tb=short   # compact output
```

Tests use in-memory SQLite with the full migration suite applied. Fixtures in `tests/conftest.py`.

## Notes

- **Config env vars** are placeholder-substitution only (`${VAR}` in YAML), not a general override layer. If `config.local.yaml` has a literal value, env vars won't override it. This is by-design.
- **Logging** uses a single `sync.log` file for all operations (the design mentioned per-module files, but the implementation uses one rotating file).

## Common Pitfalls

- **config.local.yaml is gitignored** — must be created manually per machine
- **garth tokens** in `~/.fit/garmin-tokens/` — not `~/.garmy/` (legacy, retired)
- **Pre-commit hook** uses 79 char line length, but `pyproject.toml` ruff config is 120. Use `ruff check` for the real standard.
- **MCP server** loads config from the repo root (parent of mcp/) — run from the repo directory
- **activities.hr_zone** is an alias for the preferred zone model — use `hr_zone_maxhr` or `hr_zone_lthr` for specific models
- **Weekly_agg can drift** after manual DB edits or backfill migrations — run `fit recompute` to fix
- **race_calendar is manual** — races are inserted via SQL or MCP, not auto-detected from Garmin. `activity_id` links to Garmin data after matching.
- **correlations skip recompute** when data count hasn't changed (`data_count_at_compute`) — run `fit correlate` after new data to update
- **Rolling correlations** use `data_hash` for invalidation — more reliable than count for detecting updates
- **alerts deduplicate by date+type** — same alert won't fire twice on the same day, check `acknowledged` flag for dismissal
- **Dashboard generator expects 3 JS files** in `fit/report/`: `chartjs.min.js`, `chartjs-annotation.min.js`, `chartjs-date-adapter.min.js`
- **Python migrations disable FKs** — the migration runner sets `PRAGMA foreign_keys=OFF` before BEGIN for .py migrations, re-enables after COMMIT
- **fitparse is optional** — install with `pip install 'fit[analysis]'`. `fit sync --splits` degrades gracefully without it
- **Runna plan sync is best-effort** — undocumented Garmin Calendar API. CSV import (`fit plan import`) is equally robust fallback
- **sRPE computed retroactively** — triggers from both sync pipeline and `fit checkin`
- **Monotony NULL guard** — if stdev=0 (all identical loads or 1 training day), monotony=NULL, no alert

## Public Repo Rules

- NEVER commit personal data: config.local.yaml, *.db, *.csv, garmin tokens
- config.yaml is a template with `${VAR}` placeholders — no real values
- .gitignore covers all sensitive paths
