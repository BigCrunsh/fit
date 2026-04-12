## Why

The Training tab is organized around metrics (volume chart, load chart, type breakdown) rather than the runner's actual questions. The checkin restructure proved that designing around use cases — morning/run/evening mapped to natural runner moments — produces better UX. The Training tab should do the same: organize around the 4 moments a runner looks at training data.

The most frequent use case ("how's my week going?") is the worst served — there's no hero card, no plan summary, no week-level view. Meanwhile, rich per-run data (splits, elevation, cardiac drift, planned workout structure) exists in the DB but is invisible. And several computed metrics (sRPE, objectives, milestones) are stored but never surfaced in the Training tab.

### Cross-Dashboard Consistency Review

The proposal was stress-tested against the full 5-tab dashboard structure. Key decisions:

- **Objectives stay in both tabs, differentiated**: Overview shows long-term objective sparklines (weeks of history). Training shows this week's contribution as progress bars only — no duplication of sparkline data.
- **Training Load per Run removed, not moved**: Per-run load is folded into Last 7 Days cards. Readiness tab already has ACWR for aggregate load. No chart moves between tabs.
- **sRPE shown per-run, not as standalone chart**: A 90-day sRPE trend line answers a coaching question, not a runner question. sRPE per-run in Last 7 Days cards answers "did that tempo feel harder than expected?"
- **Milestones stay in Overview**: They're motivational, not analytical. At the bottom of a long Training tab nobody would scroll to them. Overview is where celebration belongs.
- **Week Impact signals must be honest**: Z2 pace delta in 7 days is noise. Use 4-week rolling comparison with direction arrows, not precise deltas. Only show when sample size ≥2 runs per period.
- **Section count stays at 6**: Same as current tab, but every section now answers a specific runner question.

## What Changes

- **Add Last 7 Days hero card**: compliance ring, volume progress bar, WoW delta, next workout — glanceable in 2 seconds
- **Add Objectives row**: 4 progress bar cards (weekly volume, long run, Z2%, consistency) with gap-to-target and traffic-light colors. Simpler than Overview's sparkline version — this week's progress only.
- **Add Last 7 Days run detail section**: per-run cards with plan comparison, per-km splits (elevation impact, workout phase overlay, pacing verdict), and 4-week rolling adaptation signals. Absorbs sRPE (per-run) and training load (per-run) from the deleted standalone charts.
- **Modify Volume chart**: default to 12 weeks instead of all-time, phase target as shaded band (box annotation matching established chart style)
- **Add multi-week Plan Adherence**: call `compute_plan_adherence()` per week for last 4 weeks with week summary headers
- **Remove Training Load per Run chart**: per-run load data folded into Last 7 Days cards — no standalone chart, no tab move
- **Absorb WoW card into This Week hero**: the standalone narrative sentence becomes a subtitle in the hero card
- **Replace flat Run Timeline with Last 7 Days**: the 12-run horizontal bar list becomes a richer per-run analysis section with plan context, splits, and adaptation signals

## Capabilities

### New Capabilities
- `training-week-summary`: Last 7 Days hero card and multi-week plan adherence summaries — answering "how's my week going?" and "am I following my plan?"
- `run-detail-analysis`: Last 7 Days per-run detail cards with split analysis, elevation impact, workout phase overlay, plan comparison, pacing verdicts, and 4-week rolling adaptation signals
- `rolling-window`: Replace ISO week boundaries with rolling 7-day windows across the entire system — hero card, objectives, WoW comparison, alerts, ACWR, CLI output, charts. Metrics and alerts SHALL NOT depend on a specific cutoff day. `weekly_agg` becomes a cache/materialization layer, not the source of truth for "this week."

### Modified Capabilities
- `dashboard`: Training tab restructured (6 sections replacing 6, but purpose-driven), Training Load chart deleted (data in per-run cards), volume chart defaults to 12 weeks with box annotation, WoW card absorbed into hero, objectives row added (simplified from Overview's sparkline version). Coach tab staleness changed from sync-based to 7-day cadence.
- `sync-ux`: `compute_weekly_agg()` and ACWR computation updated to support rolling window queries alongside ISO week materialization
- `mcp-server`: `check_dashboard_freshness()` uses 7-day coaching cadence instead of last-sync comparison. Partial-week ACWR flag removed (rolling window makes it unnecessary).

## Impact

- **`fit/report/sections/cards.py`**: New functions `_this_week_card()`, `_last_7_days()`, `_week_impact()`, `_weekly_plan_adherence()`, `_training_objectives()`. Existing `_overview_objectives()` stays in Overview only.
- **`fit/report/sections/charts.py`**: Volume chart modified (12w default, box annotation). Training Load chart removed from `_all_charts()`.
- **`fit/report/generator.py`**: New context variables wired. Existing milestones/objectives context unchanged.
- **`fit/report/templates/dashboard.html`**: Training tab section fully rewritten. Progressive disclosure JS for run detail expansion.
- **`tests/test_report.py`**: Tests for all new data functions.
- **`fit/analysis.py`**: New `compute_rolling_week()` function querying activities directly for any 7-day window. `_compute_acwr()` and `_compute_streak()` updated to use rolling windows internally while still materializing to `weekly_agg` for historical queries.
- **`fit/alerts.py`**: Remove partial-week suppression logic (no more "is it Thursday yet?" guards). Alerts fire based on rolling windows.
- **`fit/narratives.py`**: `generate_wow_sentence()` updated to accept rolling 7d data instead of ISO week pairs.
- **`fit/plan.py`**: `compute_plan_adherence()` stays calendar-week aligned (plans are authored per week).
- **`fit/cli.py`**: `fit status` output uses rolling 7d for "this week" metrics.
- **`fit/report/sections/charts.py`**: Volume chart and run type breakdown query by date range, not ISO week grouping.
- **`mcp/server.py`**: Coaching context uses rolling 7d for current-week metrics.
- **`fit/cli.py`**: Remove `fit goal add/list/complete` CLI group. `fit target set/clear/show` remains as the sole path to objectives.
- **`fit/goals.py`**: Remove manual goal CRUD functions. Keep `get_target_race()` and any functions used by `derive_objectives()`.
- **`tests/test_goals.py`**: Remove tests for manual goal CRUD. Keep tests for target race lifecycle and objective derivation.
- **`mcp/server.py`**: Remove goal references from coaching context that mention `fit goal add`.
- **Existing functions reused (not reinvented)**: `compute_plan_adherence()`, `_overview_objectives()` (referenced for targets only), `_next_workouts()`, `generate_wow_sentence()`, `compute_cardiac_drift()`, `compute_pace_variability()`.
