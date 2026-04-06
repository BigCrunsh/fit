# CLAUDE.md — Project Context for Claude Code

## Project

**fit** — Personal fitness data platform. SQLite database, Python CLI, MCP server for Claude, HTML dashboard.

## Quick Commands

```bash
pip install -e .              # install (first time or after pyproject.toml changes)
fit sync --days 7             # daily: pull Garmin data + enrich + weather + weekly_agg
fit sync --full && fit recompute  # init: pull all history + enrich everything
fit checkin                   # daily: interactive check-in (after training)
fit report                    # generate dashboard → ~/.fit/reports/dashboard.html
fit report --daily            # snapshot: reports/YYYY-MM-DD.html
fit status                    # quick overview: counts, calibration, data health, phase, ACWR, goals
fit doctor                    # validate pipeline: schema, tables, freshness, calibration, data sources
fit correlate                 # compute cross-domain Spearman correlations (5 pairs)
fit calibrate max_hr          # after a race: update max HR
fit calibrate lthr            # after a 30-min time trial: update LTHR
fit recompute                 # after config changes: re-enrich all activities
fit races                     # show race calendar with match status
fit goal add                  # add a goal interactively (race/metric/habit)
fit goal list                 # show active goals with progress
fit goal complete <id>        # mark a goal as achieved
```

## Architecture

```
fit/                 # Python package (pip install -e .)
  cli.py             # Click group: sync, checkin, report, status, doctor, correlate, recompute, calibrate, races, goal (add/list/complete)
  config.py          # Three-layer: config.yaml → config.local.yaml → env vars
  db.py              # SQLite + transaction-safe migration runner
  garmin.py          # Garmin Connect API via garminconnect + garth
  weather.py         # Open-Meteo daily + hourly weather
  sync.py            # Sync pipeline: fetch → enrich → upsert → weekly_agg
  analysis.py        # Zones (parallel max_hr + LTHR), speed_per_bpm, run types, ACWR, race predictions
  checkin.py         # Interactive check-in with RPE, sleep quality
  goals.py           # Training phases, phase compliance, goal log, goal CRUD
  calibration.py     # Max HR, LTHR staleness tracking + auto-extraction from races
  data_health.py     # Data source health check (what Garmin settings are missing)
  correlations.py    # Spearman rank correlation engine (5 predefined pairs, zero-dependency)
  alerts.py          # Threshold-based coaching alerts (volume ramp, zone compliance, readiness, alcohol+HRV)
  logging_config.py  # Logging setup
  report/
    generator.py     # Jinja2 + Chart.js dashboard generator (all tabs, charts, panels)
    headline.py      # Rule-based Today headline engine
    templates/       # dashboard.html Jinja2 template
    chartjs.min.js   # Vendored Chart.js 4.4.7
    chartjs-annotation.min.js  # Event annotation plugin
    chartjs-date-adapter.min.js  # Date adapter for time-scaled x-axes
mcp/
  server.py          # MCP server: 8 tools (read-only DB + coaching workflow with correlation/alert context)
migrations/          # Numbered .sql/.py migrations (001-006+)
  005_correlations_alerts.sql  # correlations, alerts, import_log tables
  006_race_calendar.sql        # race_calendar table
tests/               # pytest suite
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
- **Two-palette color system** — safety (green/yellow/red) for "is this good?" vs intensity (blue/amber/orange) for "how hard?"
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
         → upsert (ON CONFLICT — preserves derived metrics for existing)
         → Open-Meteo → daily weather + hourly per-activity weather
         → compute_weekly_agg() → ACWR, zone time distribution, consistency streak
         → auto-extract LTHR from races ≥ 10km
         → weight CSV auto-import (if weight_csv_path configured)

fit correlate → 5 predefined pairs (Spearman rank, lagged pairing)
             → upsert into correlations table (skip if data unchanged)

fit report → generator.py queries all tables
           → Jinja2 template + inlined Chart.js/annotation/date-adapter
           → self-contained HTML (dashboard.html + optional dated snapshots)

fit doctor → schema version check
           → table presence (14 expected)
           → weekly_agg freshness
           → calibration staleness
           → data source health
           → correlation count
```

## Database Tables (14)

`activities`, `daily_health`, `checkins`, `body_comp`, `weather`, `goals`, `training_phases`, `goal_log`, `calibration`, `weekly_agg`, `schema_version`, `correlations`, `alerts`, `import_log`, `race_calendar`

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
- **alerts deduplicate by date+type** — same alert won't fire twice on the same day, check `acknowledged` flag for dismissal
- **Dashboard generator expects 3 JS files** in `fit/report/`: `chartjs.min.js`, `chartjs-annotation.min.js`, `chartjs-date-adapter.min.js`

## Public Repo Rules

- NEVER commit personal data: config.local.yaml, *.db, *.csv, garmin tokens
- config.yaml is a template with `${VAR}` placeholders — no real values
- .gitignore covers all sensitive paths
