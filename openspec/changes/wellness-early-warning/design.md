# Design: wellness-early-warning

## Context

`daily_health` already stores RHR, HRV (value + Garmin status), readiness, sleep, and a respiration average — populated for 650+ days. Three consumers exist and are already wired end-to-end: the alerts framework (`fit/alerts.py`: fire on sync → `alerts` table → Overview banner + `_ctx_alerts` in the coach context, with `_condition_still_holds` auto-dismiss), the Readiness tab charts (`fit/report/sections/charts.py`), and `_ctx_health` (`fit/coaching/context.py`). What's missing: sleep respiration is never captured (`fit/garmin.py:245` reads only `avgWakingRespirationValue`), respiration is rendered nowhere, and no rule compares any wellness signal against the athlete's own baseline.

## Goals / Non-Goals

**Goals:**
- Sleep respiration captured going forward (additive column, no backfill requirement).
- One baseline/deviation computation shared by alerts, coach context, and chart (SSOT — CLAUDE.md contract).
- Deviation alerts with fire/auto-dismiss parity, following the existing `spo2_low` consecutive-days pattern.
- Respiration chart on the Readiness tab consistent with existing chart conventions.

**Non-Goals:**
- Garmin Training Status / race predictor / body-battery-series ingestion (reviewed and rejected).
- Attention-panel (`_attention_items`) changes — wellness signals use the alerts channel.
- Readiness morning-vs-peak fix, sleep score, strain display (separate changes).
- Backfilling historical sleep respiration (would need per-day API calls over history; baselines only need the trailing window).

## Decisions

**D1 — Alerts channel, not attention panel.** The attention panel is admin/actions (calibrations, staleness, race results) with an SSOT contract; alerts are physiological safety signals that already reach the Overview banner, `fit status`, and the coach via `_ctx_alerts`. `readiness_gate` and `spo2_low` set the precedent. Alternative (new panel items) rejected: duplicates an existing channel and widens the attention-panel contract for no gain.

**D2 — `fit/wellness.py` as the shared helper module.** `wellness_snapshot(conn, config)` returns a typed snapshot: per-signal baseline (28-day rolling **median**, minimum 14 observations), latest values, consecutive-deviation counts, and boolean deviation states. Alerts (fire + `_condition_still_holds`), `_ctx_health`, and the chart builder all call it — same numbers everywhere, no drift between fire and dismiss. Median over mean: robust to single outlier nights. Baseline window *excludes* the days being evaluated (baseline = days [-window-n_eval, -n_eval)) so an ongoing illness doesn't absorb into its own baseline. Alternative (inline SQL per consumer, like `spo2_low` does) rejected: three consumers × three signals invites the fire-then-instant-dismiss mismatches the alerts file itself documents (D6, D12 comments).

**D3 — Respiration signal source: sleep average with waking fallback.** The illness literature (and the Garmin notes driving this change) key on *sleep* respiration. Until the new column populates (needs ~2 nights minimum, 14 for a baseline), the rule falls back to `avg_respiration` (waking) with the same thresholds — the deviation logic is relative to the same series' own baseline, so mixing is never allowed (sleep deviates vs sleep baseline; waking vs waking).

**D4 — Rule definitions** (thresholds in config under `coaching:`, following `spo2_alert_threshold`):
- `respiration_elevated` (warning): latest **2+ consecutive** nights each ≥ baseline + `respiration_delta_brpm` (default 2.0).
- `rhr_elevated` (warning): latest **3+ consecutive** days each ≥ baseline + `rhr_delta_bpm` (default 5).
- `recovery_cliff` (critical): on the latest day, RHR ≥ baseline + delta AND (HRV status `LOW` OR `hrv_last_night` < 0.85 × HRV baseline) AND readiness < 50. Compound rule fires independently of the two-/three-day streak rules (it's a same-day cliff, not a trend).
- Deviation compares each night/day against the *fixed* pre-window baseline (D2), so consecutive counting is well-defined during a multi-day episode.
- Missing data days break a consecutive streak (conservative: no interpolation; a gap means "unknown", not "still elevated").

**D5 — Chart: one respiration chart, two series + baseline band.** Line chart on the Readiness tab (after `chart-sleep`): sleep respiration (primary series), waking respiration (muted/dashed), horizontal band marking the normal zone (baseline → baseline + delta — nights above it are what fire the alert) from the same `wellness_snapshot`. Time axis per repo convention (`type: 'time'`, auto-unit); annotation band at 40+ hex opacity per CLAUDE.md. Rendered only when respiration data exists (matches other charts' guard style). No new design-system tokens needed — uses existing chart palette variables.

**D6 — Coach context line is additive.** `_ctx_health` gains one line after the existing `Last 7d:` line, e.g. `Respiration (sleep): 16.1 brpm 7d avg (baseline 15.4) — ELEVATED 2 nights` or the unremarkable form `Respiration (sleep): 15.2 brpm 7d avg (baseline 15.4)`. Coaching-context tests are semantic (section/line presence), extended not rewritten.

**D7 — Migration 019 is a plain additive ALTER** (`019_sleep_respiration.sql`): `ALTER TABLE daily_health ADD COLUMN avg_sleep_respiration REAL`. `_upsert_health` treats it like `avg_spo2` (COALESCE on conflict — don't wipe a previously-synced value when a later partial fetch returns NULL).

## Risks / Trade-offs

- [Sparse sleep-respiration history at launch — rules silent for ~2 weeks] → waking-average fallback (D3) keeps the signal live from day one; `fit doctor`/data-health unaffected.
- [Baseline drift for genuinely changing physiology (fitness gains lower RHR)] → 28-day rolling window follows slow drift; median resists single-night noise. Deltas (+2 brpm, +5 bpm) are the notes'/literature's standard and configurable.
- [Alert fatigue] → consecutive-day requirements, warning tier for single-signal rules, and the existing same-day dedup in `_fire` + type-dedup in `get_recent_alerts`. `recovery_cliff` is the only critical and needs three simultaneous conditions.
- [Fire/dismiss divergence] → both paths call `wellness_snapshot` (D2); a regression test asserts a fired rule's condition holds immediately after firing.
- [Timezone/definition mismatch: Garmin "day" vs local] → we key on Garmin's own `calendarDate` (as all `daily_health` ingestion already does); no new handling.

## Migration Plan

1. Migration 019 (additive) applies automatically on next `fit sync`/`fit report` via the migration runner; no data rewrite, instant rollback = column stays unused.
2. Sync starts populating `avg_sleep_respiration` for the re-fetched recent window (last N days) and all future days.
3. Rules activate as soon as enough data exists (waking fallback active immediately; sleep series takes over once it has a 14-observation baseline).

## Open Questions

_None blocking._ The HRV-below-baseline factor in `recovery_cliff` uses 0.85 × baseline (≈ the "meaningfully below normal range" heuristic); if Garmin's own `hrv_status=LOW` proves reliable alone, the ratio branch can be dropped later without a spec change (status is the primary condition; the ratio is the fallback when status is missing).
