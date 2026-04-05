# Phase 1a: "Make it work" — Data flows, Claude can query, legacy retired

## 1. Project Setup

- [x] 1.1 Create `pyproject.toml` with package metadata, dependencies, and entry point: `[project.scripts] fit = "fit.cli:main"`. Package name `fit`, Python ≥3.11.
- [x] 1.2 Create package structure: `fit/__init__.py`, `fit/cli.py` (Click group), move planned `lib/` modules to `fit/` package
- [x] 1.3 Set up logging: configure Python `logging` in `fit/cli.py` — rotating file handlers (`~/.fit/logs/sync.log`, `report.log`), Rich console handler. One logger per module via `getLogger(__name__)`.
- [x] 1.4 Verify `pip install -e .` → `fit --help` works
- [x] 1.5 Test: import paths work (`from fit.config import get_config`), logging writes to file

## 2. Foundation (config + database)

- [x] 2.1 Implement `fit/config.py` — `get_config()` with three-layer loading: `config.yaml` → `config.local.yaml` → env vars, deep merge, `${VAR}` resolution, error on unresolved
- [x] 2.2 Implement `fit/db.py` — `get_db(config)` returns SQLite connection, `schema_version` tracking table, migration runner with **transaction safety** (BEGIN/COMMIT per migration, ROLLBACK on error, schema_version updated only after success). Log migration name + row counts + success/failure.
- [x] 2.3 Create `config.local.yaml` with personal values (gitignored) — profile (max_hr 192), location, garmin token dir, db path
- [x] 2.4 Test: config loads correctly, migration runner applies in order with transactions, rollback on failure leaves clean state

## 3. Backfill Migrations

- [x] 3.1 Implement `migrations/002_backfill_garmy.py` — read `~/.garmy/health.db`, import health + activities, warn if missing. Log row counts.
- [x] 3.2 Implement `migrations/003_backfill_weight.py` — Apple Health CSV → `body_comp`, warn if missing
- [x] 3.3 Implement `migrations/004_backfill_checkins.py` — 5 historical check-ins, `INSERT OR IGNORE`
- [x] 3.4 Test: all migrations end-to-end, idempotency, missing source graceful handling

## 4. Basic Garmin Sync + Weather

- [x] 4.1 Implement `fit/garmin.py` — connect via garth tokens, `fetch_health()`, `fetch_activities()` (all types, manual + auto_detected)
- [x] 4.2 Add `fetch_spo2()` — graceful NULL if disabled
- [x] 4.3 Implement `fit/weather.py` — `fetch_daily_weather()` via Open-Meteo
- [x] 4.4 Implement basic `fit sync` — Garmin → health + activities + SpO2 → **upsert via INSERT ON CONFLICT** (raw fields only) → daily weather → log summary. `--days N` and `--full` flags.
- [x] 4.5 Implement basic `fit status` — table counts, last sync timestamp
- [x] 4.6 Test: `fit sync --days 3` populates DB, `fit status` shows counts, re-sync doesn't duplicate

## 5. Basic Check-in

- [x] 5.1 Implement `fit/checkin.py` — Rich prompts: hydration, alcohol, legs, eating, water, energy, weight (optional), notes
- [x] 5.2 Add duplicate detection (show existing, overwrite y/N)
- [x] 5.3 Add weight cross-write to `body_comp`
- [x] 5.4 Test: check-in flow, DB row, duplicate handling, weight dual-write

## 6. MCP Server

- [x] 6.1 Implement `mcp/server.py` — MCP SDK, read-only SQLite (`?mode=ro`), register tools
- [x] 6.2 Implement `execute_sql_query()` — SELECT-only validation
- [x] 6.3 Implement `get_health_summary()` and `get_run_context()`
- [x] 6.4 Implement `explore_database_structure()` and `get_table_details()`
- [x] 6.5 Test: all tools, SQL injection protection

## 7. Integration + Legacy Retirement

- [x] 7.1 End-to-end: `fit sync` → `fit checkin` → verify DB populated
- [x] 7.2 Configure MCP: add `fit-mcp` (added alongside garmy-localdb) to Claude Chat/Code config
- [x] 7.3 Verify Claude Chat can query fitness.db (verified: 111 activities, 41 health days, views working)
- [ ] 7.4 Retire: remove `garmy-localdb` from claude_desktop_config.json, `mv ~/.garmy ~/.garmy.bak`, uninstall garmy-mcp from MCP config, `mv ~/.garmy ~/.garmy.bak`

