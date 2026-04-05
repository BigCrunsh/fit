# fit

Goal-agnostic personal fitness data platform. Ingests from Garmin, Fitdays, Apple Health, and weather APIs into a single SQLite database. Claude is the primary analysis engine via MCP.

## Install

```bash
cd ~/.fit  # or wherever you cloned this repo
pip install -e .
fit --version
```

## Setup

```bash
# 1. Create personal config (gitignored)
cp config.yaml config.local.yaml
# Edit config.local.yaml with your values: max_hr, location, etc.

# 2. Garmin auth (one-time)
# Tokens should be in ~/.fit/garmin-tokens/
# If migrating from garmy: cp ~/.garmy/oauth*.json ~/.fit/garmin-tokens/

# 3. First sync
fit sync --full     # pulls all available history
fit recompute       # enriches activities with zones, efficiency, run types

# 4. Generate dashboard
fit report
open ~/.fit/reports/dashboard.html
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `fit sync [--days N] [--full]` | Pull Garmin data, enrich with weather, compute derived metrics |
| `fit checkin` | Interactive daily check-in (hydration, legs, RPE, weight, etc.) |
| `fit report [--daily] [--weekly]` | Generate HTML dashboard (5 tabs: Today/Training/Body/Fitness/Coach) |
| `fit status` | Quick overview: data counts, last sync, goals |
| `fit recompute` | Re-enrich all activities and rebuild weekly aggregations |
| `fit calibrate max_hr` | Calibrate max heart rate from race observation |
| `fit calibrate lthr` | Calibrate lactate threshold from 30-min time trial |

## Zone Model

Standard 5-zone model based on % of max HR (aligned with Runna/Garmin):

| Zone | % Max HR | HR (192) | Effort |
|------|----------|----------|--------|
| Z1 | < 60% | < 115 | Recovery |
| Z2 | 60-70% | 115-134 | Easy |
| Z3 | 70-80% | 134-154 | Moderate |
| Z4 | 80-90% | 154-173 | Hard |
| Z5 | 90-100% | 173-192 | Very Hard |

Both max HR and LTHR (Friel) zone models are computed in parallel on every activity.

## MCP Server

The MCP server exposes `fitness.db` to Claude Chat and Claude Code.

**Tools:** `execute_sql_query`, `get_health_summary`, `get_run_context`, `explore_database_structure`, `get_table_details`, `check_dashboard_freshness`, `get_coaching_context`, `save_coaching_notes`

**Setup:** Add to Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`):
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

## Coaching

Use `/fit-coach` in Claude Code or ask Claude Chat to call `get_coaching_context()` → analyze → `save_coaching_notes()`. Insights appear in the dashboard Coach tab.

## Database

SQLite at `~/.fit/fitness.db`. 10 tables: activities, daily_health, checkins, body_comp, weather, goals, training_phases, goal_log, calibration, weekly_agg. 2 views: v_run_days, v_all_training.
