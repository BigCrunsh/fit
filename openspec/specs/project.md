# fit — Personal Fitness Data Platform

## Overview
Goal-agnostic fitness data platform that ingests from Garmin, Fitdays, Apple Health, and weather APIs into a single SQLite database. Goals are configured, not hardcoded.

## Current Goals
- Berlin Marathon 2026 (sub-4:00, Sep 27)
- VO2max: 49 → 51
- Weight: 78.3 → 75 kg

## Architecture
- **Database**: SQLite (`fitness.db`) — single source of truth
- **CLI**: `fit sync`, `fit checkin`, `fit report`, `fit status`
- **MCP Server**: exposes fitness.db to Claude Chat/Code
- **Config**: template `config.yaml` + gitignored `config.local.yaml`
- **Migrations**: numbered SQL/Python scripts in `migrations/`

## Data Sources
- Garmin Connect API (health metrics, activities, SpO2)
- Garmin Move IQ (auto-detected cycling/walking)
- Apple Health (weight export via CSV)
- Fitdays scale (body composition)
- Open-Meteo (weather, free API)

## Tech Stack
- Python 3.11+
- SQLite
- Click (CLI)
- Rich (terminal UI)
- garminconnect + garth (Garmin API)
- MCP SDK (Claude integration)

## Constraints
- Public repo: no personal data, tokens, or PII in committed files
- Config uses template + local override pattern
- All derived metrics computed on insert via analysis.py
