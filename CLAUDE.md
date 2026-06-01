# CLAUDE.md — fit project

Personal fitness data platform. SQLite database, Python CLI, MCP server, HTML dashboard.

## Quick Commands

```bash
pip install -e .                      # install
pip install -e '.[analysis]'          # install with fitparse for .fit file analysis
pytest tests/ -v                      # run tests (905 tests, in-memory SQLite)
pytest tests/ -v --tb=short           # compact output
fit sync --days 7                     # daily: pull Garmin + enrich + weather + aggregate
fit sync --full && fit recompute      # init: pull all history + re-enrich
fit checkin                           # daily check-in (sleep, hydration, alcohol — RPE comes from Garmin)
fit backfill rpe                      # one-shot: import directWorkoutRpe/Feel/ComplianceScore from Garmin for all running activities
fit report                            # generate dashboard → ~/.fit/reports/dashboard.html
fit status                            # quick overview: countdown, phase, ACWR, last 7 days
fit doctor                            # validate pipeline health
fit mcp install                       # register MCP server with Claude Desktop / Code (needed for /fit-coach)
```

## Design Decisions That Prevent Mistakes

- **Keep the MCP and the coaching skill in sync** — `mcp/server.py` (`get_coaching_context` et al.) and `.claude/skills/fit-coach/SKILL.md` consume the same zone model, metrics, calibrations, phases, and analysis semantics. Whenever you change any of those (or rename a metric, flip the default zone model, alter a calibration/anchor rule, etc.), check whether the coaching context **and** the skill need updating too — otherwise coaching silently drifts from the dashboard. They are a contract, not independent files.
- **INSERT ON CONFLICT**, not INSERT OR REPLACE — derived metrics are preserved on re-sync
- **Rolling 7-day window, not ISO weeks** — `compute_rolling_week()` (today-6 → today). ACWR is hybrid: rolling 7d acute + ISO-week chronic. Streaks stay ISO-week.
- **Phase-specific targets** — compare against active training phase targets, not fixed 80/20
- **Zone distribution by TIME** (duration_min), not by run count
- **speed_per_bpm** (higher = better), not cardiac_efficiency (lower = better)
- **5-level effort class**: Recovery / Easy / Moderate / Hard / Very Hard
- **Prediction = conservative (upper bound)** — slowest prediction across all methods. Deliberately pessimistic.
- **Long run dual condition** — (>30% weekly AND ≥8km) OR ≥12km absolute override
- **Monotony = mean/stdev** (Foster's formula), NOT stdev alone. Strain = weekly_load × monotony
- **Objectives auto-derived only** — from target race via `derive_objectives()`. No manual CRUD.
- **Goals = "objectives" in UI** — DB table stays `goals`, user-facing text says "objectives"
- **RPE/Feel/Compliance source = Garmin** — `activities.rpe`, `activities.feel`, `activities.compliance_score` come from `summaryDTO.directWorkoutRpe/Feel/ComplianceScore` of the activity detail endpoint. Sync re-fetches the last 14 days every run; older activities are fill-NULL-only. Use `fit backfill rpe` to populate history. RPE is NOT collected via `fit checkin`.
- **sRPE source = activities.rpe** — `compute_srpe()` reads per-activity RPE directly. Triggered from sync and backfill (no longer from checkin).
- **Race calendar is manual** — not auto-detected from Garmin activity names

## Zone Model

5-zone. **Default: Friel %LTHR** (anchored to calibrated LTHR), with fall-through to %MaxHR when LTHR is missing. The textbook 70%-MaxHR Z2 ceiling (= 134 at MaxHR=192) is too strict for trained runners with high LTHR/MaxHR ratio; %LTHR with LTHR=172 gives a Z2 ceiling of 153, which matches actual upper-aerobic effort.

```
                 %LTHR (primary)     %MaxHR (diagnostic)
Z1 Recovery      <85% (<146)         <60% (<117)
Z2 Easy          85-89% (146-153)    60-70% (117-136)
Z3 Tempo         90-94% (154-161)    70-80% (137-156)
Z4 Threshold     95-99% (163-170)    80-90% (156-175)
Z5 VO2max        ≥100% (≥172)        ≥90% (≥176)
```

(Numbers above are for LTHR=172, MaxHR=195 — the active calibrations as of 2026-06-01.)

Zone boundaries must come from config (`zones_lthr` for the primary model, `zones_max_hr_pct` for the diagnostic), never from memory or common defaults. AeT-anchored Z2 ceiling is planned (`aet-anchored-zones` change) — when AeT lands, Z2 ceiling refines to AeT directly; everything Z3 and above stays LTHR-anchored.

Override the default via `profile.zone_model: max_hr` in `config.local.yaml` if you want the strict textbook model.

## Dashboard & Visualization

- **Always use the design system** — `fit/report/templates/design_system.css` is the single source of truth for colors, typography, spacing, and components. Never hardcode hex colors or styles that duplicate or contradict it.
  - Colors: use CSS variables (`var(--safe)`, `var(--z2)`, `var(--text-muted)`, etc.) in HTML. In Python/Chart.js where CSS vars aren't available, use the exact hex values defined in `:root`.
  - Components: reuse existing classes (`.card`, `.badge`, `.chart-box`, `.run-bar`, etc.) before inventing inline styles.
  - If a new color or component is needed, propose adding it to `design_system.css` first — don't inline a one-off.
- **Annotation bands** use 40+ hex opacity (e.g., `#60a5fa40`), never `0c`/`10`/`18`.
- **Consistent time x-axis** — all charts use `type: 'time'` with ISO date labels. Weekly aggregations (volume, run types) always use `unit: 'week'`. Other charts auto-select: `month` (>180d), `week` (42-180d), `day` (<42d). Profile charts share a fixed range (first phase - 2w → race + 10d). Weekly data uses ISO dates (Sunday of each week), never ISO week strings.
- **3 vendored JS files** inlined into HTML: chartjs.min.js, chartjs-annotation.min.js, chartjs-date-adapter.min.js

## Testing

Tests use in-memory SQLite with full migration suite. Fixtures in `tests/conftest.py`.

## Public Repo Rules

- NEVER commit personal data: config.local.yaml, *.db, *.csv, garmin tokens
- config.yaml is a template with `${VAR}` placeholders — no real values
