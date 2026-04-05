## Context

The `fit` platform is a new personal fitness data warehouse replacing a fragmented set of tools: `~/.garmy/health.db` (partial Garmin sync), `garmy-localdb` MCP server (read-only), ephemeral Claude Chat check-ins, and manual CSV exports. The repo is public — no personal data can be committed.

Currently only `migrations/001_schema.sql` and `config.yaml` (template) exist. All Python code (`lib/`, `bin/`, `mcp/`, remaining migrations) needs to be written from scratch. The schema is already designed and committed.

## Goals / Non-Goals

**Goals:**
- Complete end-to-end loop: ingest → store → analyze → visualize
- All 4 capabilities working: data ingestion, daily check-in, MCP server, AI-enriched dashboard
- Clean retirement of `~/.garmy/` with full data migration
- Cron-friendly CLI that runs unattended

**Non-Goals:**
- Correlation engine (alcohol → HRV, weight → pace) — Phase 2
- Race time predictions — Phase 2
- Training plan integration (Runna) — Phase 2
- .fit file parsing for per-km splits — Phase 2
- Web server or hosted dashboard — reports are static HTML files
- Mobile app or push notifications
- Multi-user support — this is a single-user personal system

## Decisions

### 1. Proper Python package with Click entry point

The project uses a standard Python package structure with `pyproject.toml`:

```
fit/
  __init__.py
  cli.py              # Click group: fit sync, fit checkin, fit report, fit status, fit calibrate
  config.py
  db.py
  garmin.py
  weather.py
  analysis.py
  goals.py
  calibration.py
  data_health.py
  report/             # dashboard generation
    __init__.py
    generator.py
    headline.py       # rule-based Today headline
    templates/        # Jinja2 templates
mcp/
  server.py
migrations/
  001_schema.sql
  002_backfill_garmy.py
  ...
tests/
pyproject.toml        # [project.scripts] fit = "fit.cli:main"
```

Installation: `pip install -e .` → `fit` is on PATH. No `sys.path` hacks, no `bin/` scripts, no shebang workarounds. Tests import normally (`from fit.config import get_config`).

**Alternative considered:** Scripts in `bin/` with sys.path manipulation. Rejected — this is the #1 cause of "works on my machine" issues in Python projects. A proper package is 15 minutes of setup that prevents hours of import pain.

### 2. Migration runner: numbered files with transaction safety

`db.py` maintains a `schema_version` table tracking which migrations have been applied. On `get_db()`, it scans `migrations/` for files matching `NNN_*.sql` or `NNN_*.py`, sorts by number, and runs any not yet applied.

Each migration is wrapped in a transaction:
- `conn.execute("BEGIN")` before the migration
- `conn.commit()` + update `schema_version` on success
- `conn.rollback()` on any exception → partial state impossible
- Python migrations catch exceptions and provide context: "Migration 002 failed on row 347 of daily_health_metrics: [error]"

Only `schema_version` is updated after successful commit, so a failed migration can be re-run safely.

**Alternative considered:** Alembic. Rejected — overkill for a single-user SQLite database. The numbered-file approach is transparent and debuggable.

### 3. Config loading with PyYAML + string template resolution

`lib/config.py` implements `get_config()`:
1. Load `config.yaml` with `yaml.safe_load()`
2. If `config.local.yaml` exists, deep-merge it over the template (local wins)
3. Walk the merged dict and resolve any remaining `${VAR}` placeholders from environment variables (`FIT_*` prefix not required in the placeholder — `${FIT_USER_NAME}` maps to env var `FIT_USER_NAME`)
4. If any `${VAR}` placeholder remains unresolved, raise an error

No external config library needed. The three layers (template → local → env) are sufficient and the implementation is ~50 lines.

**Alternative considered:** python-dotenv, dynaconf, or Pydantic Settings. All add dependencies for a problem that's simpler than they solve. YAML merge + env substitution is enough.

### 4. Garmin sync via garminconnect library with garth token management

`lib/garmin.py` wraps the `garminconnect` library. Auth uses garth tokens stored in `~/.garmy/` (reusing the existing token directory from the legacy setup). The sync pipeline:

