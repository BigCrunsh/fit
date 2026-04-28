## Follow-ups & Open Ideas

Captured 2026-04-27 after the `/opsx:verify` pass. Implementation is complete (53/53 tasks, 773/773 tests, change validates strictly). The items below are deferred work, not blockers.

## Verification Gaps

### Manual visual review of Training tab (task 9.2)
Marked done programmatically, but no human has actually opened a fresh dashboard and walked through all 6 sections. Worth a 10-minute pass:
- Hero card renders correctly when 0 runs / 0 planned workouts in window
- Objectives row renders correctly with no target race (all 4 deactivated)
- Run detail expand/collapse works in browser; splits visible when present, graceful empty state otherwise
- Plan Adherence color thresholds (green / amber <70 / red <50) trigger as expected
- Volume chart phase target band visible; gap annotations appear for >14 day breaks

### Scheduled remote audit (deferred — blocked on auth)
On 2026-04-27 I tried to schedule a one-time remote agent to re-audit the rolling-7-day surfaces in 1 week. The claude.ai/code routines API returned 401. Either authenticate and re-run `/schedule`, or run the audit manually:
- Re-confirm every "last 7 days" surface still reads from `compute_rolling_week()`, not `weekly_agg` current-ISO-week lookups
- Grep for any new `iso.weekday < 5` partial-week guards
- Run full pytest

## Spec / Implementation Divergences (now spec'd, but worth revisiting)

### Volume Trend + Run Type Mix merged
Original spec had two separate charts as Training tab sections 5 and 6. Implementation merged them into a single stacked-by-run-type bar chart (`chart-volume`) and the spec was updated to match. Reasons to revisit:
- If the stacked chart becomes hard to read (>5 active run types in a window), split back into two charts
- Run Type Mix as percentages (not absolute km) might tell a different story — currently buried in the absolute-km stacked view

### Volume chart current bar is ISO-week aligned, not rolling
Original task 6.2 prescribed `weekly_agg` for history + `compute_rolling_week()` for the rightmost bar. Implementation queries `activities` directly and groups by ISO week for all bars, including the current one — meaning the current week's bar shows partial data (Mon-today) until Sunday. Spec was updated to record this. The hero card above already shows the rolling 7-day total, so the loss is small.

If we want to honor the original intent, we'd need either:
- A separate per-run-type rolling aggregation query for just the rightmost bar (moderate complexity), or
- Drop the run-type stacking and use a simple total-volume chart with rolling current bar (regressive UX)

### "Planned vs Actual (per day)" and "Plan Compliance Trend" sections
Both sections exist in the Training tab but weren't in the original 6-section spec. They look useful — the spec was updated to include them, but they don't have their own scenario coverage. Worth backfilling tests/scenarios if either becomes a maintenance hot spot.

## Cleanup / Polish

### Repo-wide grep for stale chart references
Removed `chart-load` from `timeScaleCharts` in dashboard.html. Worth a broader sweep — there may be other dangling references to removed charts in CSS, JS, or comments. Quick grep: `grep -rn 'chart-load\|chart-rpe\|run-timeline' fit/`.

### tests/test_report.py duplication after rewrite
The Training tab rewrite added many new test cases. After things settle, scan `tests/test_report.py` for duplicate setup blocks across the new tests and consider extracting fixtures.

### `_aggregate_date_range` cache opportunity
Hero card, objectives, narrative, and alerts all call `compute_rolling_week()` separately on each report generation. They all hit the same SQL. If `fit report` ever feels slow, memoize per-process — or cache the result on `conn`.

## Future Capability Ideas (parking lot)

### Manual goals re-introduced with structured metadata
Decision 7 in design.md killed `fit goal add/list/complete` because manual goals had freeform names that couldn't map to the 4 canonical objective slots. If users ask for custom objectives back, the design path is: structured `metric_source` + `threshold` columns on goals, then the 4 slots can absorb manual goals via metadata match instead of name prefix.

### Per-phase volume targets on hero card
Hero card shows current phase's weekly_km target as a single number. When the phase target spans a range (e.g., 30-40km), we show the lower bound. Could show the range with a band on the daily-volume mini-chart.

### Adaptation signals over longer windows
Currently 4-week rolling. For users with sparser run patterns (1-2 runs/week of a given type), 4 weeks rarely hits the count >= 2 threshold. Consider adaptive window: 4 weeks if data, expand to 8 weeks otherwise.

### Streak with grace days
ISO-week streak is binary (3+ runs or break). A "1 grace week per 12 weeks" rule would survive normal life events without feeling punitive. Out of scope for this change but worth tracking.
