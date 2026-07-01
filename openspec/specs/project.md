# fit — Personal Fitness Data Platform

## Overview
Goal-agnostic fitness data platform that ingests from Garmin, Fitdays, Apple Health, and weather APIs into a single SQLite database. Goals are configured, not hardcoded. Includes an alerts system, race calendar, and a 5-tab narrative HTML dashboard.

## Current Goals
- Berlin Marathon 2026 (sub-4:00, Sep 27)
- VO2max: 49 → 51
- Weight: 78.3 → 75 kg
- Consistency: 8 consecutive weeks with 3+ runs

## Architecture
- **Database**: SQLite (`fitness.db`) — single source of truth, 14+ tables
- **CLI**: `fit sync`, `fit report`, `fit status`, `fit doctor`, `fit recompute`, `fit calibrate`, `fit races`, `fit goal add/list/complete`
- **MCP Server**: exposes fitness.db to Claude Chat/Code (8 tools)
- **Dashboard**: 5-tab HTML report (Today/Training/Body/Fitness/Coach) with Chart.js + date adapter + annotation plugin
- **Alerts Engine**: threshold-based coaching alerts fired after sync
- **Config**: template `config.yaml` + gitignored `config.local.yaml`
- **Migrations**: numbered SQL/Python scripts in `migrations/` (001-006+)

## Data Sources
- Garmin Connect API (health metrics, activities, SpO2)
- Garmin Move IQ (auto-detected cycling/walking)
- Apple Health (body composition via XML Export.zip, imported on-demand with `fit import-health <path>`)
- Fitdays scale (body composition)
- Open-Meteo (weather, free API)
- Race calendar (manual registry with official results + Garmin activity matching)

## Tech Stack
- Python 3.11+
- SQLite
- Click (CLI)
- Rich (terminal UI, progress bars)
- Jinja2 (dashboard templates)
- Chart.js 4.4.7 + chartjs-plugin-annotation + chartjs-adapter-date-fns (vendored)
- garminconnect (Garmin API, with curl_cffi TLS fingerprinting to dodge Cloudflare login blocks)
- MCP SDK (Claude integration)

## Constraints
- Public repo: no personal data, tokens, or PII in committed files
- Config uses template + local override pattern
- All derived metrics computed on insert via analysis.py
- Dashboard is a single self-contained HTML file (no build step, no server)