```
fit sync [--days 7] [--full]
  │
  ├── 1. Connect to Garmin via garth tokens
  ├── 2. Fetch daily health summaries → upsert into daily_health
  ├── 3. Fetch activities (all types) → upsert into activities
  ├── 4. Fetch SpO2 data → update daily_health.avg_spo2
  ├── 5. Compute derived metrics for new/updated activities
  ├── 6. Fetch weather for activity dates → upsert into weather
  └── 7. Recompute weekly_agg for affected weeks
```

Upserts use `INSERT ... ON CONFLICT(pk) DO UPDATE SET` (SQLite upsert syntax, 3.24.0+). Only raw Garmin fields are listed in the `DO UPDATE SET` clause — derived fields (`hr_zone_maxhr`, `hr_zone_lthr`, `hr_zone`, `speed_per_bpm`, `speed_per_bpm_z2`, `effort_class`, `run_type`, `max_hr_used`, `lthr_used`) are never overwritten on re-sync.

**Why not INSERT OR REPLACE?** `INSERT OR REPLACE` deletes the old row and inserts a new one, which destroys any columns not in the INSERT statement — including all derived metrics. This would break backward compatibility (frozen zones) silently.

### 5. Weather at two levels: daily table + per-activity hourly

`lib/weather.py` calls the Open-Meteo API at two granularities:

1. **Daily weather** → `weather` table (date PK): temp avg/max/min, humidity, wind, precipitation, conditions. For general context.
2. **Hourly weather** → `activities.temp_at_start_c` and `activities.humidity_at_start_pct`: fetched for the specific hour and location of each activity with a known start time. Enables per-activity weather context (morning long run at 8C vs afternoon run at 22C matters for cardiac drift).

Open-Meteo's historical API supports both daily and hourly endpoints at no cost. Only fetches for dates/activities that don't already have weather data (unless `--full`). Activities without start time or location (e.g., Move IQ auto-detected) get NULL for hourly fields — daily weather still populates.

**Alternative considered:** OpenWeatherMap. Rejected because it requires an API key and has rate limits. Open-Meteo is free and sufficient for both daily and hourly data.

### 6. Parallel zone models: both max HR and LTHR computed on every activity

Both zone models are computed in parallel and stored on each activity:
- `hr_zone_maxhr`: always computed (max HR is required config)
- `hr_zone_lthr`: computed when a valid LTHR calibration exists, NULL otherwise
- `hr_zone`: alias for the preferred model per config (used in queries and dashboard)

This avoids a "pick one" tradeoff. Max HR zones are stable (good for absolute comparisons over time). LTHR zones shift with fitness (good for training prescription — "easy" gets faster as LTHR improves). The dashboard can show either or both.

Both models produce 5 zones with 5 effort classes: Recovery (Z1), Easy (Z2), Moderate (Z3), Hard (Z4), Very Hard (Z5). The 5-level effort class replaces the previous 3-level mapping because Z4 (threshold, sustainable 40-60 min) and Z5 (VO2max, sustainable 3-5 min) are fundamentally different training stimuli.

### 7. Calibration tracking with active test prompts

A `calibration` table tracks when key physiological inputs were last validated and how. Each entry: metric, value, method, confidence, date, optional source activity.

Staleness thresholds trigger prompts in `fit status` and the dashboard:
- **Max HR**: stale after 12 months. Prompt to verify during next hard race.
- **LTHR**: stale after 8 weeks. Prompt to schedule 30-min TT or extract from next 10k+ race.
- **Weight**: stale after 7 days.
- **Phase transitions** trigger a calibration check prompt.

LTHR auto-extraction: when `fit sync` imports a race (run_type = 'race', >= 10km), the system computes a candidate LTHR from avg HR of the second half and offers it as a new calibration.

This creates a **calibration loop**: passive extraction from races + active prompts for time trials = LTHR stays current without requiring a lab.

### 8. Data source health check

