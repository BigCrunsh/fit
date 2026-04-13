# CLAUDE.md — fit project

Personal fitness data platform. SQLite database, Python CLI, MCP server, HTML dashboard.

## Quick Commands

```bash
pip install -e .                      # install
pip install -e '.[analysis]'          # install with fitparse for .fit file analysis
pytest tests/ -v                      # run tests (748 tests, in-memory SQLite)
pytest tests/ -v --tb=short           # compact output
fit sync --days 7                     # daily: pull Garmin + enrich + weather + aggregate
fit sync --full && fit recompute      # init: pull all history + re-enrich
fit checkin                           # daily check-in (RPE, sleep) + sRPE computation
fit report                            # generate dashboard → ~/.fit/reports/dashboard.html
fit status                            # quick overview: countdown, phase, ACWR, last 7 days
fit doctor                            # validate pipeline health
```

## Design Decisions That Prevent Mistakes

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
- **sRPE dual-trigger** — computed from both sync and checkin paths
- **Race calendar is manual** — not auto-detected from Garmin activity names

## Zone Model

5-zone, % of max HR. Z2 ceiling at 134 bpm (not 150):

```
Z1: <60%  (<115)   Recovery
Z2: 60-70% (115-134) Easy     ← real easy ceiling
Z3: 70-80% (134-154) Moderate
Z4: 80-90% (154-173) Hard
Z5: 90-100% (173-192) Very Hard
```

Zone boundaries must come from config, never from memory or common defaults.

## Dashboard & Visualization

- **Dark background** (`#07070c`) — every dataset must be clearly visible. Annotation bands use 40+ hex opacity (e.g., `#60a5fa40`), never `0c`/`10`/`18`.
- **5-zone color palette** — Z1=#93c5fd, Z2=#60a5fa, Z3=#fbbf24, Z4=#f97316, Z5=#ef4444. Safety: emerald/amber/red.
- **3 vendored JS files** inlined into HTML: chartjs.min.js, chartjs-annotation.min.js, chartjs-date-adapter.min.js

## Testing

Tests use in-memory SQLite with full migration suite. Fixtures in `tests/conftest.py`.

## Public Repo Rules

- NEVER commit personal data: config.local.yaml, *.db, *.csv, garmin tokens
- config.yaml is a template with `${VAR}` placeholders — no real values