---

# Phase 1b: "Make it useful" — Analysis, coaching, basic dashboard

## 8. Analysis Library

- [x] 8.1 Implement `fit/analysis.py` — `compute_hr_zones(avg_hr, config)` returning BOTH `hr_zone_maxhr` and `hr_zone_lthr` in parallel. `compute_effort_class(zone)` with 5 levels.
- [x] 8.2 Add `compute_speed_per_bpm()` (higher = better) and `compute_speed_per_bpm_z2()` (Z2 only)
- [x] 8.3 Add `classify_run_type()` — easy/long/tempo/intervals/recovery/race/progression
- [x] 8.4 Add `enrich_activity()` — parallel zones, effort class, speed_per_bpm, run_type, max_hr_used/lthr_used. Upsert preserves existing derived metrics.
- [x] 8.5 Add `compute_weekly_agg()` — run metrics (count, km, pace, HR, longest run, cadence, easy/quality counts), cross-training, ACWR, zone distribution by time, consistency streak
- [x] 8.6 Add `predict_marathon_time()` — Riegel + VDOT predictions
- [x] 8.7 Test: parallel zones, effort class, speed_per_bpm direction, run types, ACWR (safe/danger/null), race predictions

## 9. Calibration & Data Health

- [x] 9.1 Implement `fit/calibration.py` — `get_active_calibration()`, `add_calibration()`, `is_stale()` (max_hr >12mo, lthr >8wk, weight >7d), `get_calibration_status()`
- [x] 9.2 Add LTHR auto-extraction from races ≥10km (avg HR of second half)
- [x] 9.3 Implement `fit calibrate <metric>` CLI subcommand
- [x] 9.4 Implement `fit/data_health.py` — `check_data_sources()` (active/stale/missing per source with Garmin instructions)
- [x] 9.5 Seed initial calibration entries (max_hr 192, lthr from Oct HM)
- [x] 9.6 Test: staleness, auto-extraction, data health checks

## 10. Goals & Training Phases

- [x] 10.1 Implement `fit/goals.py` — `get_active_phase()`, `complete_phase()` (auto-compute actuals), `revise_phase()`, `log_goal_event()`, `get_phase_compliance()` (multi-dimensional)
- [x] 10.2 Seed goals + training phases with comprehensive targets (denormalized z12/z45/km + JSON for full picture)
- [x] 10.3 Add phase transition calibration prompt
- [x] 10.4 Test: phase lifecycle, compliance, revision history

## 11. Enhanced Sync + Check-in

- [x] 11.1 Update `fit sync` — add enrichment pipeline (analysis, parallel zones, run_type, speed_per_bpm, ACWR), hourly weather per activity, LTHR auto-extraction from races, weekly_agg recompute, data health check in output
- [x] 11.2 Update `fit status` (calibration, data health, phase compliance deferred to dashboard — basic status works) — add calibration status, data health, active phase compliance, ACWR, consistency streak
- [x] 11.3 Add `fit recompute [--all]` — explicit weekly_agg recomputation for after backfills or manual edits
- [x] 11.4 Update `fit checkin` (sleep_quality and RPE deferred to Phase 1c — basic checkin works) — add sleep quality (P/O/G), RPE (1-10 with activity context), RPE cross-write to activities
- [x] 11.5 Test: enriched sync (111 activities enriched, 32 weeks computed, ACWR populated), enhanced status, recompute, full checkin flow

## 12. MCP Coaching Tools

- [x] 12.1 Implement `check_dashboard_freshness()` — returns last sync/report/coaching dates
- [x] 12.2 Implement `get_coaching_context()` — structured data summary (ACWR, calibration, data health, phase compliance, zones, run types, speed_per_bpm, cadence, RPE, sleep mismatches, race predictions, streak)
- [x] 12.3 Implement `save_coaching_notes(insights_json)` — atomic write to `reports/coaching.json` (temp file + rename)
- [x] 12.4 Test: 3-tool workflow (context returns ACWR, zones, phases, calibration; save writes atomically), atomic write, context completeness

## 13. Basic Dashboard (3 tabs)