`fit sync` and the dashboard check all data sources and Garmin settings:
- SpO2: present or "enable Pulse Ox on Garmin"
- LTHR detection: present or "enable in Garmin Physiological Metrics"
- HRV Status: present or "enable, needs 3 weeks for baseline"
- Training Readiness, Move IQ, weight freshness, check-in freshness

This turns the dashboard into a self-diagnosing system — it tells you what data is missing and how to fix it, rather than silently showing NULL.

### 9. Zone classification frozen at insert time (backward compatibility)

Max HR changes over time — it declines with age (~1 bpm/year) and can be revised upward after a race or lab test. If zone boundaries shift, historical activities should NOT be reclassified — a run that was "Easy" at the time should stay "Easy" in the data.

Each activity stores `max_hr_used` — the max HR config value when zones were computed. On upsert (`fit sync` re-syncing existing data), raw Garmin fields are updated but derived fields (`hr_zone`, `effort_class`, efficiency, `max_hr_used`) are preserved from the original insert. This means:

- New activities → zones computed with current max HR
- Re-synced activities → derived metrics untouched
- `fit sync --full` → safe, won't reclassify history

A future `fit recompute-zones [--from-date DATE]` command can intentionally reclassify if needed (e.g., after discovering max HR was wrong all along), but this is an explicit, auditable action.

**Alternative considered:** Store zone boundaries on each activity row. More complete but redundant — max_hr + the percentage model fully determines boundaries. Storing max_hr is sufficient and simpler.

### 10. Analysis module computes derived metrics at insert time

`lib/analysis.py` provides pure functions:
- `compute_hr_zone(avg_hr, config)` → "Z1"–"Z5" (uses max HR or LTHR model per config)
- `compute_effort_class(zone)` → "Recovery" / "Easy" / "Moderate" / "Hard" / "Very Hard" (5 levels)
- `compute_speed_per_bpm(distance_km, duration_min, avg_hr)` → float (m/min/bpm, higher = better)
- `compute_speed_per_bpm_z2(distance_km, duration_min, avg_hr, z2_range)` → float or None (Z2 HR only)
- `classify_run_type(activity, config, recent_long_run_avg)` → run type string
- `compute_weekly_agg(conn, week_str)` → dict with running metrics (including cadence, run type counts), cross-training, ACWR, zone distribution by time, consistency
- `predict_marathon_time(races, vo2max)` → dict with Riegel and VDOT predictions

**Speed per BPM** replaces the inverted "cardiac efficiency" formula. Previous: `pace / avg_hr` (lower = better, counterintuitive). New: `(m/min) / avg_hr` (higher = better, intuitive). This is a direction fix — the underlying signal is the same.

**Run type classification** auto-labels runs as easy/long/tempo/intervals/recovery/race/progression based on distance, pace patterns, HR zone, and activity name. This enables training structure analysis — coaches look at weekly run-type breakdown before anything else.

**ACWR** (Acute:Chronic Workload Ratio) = this week's total_load / avg of previous 4 weeks. Safe range 0.8-1.3. Critical for injury prevention, especially during comeback training where chronic load is very low and enthusiasm can cause dangerous spikes.

Zone distribution targets are **phase-specific** — Phase 1 (base building) targets 90% Z1-Z2, 0% Z4-Z5. Phase 3 (peak) targets 75-80% Z1-Z2, 15-20% Z4-Z5. The dashboard compares actual distribution to the active phase's targets, not a blanket 80/20.

### 11. Check-in CLI uses Rich prompts with RPE

`bin/fit-checkin` uses Rich for formatted prompts and confirmation display. Categorical fields use single-character input mapped to full values. The alcohol field parses free text: if it starts with a number, that becomes the count and the full text becomes the detail. Weight entry cross-writes to `body_comp` with `source = 'checkin'`.

New: RPE (Rate of Perceived Exertion, 1-10) captures how hard the day's workout felt. If an activity exists for today, the CLI shows the activity name and HR to help calibrate. RPE is stored in both `checkins.rpe` (daily) and `activities.rpe` (per-activity if one exists today). RPE paired with HR data enables fatigue detection: easy HR + high RPE = overtraining signal.

**Alternative considered:** Click prompts. Rejected because Rich provides better formatting (color-coded categories, emoji icons, styled confirmation) matching the dashboard aesthetic.

