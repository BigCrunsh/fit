# Tasks: wellness-early-warning

## 1. Ingestion — sleep respiration (TDD)

- [x] 1.1 Write failing tests: migration 019 adds `avg_sleep_respiration` (existing rows NULL); `_fetch_day_health` parses `avgSleepRespirationValue` (present / missing / whole payload absent); upsert COALESCE preserves stored value on NULL re-sync
- [x] 1.2 Add `migrations/019_sleep_respiration.sql` (additive ALTER)
- [x] 1.3 Parse `avgSleepRespirationValue` in `fit/garmin.py:_fetch_day_health`
- [x] 1.4 Add column to `fit/sync.py:_upsert_health` with COALESCE on conflict; run tests green

## 2. Baseline helper — `fit/wellness.py` (TDD)

- [x] 2.1 Write failing tests (`tests/test_wellness.py`): baseline median over 28d window excluding evaluation days; undefined under 14 observations; missing-day breaks streak; boundary (value == baseline+delta counts); waking fallback when sleep series thin; series never mixed; HRV ratio fallback
- [x] 2.2 Implement `wellness_snapshot(conn, config)` returning per-signal baseline, latest values, consecutive-deviation counts, deviation states
- [x] 2.3 Add config defaults to `config.yaml` under `coaching:` (`respiration_delta_brpm: 2.0`, `rhr_delta_bpm: 5`, `wellness_baseline_days: 28`); run tests green

## 3. Alert rules (TDD)

- [x] 3.1 Write failing tests (`tests/test_alerts.py`): fire/no-fire/boundary for `respiration_elevated` (2 nights), `rhr_elevated` (3 days, interrupted streak), `recovery_cliff` (all-three vs two-of-three, HRV ratio fallback, missing readiness blocks); fire→condition-still-holds parity; auto-dismiss on normalization
- [x] 3.2 Implement the 3 rules in `fit/alerts.py:run_alerts` via `wellness_snapshot`; add severity map entries (warning/warning/critical)
- [x] 3.3 Implement `_condition_still_holds` branches via the same snapshot; run tests green

## 4. Coaching context (TDD)

- [x] 4.1 Write failing tests (`tests/test_coaching_context.py`): respiration line with baseline + ELEVATED flag; unremarkable form; omitted when no data; sleep-vs-waking label
- [x] 4.2 Add respiration line to `_ctx_health` via `wellness_snapshot`; run tests green

## 5. Dashboard chart

- [x] 5.1 Load `dataviz` skill; write failing tests (`tests/test_dashboard_charts_coverage.py` / `test_chart_axes.py` patterns): chart present with data, omitted without, time axis, band only when baseline defined
- [x] 5.2 Implement respiration chart in `fit/report/sections/charts.py` (sleep primary, waking muted, baseline±delta band at 40+ hex opacity) + chart slot in `dashboard.html` Readiness tab; run tests green

## 6. Verify & ship

- [x] 6.1 Full check suite (pytest, ruff, any other CI gates) green
- [x] 6.2 End-to-end: `fit report` against a copy of the real DB — Readiness tab shows respiration chart; alerts evaluate without error
- [ ] 6.3 Commit, push branch, open draft PR
