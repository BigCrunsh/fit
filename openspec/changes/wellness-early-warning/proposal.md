# Proposal: wellness-early-warning

## Why

The platform ingests 650+ days of wellness data (RHR, HRV, respiration, readiness) but surfaces none of it as an early-warning signal: respiration is rendered nowhere (and only the *waking* average is captured — the illness/overtraining indicator is the *sleep* average), and no alert rule watches for deviations from the athlete's personal baseline. The coach prompt names the "recovery cliff" (RHR up + HRV down + readiness low together) but nothing computes it. A 2026-07-04 insights review (Garmin-965 observation notes vs dashboard) identified this as the highest-value gap: illness/overtraining shows up in sleep respiration and RHR days before it shows up in training data.

## What Changes

- **Capture sleep respiration**: parse `avgSleepRespirationValue` from the already-fetched Garmin respiration payload (zero new API calls) into a new `daily_health.avg_sleep_respiration` column (migration 019). Waking average stays in `avg_respiration`.
- **Personal-baseline deviation detection**: a shared helper (`fit/wellness.py`) computes 28-day rolling baselines (median, for robustness) for sleep respiration and RHR, and evaluates deviation states. Single source of truth consumed by alerts, coaching context, and the dashboard chart.
- **Three new alert rules** in the existing `fit/alerts.py` framework (fire + auto-dismiss parity, same as `spo2_low`/`readiness_gate`):
  - `respiration_elevated` (warning): sleep respiration ≥ baseline + 2 brpm for 2+ consecutive nights — possible illness/overtraining.
  - `rhr_elevated` (warning): RHR ≥ baseline + 5 bpm for 3+ consecutive days — accumulated fatigue or illness.
  - `recovery_cliff` (critical): RHR elevated AND HRV status LOW (or HRV below baseline) AND readiness < 50 on the latest day — the compound signal the coach prompt already describes.
- **Respiration visible on the Readiness tab**: a time-series chart (sleep + waking respiration with the personal baseline band), following the existing chart conventions (design_system palette, time axis).
- **Coaching context**: the `_ctx_health` recovery block gains a respiration line (7d sleep-respiration average + baseline deviation flag) so `fit coach` sees the same signal.
- **Config thresholds**: deviation deltas and windows under `coaching:` (`respiration_delta_brpm: 2`, `rhr_delta_bpm: 5`, `wellness_baseline_days: 28`), following the existing `spo2_alert_threshold` pattern.

Non-goals: no Garmin Training Status / race predictor ingestion (deliberately rejected — redundant with own load model); no attention-panel changes (wellness signals live in the alerts channel, which already reaches the Overview banner and coach context); no readiness-source change (morning vs peak is a separate change).

## Capabilities

### New Capabilities

_None — all changes extend existing capabilities._

### Modified Capabilities

- `coaching-signals`: new wellness baseline-deviation alert requirements (respiration_elevated, rhr_elevated, recovery_cliff) alongside the existing SpO2 illness alert; coaching context health section gains respiration.
- `data-ingestion`: `daily_health` schema gains `avg_sleep_respiration`; sync parses the sleep respiration field from the existing respiration endpoint.
- `dashboard`: Readiness (Body) tab gains a respiration chart with personal baseline band.

## Impact

- **Code**: `fit/garmin.py` (parse), `fit/sync.py` (upsert), `migrations/019_sleep_respiration.sql` (new), `fit/wellness.py` (new — baseline helper), `fit/alerts.py` (3 rules + severity map + auto-dismiss), `fit/coaching/context.py` (`_ctx_health` line), `fit/report/sections/charts.py` (respiration chart), `fit/report/templates/dashboard.html` (chart slot on Readiness tab), `config.yaml` (threshold defaults).
- **Tests**: new `tests/test_wellness.py`; extensions to `tests/test_alerts.py`, `tests/test_garmin.py`, `tests/test_coaching_context.py`, `tests/test_dashboard_charts_coverage.py`. TDD, ~2:1 unhappy:happy.
- **Data**: one additive column; existing rows keep NULL sleep respiration until the next sync/backfill window (sync re-fetches recent days; older history stays NULL — acceptable, baselines need only 28 days).
- **No breaking changes**: alerts are additive; context line is additive (semantic context tests extended, not rewritten).