### 12. MCP server: thin wrapper with SQL safety and separated concerns

`mcp/server.py` uses the MCP SDK to expose tools. The SQL query tool validates that the query starts with SELECT (after stripping whitespace and comments) before executing. Results are returned as formatted text (not JSON) for Claude readability.

The server opens a read-only SQLite connection (`?mode=ro`) for database queries. Filesystem writes (coaching.json) are a separate concern handled by a dedicated tool.

The coaching workflow is split into 3 focused tools (not 1 monolithic tool):
- `get_coaching_context()` → returns structured data summary (zone compliance, ACWR, trends, RPE patterns, etc.). Claude reads this and reasons.
- `save_coaching_notes(insights_json)` → writes to `reports/coaching.json`. Called after Claude generates its analysis.
- `check_dashboard_freshness()` → returns last sync date vs last report date. Simple status check.

This gives Claude flexibility: it can call `get_coaching_context()`, reason about the data, ask follow-up questions via `execute_sql_query()`, and only then call `save_coaching_notes()` with its analysis. The monolithic approach forces a rigid flow that prevents Claude from investigating before concluding.

### 13. Dashboard: story-driven 5-tab layout with Jinja2 + Chart.js

The dashboard is restructured from 4 data-domain tabs to 5 story-driven tabs:

```
  Today     → "How am I doing, what should I do?"  (landing tab)
  Training  → "What have I been doing?"             (training structure)
  Body      → "How is my body recovering?"          (physiology)
  Fitness   → "Am I getting faster?"                (performance trends)
  Coach     → "What does the AI think?"             (deep analysis)
```

**Today is the landing tab** — it answers the most common question immediately with a rule-based headline sentence (no Claude needed), status cards, ACWR gauge, phase compliance scorecard, and a journey timeline. The user gets the "so what" before diving into charts.

**Two color palettes** prevent semantic confusion:
- **Safety palette** (green/yellow/red): evaluative signals — readiness, ACWR, compliance, staleness, RPE mismatches. "Is this good or bad?"
- **Intensity palette** (blue→amber→orange): descriptive — zone distribution, load bars, run types, HR bars. "How hard was this?" A Z4 interval shows as hot orange (hard, intentional), not red (danger).

**Event annotations** on all time-series charts (via chartjs-plugin-annotation): races, training gaps, phase transitions, calibration changes. Thin vertical lines with hover labels. This transforms data points into a narrative — a dip in VO2max becomes "100-day gap" not "unexplained decline."

**Smart date ranges** with zoom toggle: Training and Fitness tabs default to the current training cycle (from Phase 1 start or last significant gap), with 3mo/6mo/1yr/all toggle. Avoids the visual problem of 12+ months of data compressing recent trends.

**Progressive disclosure for definitions**: `ⓘ` icon next to chart titles, collapsed by default. When expanded, definitions are contextual ("Your VO2max is 49, you need ≥50 for sub-4:00") not encyclopedic.

**Run timeline** replaces the traditional table: horizontal bars where length = distance, color = intensity, with run_type label and RPE. Tells the training story at a glance.

**RPE predicted vs actual** as a dual-axis time series (not scatter): shows predicted RPE from HR zone vs actual RPE from check-in. A widening gap over time = accumulating fatigue, which is the real coaching signal.

**Week-over-week** summary card on Training tab: this week vs last week deltas.

**Journey timeline** on Today tab: horizontal bar showing all phases, current position, and race date. Emotional context — where you are in the story.

**Pipeline:**
```
  1. Query fitness.db → Python dicts/lists
  2. Compute: headline rules, 4-week deltas, zone distribution, ACWR,
     phase compliance, event annotations, week-over-week, race predictions
  3. Render Jinja2 templates (base + 5 tab blocks) with Chart.js configs
  4. Read reports/coaching.json for Coach tab (if exists)
  5. Write to reports/dashboard.html (and snapshot if --daily/--weekly)
```

Jinja2 + Chart.js + chartjs-plugin-annotation are vendored and inlined for offline use.

