# Phase 1 — Foundation + Full Loop

## Why

Fitness data is scattered across Garmin Connect, Apple Health, Fitdays, Claude Chat conversations, and a legacy `~/.garmy/` setup. There is no single place to ask cross-domain questions like *"How did sleep + alcohol + weather affect my run yesterday?"* — which is exactly what goal-driven training needs.

The legacy system is run-centric (misses cycling, hiking, Move IQ auto-detected activities), has no subjective data (check-ins are lost in ephemeral chat sessions), no weather context, and the MCP server is read-only with no enrichment.

Phase 1 builds the complete **ingest → store → analyze → visualize** loop end-to-end, replacing all legacy tooling with a single unified platform.

## What Changes

**New system from scratch.** A personal fitness data warehouse with two analysis interfaces: Claude via MCP (deep, ad-hoc, conversational) and an AI-enriched HTML dashboard (visual, daily, shareable).

```
  ┌──────────────┐     ┌──────────┐     ┌───────────────────┐
  │   Ingest     │     │  Store   │     │     Analyze       │
  │              │     │          │     │                   │
  │ Garmin API   │────▶│          │────▶│ Claude via MCP    │
  │ Apple Health │     │ SQLite   │     │  (conversational) │
  │ Fitdays      │     │ single   │     │                   │
  │ Open-Meteo   │     │ DB       │     │ HTML Dashboard    │
  │ fit checkin  │     │          │     │  (AI-interpreted) │
  └──────────────┘     └──────────┘     └───────────────────┘
```

Phase 1 is split into three sub-phases to manage completion risk:

**Phase 1a — "Make it work"**: Config, DB, migrations, basic Garmin sync, basic check-in, MCP server. Outcome: data flows, Claude can query, `~/.garmy/` retired. No dashboard — Claude Chat via MCP is the analysis interface.

**Phase 1b — "Make it useful"**: Analysis library (zones, efficiency, ACWR, run types, race predictions), calibration tracking, goals + training phases, enhanced sync/checkin (RPE, sleep quality), 3 coaching MCP tools, basic 3-tab dashboard (Training/Body/Coach), `/fit-coach` skill.

**Phase 1c — "Make it beautiful"**: Today tab with headline engine + journey timeline, 5-tab story-driven layout, two-palette color system, event annotations, run timeline viz, week-over-week comparison, progressive disclosure, smart date ranges.

## Capabilities

- **data-ingestion** — SQLite schema (7 tables, 2 views), three-layer config system (template → local → env), Garmin Connect sync (health metrics, activities, SpO2), Open-Meteo weather enrichment for run dates, backfill migrations from legacy garmy DB + Apple Health weight CSV, derived metrics (HR zones, cardiac efficiency, effort class), weekly aggregation, and the `fit sync` and `fit status` CLI commands.

- **daily-checkin** — Interactive `fit checkin` CLI for logging daily subjective data: hydration, alcohol (count + detail), leg freshness, eating quality, water intake, energy level, optional weight, and free-text notes. Backfill migration for historical check-ins captured in Claude Chat sessions.

- **mcp-server** — MCP server exposing `fitness.db` to Claude Chat and Claude Code as a direct replacement for `garmy-localdb`. Tools for SQL queries, health summaries, run context lookups, and schema exploration. Becomes the primary interface for deep, ad-hoc analysis.

- **dashboard** — `fit report` generates a self-contained, story-driven HTML dashboard with 5 tabs: Today (daily headline synthesis, status cards with 4-week deltas, ACWR gauge, phase compliance scorecard, journey timeline, calibration/data health), Training (weekly volume with longest run, run type breakdown, training load, run timeline visualization, week-over-week comparison), Body (readiness + RHR + HRV, sleep with quality mismatch detection, weight trend, stress vs battery), Fitness (speed-per-bpm hero chart, VO2max trend, zone distribution vs phase-specific targets, cadence trend, race predictions via Riegel + VDOT, RPE predicted vs actual), and Coach (AI-generated insights via Claude Chat/Code). Dark theme with two-palette color system (safety vs intensity), Chart.js with event annotations, smart date ranges with zoom, progressive disclosure for definitions, contextual not encyclopedic. Supports always-current, daily snapshot, and weekly rollup. Cron-friendly.

## Impact

- **Replaces** `~/.garmy/health.db`, `garmy-localdb` MCP, `garmy-sync`, manual `sync_all.py`, React artifact dashboards
- **Preserves** all historical data via backfill migrations (garmy health DB, Apple Health weight export, Claude Chat check-ins)
- **New capability**: Coach Notes generated via Claude Chat (MCP tool) or Claude Code (`/fit-coach` skill), stored in `reports/coaching.json`, displayed in dashboard
- **Public repo constraint**: config template committed, personal values in gitignored `config.local.yaml`, no PII in repo
