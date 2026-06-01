## Why

The `calibration` table stores every reading for `max_hr`, `lthr`, `weight`, `vo2max`, and (after `aet-anchored-zones`) `aet`, but the dashboard never visualizes the history. The user sees only the *active* row per metric — they cannot tell whether the active value is well-corroborated (multiple agreeing readings) or a single noisy point.

Three concrete problems this creates:

1. **Active row selection is date-only.** `get_active_calibration()` returns `MAX(date)`. A spurious 220 bpm strap glitch *would* replace a clean 195 row simply because it's newer. There's no concept of confidence.
2. **Implausible readings are silently discarded.** The `extract_lthr_from_race()` and `extract_max_hr_from_activity()` paths reject obvious bad data (e.g., LTHR < 130, max_hr > 215) by returning `None`. The bad reading vanishes — the user has no audit trail of why a particular race didn't update the calibration.
3. **The two LTHR readings (172 in 2025-10, 171 in 2026-04, agreeing within 1 bpm) are physiologically meaningful** — that's a high-confidence calibration. But the dashboard renders LTHR as "172 (calibrated 224 days ago, stale)" without surfacing that the second reading confirmed it. The user can't see the agreement.

This change subsumes Part D of the archived `recalibrate-hr-zones` proposal.

## What Changes

### Schema: `flags` column on `calibration` table

Migration adds `flags TEXT` (JSON array of strings) defaulting to `'[]'`. Recognized flag values:

| Flag | When it fires |
|---|---|
| `implausible_value` | Outside physiological range (`max_hr > 215 or < 140`, `lthr < 130`, etc.) |
| `spike` | Activity-level max far above sustained max (sub-minute peak; strap glitch) |
| `unexpected_direction` | `max_hr` drops >2 bpm vs prior in <12 weeks, OR `lthr` drops >5 bpm vs prior in <12 weeks |
| `agrees_with_prior` | Within ±2 bpm of prior active reading (LTHR/max_hr) or method-appropriate tolerance |
| `weak_context` | Extracted from a non-race / non-hard-effort activity |

Auto-extract paths SHALL **always insert a calibration row** even when the value is implausible — the row gets `confidence = 'low'` and a flag list explaining why. No more silent rejection.

### Confidence rubric (uniform across all metrics)

| Confidence | Definition |
|---|---|
| `high` | Two corroborating readings within ±2 bpm (method-appropriate tolerance) from hard-effort contexts, OR explicitly set by user via `fit calibrate <metric> <value>` |
| `medium` | Single recent reading from a hard-effort context, plausible value, no flags |
| `low` | Any of: `implausible_value`, `spike`, `unexpected_direction`, `weak_context`, OR stale (past `STALENESS_THRESHOLDS`) |

`fit calibrate <metric> <value>` SHALL continue to write `high` (manual override is always trusted).

### Confidence-aware active selection

`get_active_calibration(conn, metric)` SHALL prefer the highest-confidence non-stale row, breaking ties by date (most recent first). A `low`-confidence flagged row SHALL NOT replace a clean `medium` or `high` row simply because it is more recent.

### Calibration history chart per metric (Profile tab)

A new "Calibration History" section on the Profile tab containing one chart per metric (LTHR, MaxHR, AeT-once-measured, weight, VO2max), each plotting the metric value over time. Each chart SHALL:

- Render every calibration row as a point (including `low`-confidence ones)
- Style points by confidence: solid dot = `high`, hollow dot = `medium`, red ring = `low`
- Show a horizontal band marking the staleness threshold; when the active row crosses it, the band turns red
- Tooltip on each point: date, value, method, confidence, flags, source activity (if any)

A CLI counterpart `fit calibrate history <metric>` SHALL print a sparkline + tabular history.

### Why this enables future work

`physiology-overview`'s "trend tag" can now query the calibration history to compute "stable" vs "+N bpm in M weeks" instead of approximating from recent activity data. `attention-panel` can prioritize stale-but-high-confidence calibrations differently from stale-and-low-confidence ones. `aet-anchored-zones` benefits from the confidence framework on day one.