### 14. Coach Notes via Claude Chat/Code skill, not API calls

Coach Notes are generated externally by Claude (via Chat or Code), not by `fit report` itself. Two entry points, one output:

- **MCP tool** `generate_coaching_notes()`: exposed by the MCP server. Claude Chat calls this to check dashboard freshness, query the DB for coaching context, and write `reports/coaching.json`.
- **Claude Code skill** `/fit-coach`: a skill that does the same flow within Claude Code sessions.

Both write to `reports/coaching.json`:
```json
{
  "generated_at": "2026-04-05T08:30:00",
  "report_date": "2026-04-05",
  "insights": [
    {
      "type": "warning|critical|positive|info|target",
      "title": "Short title",
      "body": "Contextual analysis referencing specific numbers"
    }
  ]
}
```

The dashboard's Coach Notes tab reads this file and renders the boxes. It shows a timestamp and whether the coaching is current or stale relative to the last sync.

**Why not Claude API in the report?** This approach: (1) removes the Anthropic SDK dependency from `fit report`, (2) uses full Claude quality (not a constrained Haiku call), (3) is free via Claude subscription, (4) keeps report generation instant and cron-friendly, (5) allows Claude to ask follow-up questions or use MCP for deeper investigation before generating notes.

**Alternative considered:** Direct Claude API call in `fit report`. Rejected — adds dependency, cost, and complexity. The skill/MCP approach is simpler and produces better results because Claude has full conversational access to the DB.

### 15. Metric definitions are static HTML templates

The educational definition boxes (VO2max, cardiac efficiency, HR zones, etc.) are hardcoded in the report generator as HTML snippets. They don't change between reports — they explain concepts, not data. This avoids wasting Claude API calls on static content.

The definitions are written once in the report generator code and rendered before the dynamic charts in each tab.

### 16. Training phases and goal log for living progress tracking

Goals are static targets. Training phases capture the journey — planned phases with targets, actual results when completed, and a full log of changes. This enables:

- **Planned vs actual**: "Phase 1 targeted 80% Z2, achieved 72%"
- **Revision history**: "Phase 2 targets reduced on Jun 15 due to knee issue"
- **Narrative continuity**: The dashboard and coaching notes can reference what was planned, what happened, and why things changed

Three tables work together:
- `goals` — high-level targets (marathon sub-4:00, VO2max 51, weight 75kg)
- `training_phases` — phased milestones with JSON targets/actuals, linked to a goal
- `goal_log` — append-only event log (created, updated, phase started/completed/revised, milestone achieved, setback)

Phases are never deleted. When a plan changes, the old phase is marked `revised` and a new one is created. The `goal_log` records what changed and why, with JSON `previous_value` and `new_value` for diffs.

Phase actuals can be auto-computed from `weekly_agg` data over the phase date range when a phase is completed.

### 17. Structured logging to file + Rich console output

All modules use Python's `logging` module:
- Log files: `~/.fit/logs/sync.log`, `report.log`, `server.log` (rotating, 7 days)
- Console: Rich-formatted progress output for humans
- Levels: INFO for normal ops, DEBUG for troubleshooting, WARNING for recoverable issues, ERROR for failures
- One logger per module (`logging.getLogger(__name__)`)
- Configured in CLI entry point (`cli.py`)

Logs capture: migration progress + row counts, Garmin API calls + responses, weather fetch results, sync pipeline step timing, report generation timing, MCP tool invocations. This is ~10 lines of setup that prevents hours of debugging in the dark.

### 18. weekly_agg is materialized with explicit recompute

`weekly_agg` is a materialized table (not a view) because ACWR requires a rolling window across 4 weeks. It's recomputed during `fit sync` for affected weeks.

Risk: data changes outside sync (backfill migrations, manual edits via MCP) can make `weekly_agg` stale. Mitigation:
- `fit recompute [--all]` command for explicit full recomputation
- After backfill migrations, automatically trigger a full recompute
- `fit status` warns if the latest `weekly_agg.created_at` is older than the latest `activities.created_at`

