## Why

The Training tab is organized around metrics (volume chart, load chart, type breakdown) rather than the runner's actual questions. The checkin restructure proved that designing around use cases — morning/run/evening mapped to natural runner moments — produces better UX. The Training tab should do the same: organize around the 4 moments a runner looks at training data.

The most frequent use case ("how's my week going?") is the worst served — there's no hero card, no plan summary, no week-level view. Meanwhile, rich per-run data (splits, elevation, cardiac drift, planned workout structure) exists in the DB but is invisible. And several computed metrics (sRPE, objectives, milestones) are stored but never surfaced in the Training tab.

## What Changes

- **Add This Week hero card**: compliance ring, volume progress bar, WoW delta, next workout — glanceable in 2 seconds
- **Add Objectives row**: 4 cards (weekly volume, long run, Z2%, consistency) with gap-to-target progress bars and traffic-light colors
- **Add Last 7 Days run detail section**: per-run cards with plan comparison, split analysis (elevation impact, workout phase overlay, pacing verdict), and week impact summary (Z2 pace delta, efficiency change, drift trend)
- **Add sRPE trend chart**: line chart of session RPE over time with training load overlay for fatigue divergence detection
- **Add Milestones section**: move PB/streak celebration cards from Overview to Training (they're about training execution, not race overview)
- **Move Training Load per Run chart to Readiness tab**: it's physiological stress (Garmin EPOC), not training structure — belongs with ACWR and HRV
- **Absorb WoW card into This Week hero**: the standalone narrative sentence becomes a subtitle in the hero card
- **Replace flat Run Timeline with Last 7 Days**: the 12-run horizontal bar list becomes a richer per-run analysis section with plan context, splits, and adaptation signals
- **Modify Volume chart**: default to 12 weeks instead of all-time, phase target as shaded band (box annotation matching established chart style)
- **Add multi-week Plan Adherence**: call `compute_plan_adherence()` per week for last 4 weeks with week summary headers

## Capabilities

### New Capabilities
- `training-week-summary`: This Week hero card and multi-week plan adherence summaries — answering "how's my week going?" and "am I following my plan?"
- `run-detail-analysis`: Last 7 Days per-run detail cards with split analysis, elevation impact, workout phase overlay, plan comparison, pacing verdicts, and week impact adaptation signals
- `srpe-visualization`: sRPE trend chart surfacing the computed-but-invisible session RPE data alongside training load for fatigue detection

### Modified Capabilities
- `dashboard`: Training tab restructured (8 sections replacing 6), Training Load chart moved to Readiness tab, volume chart defaults to 12 weeks with box annotation, milestones moved from Overview to Training, WoW card absorbed into hero

## Impact

- **`fit/report/sections/cards.py`**: New functions `_this_week_card()`, `_last_7_days()`, `_week_impact()`, `_weekly_plan_adherence()`. Existing `_overview_objectives()` reused in Training tab.
- **`fit/report/sections/charts.py`**: New sRPE chart in `_all_charts()`. Volume chart modified (12w default, box annotation). Training Load chart unchanged but rendered in different tab.
- **`fit/report/generator.py`**: New context variables wired. Existing milestones/objectives context reused.
- **`fit/report/templates/dashboard.html`**: Training tab section fully rewritten. Training Load `<canvas>` moved to Readiness tab. Progressive disclosure JS for run detail expansion.
- **`tests/test_report.py`**: Tests for all new data functions.
- **Existing functions reused (not reinvented)**: `compute_plan_adherence()`, `_overview_objectives()`, `_next_workouts()`, `generate_wow_sentence()`, `detect_milestones()`, `compute_cardiac_drift()`, `compute_pace_variability()`.