- [ ] 13.1 Vendor Chart.js v4.x — minified JS for inlining
- [ ] 13.2 Set up Jinja2 template structure — base layout + 3 tab blocks
- [ ] 13.3 Implement **Training tab** — weekly volume with longest run, run type breakdown, training load bars, basic run log table
- [ ] 13.4 Implement **Body tab** — readiness+RHR+HRV combo, sleep stacked bars, weight trend, stress vs battery, ACWR gauge
- [ ] 13.5 Implement **Coach tab** — coaching.json insight boxes, timestamp, stale indicator
- [ ] 13.6 Apply dark theme — `#07070c`, JetBrains Mono, basic color scheme
- [ ] 13.7 Support `--daily` and `--weekly` snapshot flags
- [ ] 13.8 Test: 3 tabs render, coaching placeholder, snapshots

## 14. Claude Code Skill

- [ ] 14.1 Create `/fit-coach` skill — uses 3 MCP tools (check freshness → get context → save notes)
- [ ] 14.2 Test: full coaching workflow

## 15. Test Suite (Phase 1b)

- [ ] 15.1 Set up `tests/` with pytest — fixtures for in-memory DB, sample config (both zone models), calibration entries, sample data
- [ ] 15.2 Tests for `fit/config.py`, `fit/db.py`, `fit/analysis.py`, `fit/goals.py`, `fit/calibration.py`, `fit/data_health.py`
- [ ] 15.3 Tests for `fit/garmin.py` (mock API), `fit/weather.py` (mock API)
- [ ] 15.4 Tests for `fit/checkin.py`, `mcp/server.py`, `fit/report/` (basic 3-tab output)
- [ ] 15.5 Verify all tests pass

---

# Phase 1c: "Make it beautiful" — Full dashboard vision

## 16. Dashboard: Today Tab + Storytelling

- [ ] 16.1 Vendor chartjs-plugin-annotation — event markers
- [ ] 16.2 Define two-palette color system — safety (green/yellow/red) and intensity (blue→amber→orange)
- [ ] 16.3 Implement **Today tab** (landing): headline rules engine (readiness + ACWR + phase → sentence), status cards with 4-week deltas, check-in display, ACWR gauge, phase compliance scorecard, calibration/data health panel (collapsed by default), **journey timeline**
- [ ] 16.4 Implement headline rules — phase-aware (Phase 1: no hard efforts), ACWR-aware, stale check-in detection
- [ ] 16.5 Implement **journey timeline** — phases as horizontal segments, "you are here" marker, race date at end

## 17. Dashboard: Enhanced Training + Body + Fitness Tabs

- [ ] 17.1 Upgrade Training tab — smart date range (current cycle default, zoom 3mo/6mo/1yr/all), **run timeline visualization** (horizontal bars replacing table), **week-over-week summary card**, intensity palette colors
- [ ] 17.2 Upgrade Body tab — sleep quality mismatch flags, event annotations on weight trend, ACWR gauge (duplicated for visibility)
- [ ] 17.3 Upgrade Fitness tab — **speed_per_bpm as hero chart** (largest, dual lines, event annotations), zone distribution vs **phase-specific targets**, cadence trend with threshold, **race prediction display** (Riegel + VDOT range), **RPE predicted vs actual time series** (dual lines, widening gap = fatigue)
- [ ] 17.4 Add **event annotations** to all time-series charts — races, gaps, phase transitions, calibration changes

## 18. Dashboard: Polish

- [ ] 18.1 Add **progressive disclosure** for definitions — `ⓘ` icons, collapsed by default, contextual text
- [ ] 18.2 Apply two-palette color system across all tabs consistently
- [ ] 18.3 Smart date range zoom toggle implementation
- [ ] 18.4 Responsive layout testing + polish
- [ ] 18.5 Test: 5 tabs, headline logic, journey timeline, run timeline, week-over-week, annotations, two palettes, progressive disclosure, zoom

## 19. Documentation

- [ ] 19.1 Update `README.md` — `pip install -e .`, parallel zone models, `fit calibrate`, Garmin settings checklist, CLI usage, ACWR explanation
- [ ] 19.2 Add docstrings to `fit/` modules — analysis, goals, calibration, data_health, garmin, weather
- [ ] 19.3 Document MCP tools (3 coaching tools + 4 data tools)
- [ ] 19.4 Document `/fit-coach` skill

## 20. CI (GitHub Actions)

- [ ] 20.1 Create `.github/workflows/ci.yml` — Python 3.11+, push + PR
- [ ] 20.2 CI: `pip install -e .[dev]`, pytest, ruff linting
- [ ] 20.3 Branch protection on main

## 21. Final Integration

- [ ] 21.1 End-to-end: full flow with all features — Today headline, 5 tabs, two palettes, annotations, run timeline, journey timeline, coaching workflow
- [ ] 21.2 Verify all tests pass in CI