**Alternative considered:** A SQLite view (always fresh, computed on read). Rejected because ACWR requires a correlated subquery across 4 weeks, and the view would be complex and slow. For <1000 rows the performance difference is negligible, but the query complexity matters for maintainability.

### 19. Backfill migrations are best-effort with warnings

Migrations 002 (garmy), 003 (weight CSV), and 004 (check-ins) are designed to be resilient:
- If source data doesn't exist (no `~/.garmy/health.db`, no CSV file), the migration logs a warning and completes successfully
- If partial data exists, it imports what it can
- All use `INSERT OR IGNORE` / `INSERT OR REPLACE` for idempotency

This means `fit sync` (which triggers migrations) works on a fresh install with no legacy data, as well as on a machine with the full `~/.garmy/` history.

## Risks / Trade-offs

**[Garmin API stability]** The `garminconnect` library wraps an unofficial API. It could break on Garmin changes.
→ Mitigation: Pin the library version. Sync failures are non-destructive (existing data preserved). The library is actively maintained with a community that catches breaking changes quickly.

**[garth token expiry]** Garmin auth tokens expire and require re-authentication.
→ Mitigation: Clear error message with instructions. The garth library handles token refresh automatically in most cases; manual re-auth is needed only on long gaps.

**[Coach Notes freshness]** Coaching insights can become stale if the user syncs new data but doesn't regenerate coaching.
→ Mitigation: The dashboard shows a clear stale indicator with instructions to regenerate. The MCP tool checks freshness before generating.

**[Chart.js bundle size]** Inlining Chart.js adds ~200KB to each HTML file.
→ Mitigation: Acceptable for a local file opened in a browser. Minified Chart.js is well under 300KB. Could vendor a subset, but the full library avoids issues with missing chart types.

**[Single-file HTML complexity]** A 4-tab dashboard with 10+ charts in one HTML file will be 1000+ lines.
→ Mitigation: The Python generator structures the output logically. The HTML doesn't need to be human-editable — it's generated output. Readability of the generator code matters more.

**[Open-Meteo historical data lag]** Open-Meteo historical data may have a 1-2 day delay.
→ Mitigation: Today's weather is fetched on next sync. Missing weather for the most recent day is acceptable — it's enrichment, not core data.

## Migration Plan (three sub-phases)

**Phase 1a — "Make it work" (retire legacy ASAP):**
1. Package setup (`pyproject.toml`, `pip install -e .`)
2. Config + DB (with transaction-safe migrations)
3. Backfill migrations (garmy, weight, checkins)
4. Basic Garmin sync + weather (upsert via `INSERT ON CONFLICT`)
5. Basic check-in
6. MCP server (4 data tools)
7. Legacy retirement: swap MCP config, `mv ~/.garmy ~/.garmy.bak`

**Phase 1b — "Make it useful" (analysis + basic dashboard):**
8. Analysis library (parallel zones, speed_per_bpm, run types, ACWR)
9. Calibration + data health
10. Goals + training phases
11. Enhanced sync/checkin (enrichment, RPE, sleep quality)
12. 3 coaching MCP tools (context/save/freshness)
13. Basic 3-tab dashboard + `/fit-coach` skill

**Phase 1c — "Make it beautiful" (full vision):**
14. Today tab + headline engine + journey timeline
15. Enhanced Training/Body/Fitness tabs
16. Two-palette colors, event annotations, progressive disclosure
17. CI, documentation, polish

Rollback: legacy `~/.garmy/` continues until step 7. After retirement, keep `.garmy.bak` for 30 days.

## Open Questions

- **SpO2 data availability:** Need to verify Christoph's Forerunner has Pulse Ox enabled and is collecting data. If not, the SpO2 sync code exists but produces NULLs.
- **Chart.js version:** Need to pick a specific Chart.js version to vendor. v4.x is current and supports all required chart types.
- **Garmin time-in-zone data:** The `garminconnect` library may expose per-activity HR time-in-zone breakdown (minutes per zone). If available, this is far more accurate than using average HR to assign a single zone to an entire run. Worth investigating during implementation — if available, store per-zone minutes on each activity and use those for weekly aggregation instead of the avg-HR proxy.