## Capabilities

### Modified Capabilities

- `fitness-profile`: calibration table gains a `flags` column; `get_active_calibration()` becomes confidence-aware; confidence rubric is uniform across all metrics; auto-extract paths always record (never silently reject).
- `dashboard`: gains the per-metric calibration history charts on the Profile tab; CLI gains `fit calibrate history <metric>`.

## Impact

- **Code**:
  - New migration: `migrations/014_add_calibration_flags.sql` (or equivalent number) adding `flags TEXT DEFAULT '[]'`.
  - `fit/calibration.py`: new `derive_flags(metric, value, prior)` helper, new `derive_confidence(flags, method, has_prior_within_tolerance)` helper, `get_active_calibration()` rewritten with confidence-aware tiebreak, `extract_max_hr_from_activity()` and `extract_lthr_from_race()` always-record path.
  - `fit/sync.py`: pass `flags` through when calling `add_calibration` from the auto-extract paths.
  - `fit/cli.py`: new `fit calibrate history <metric>` subcommand printing sparkline + table; existing `fit calibrate <metric> <value>` writes `confidence='high'` (unchanged).
  - `fit/report/sections/cards.py`: new `_calibration_history(metric)` builder returning chart data per metric.
  - `fit/report/sections/charts.py`: new `chart-cal-history-<metric>` chart generator with confidence-color points and staleness band.
  - `fit/report/templates/dashboard.html`: new Calibration History section on Profile tab with one chart per metric.
- **Schema**: one new column on `calibration` (TEXT, default `'[]'`). No data migration needed — existing rows get the default empty list.
- **Tests**:
  - `tests/test_calibration.py::TestFlags` — flag derivation per metric / value / prior.
  - `tests/test_calibration.py::TestConfidence` — confidence rubric for every combination.
  - `tests/test_calibration.py::TestActiveSelection` — confidence-aware selection beats date.
  - `tests/test_calibration.py::TestAlwaysRecord` — extract paths insert low-confidence rows for implausible readings instead of silently returning None.
  - Section-level tests for the history chart data builder.
- **Data**: existing 5+ calibration rows get `flags = '[]'` via migration default; no retroactive flagging needed (an opportunity for the user to ask for it later).
- **External**: none.

## Risks / Trade-offs

- **Backfill question.** When this lands, do we walk the existing calibration history and apply the flag taxonomy retroactively? Default proposed: no. Existing rows keep `flags=[]` and `confidence` from their original write. The chart will show them as solid dots (high) or hollow (medium) based on the existing `confidence` field. Retroactive flagging is a separate opportunity.
- **`unexpected_direction` flag tuning.** "Drop > 2 bpm in 12 weeks for max_hr" is the proposal's starting point but may flag legitimate seasonal max_hr regression. Tune after dogfooding.
- **`agrees_with_prior` triggers a confidence bump.** This is the LTHR-bump-to-high case from the archived proposal's Part B. Tests must verify it doesn't bump on the *first* reading (no prior to agree with) or on a `low`-confidence prior.
- **Stale = low confidence is asserted.** A `high`-confidence calibration that goes 56+ days stale becomes `low` at query time (not at write time — the row stays `high` in storage, but `get_calibration_status()` reports `low`). This double-meaning of "confidence" — point-in-time write quality vs. current-trust-level — should be made explicit in the spec.

## Open Questions

1. Backfill: walk existing rows once to apply flags retroactively, or forward-only?
2. `unexpected_direction` threshold tuning per metric — proposal starts with 2 bpm (max_hr) / 5 bpm (lthr) but worth reviewing.
3. Tie-break rule for two `high` rows with different dates and methods: most recent wins, or method priority (race > activity_max)?
4. Spike-detection algorithm for `max_hr`: per-km split max vs activity-level max? Window length?
5. Should the calibration history CLI default to all metrics or require one? `fit calibrate history` vs `fit calibrate history <metric>`.
