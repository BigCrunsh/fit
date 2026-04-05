# Phase 2 — Enrich: Data Story, Integrations, Deep Analysis

## Why

Phase 1 built the data pipeline and basic dashboard. The data flows, Claude can query, the daily loop works. But the platform is still missing its highest-value features: the data story that connects subjective and objective signals, integration with external training systems, automated data ingestion, and deep per-run analysis. The dashboard shows charts but doesn't yet answer "why was this run slow?" with cross-domain evidence.

## What Changes

Five capability areas, ordered by user impact:

1. **Data story / correlation engine** — The original vision: cross-domain analysis that connects alcohol → HRV, weight → pace, temp → cardiac drift, sleep quality → readiness. Query-based insights surfaced in the dashboard and coaching context.

2. **Runna training plan integration** — Import the current Runna plan so the system knows the *intended* workout, not just what happened. Flag when execution diverges from prescription ("Runna said Z2 easy 7km, you ran Z4 tempo 12.5km"). Phase compliance becomes plan compliance.

3. **Fitdays auto-import** — Pull weight + body comp data automatically instead of manual CSV. Fitdays → Apple Health → fit sync pipeline. Keeps the weight calibration fresh.

4. **Deep run analysis via .fit files** — Per-km splits, HR drift within a run, cadence fade in long runs, pace vs elevation. Second-by-second data from Garmin .fit files. The avg-HR-per-run proxy loses detail that matters for coaching.

5. **Sync UX + ioBroker dashboard** — Progress bar for `fit sync --full`, better error messages. Optional: expose key metrics via MQTT/REST for ioBroker home automation dashboard (always-on display).

## Capabilities

- **correlation-engine** — Cross-domain analysis: alcohol → next-day HRV/readiness, weight trend → pace trend, temperature → cardiac drift, sleep quality → performance. Computed correlations stored in DB, surfaced in Fitness tab and coaching context. Time-lagged analysis (yesterday's alcohol affects today's HRV).

- **runna-integration** — Import Runna training plan (manual CSV/JSON or API if available). Store planned workouts: date, type, distance, target zone, target pace. Compare planned vs actual per run. Dashboard shows plan adherence. Coaching context includes plan deviation.

- **fitdays-auto-import** — Automated weight + body composition sync. Fitdays scale → Apple Health → export → fit import pipeline. Or direct Fitdays API if available. Keep body_comp table current without manual CSV.

- **fit-file-analysis** — Parse .fit files from Garmin for per-km splits, HR zones per km, cadence per km, elevation profile, cardiac drift (HR rise at constant pace). Store per-km data in a new `activity_splits` table. Dashboard shows split analysis for individual runs.

- **sync-ux** — Rich progress bar for `fit sync`, per-step status, ETA for `--full`. Better error messages for auth failures, API rate limits. Optional: ioBroker integration via MQTT or REST endpoint exposing key daily metrics (readiness, ACWR, last run, weight).

## Impact

- **Correlation engine** unlocks the core promise: "Show me runs where I had >1 drink and compare efficiency"
- **Runna integration** closes the gap between planned and executed training — the coaching system can say "you're not following your plan" with evidence
- **Fitdays auto-import** keeps weight calibration fresh without manual effort
- **.fit file analysis** enables coaching insights impossible from averages alone: "your HR drifted 15 bpm in the last 5km — dehydration or undertrained for the distance?"
- **Sync UX** eliminates the "is it still running?" anxiety from `fit sync --full`
- **ioBroker** is optional/exploratory — value depends on existing home automation setup
