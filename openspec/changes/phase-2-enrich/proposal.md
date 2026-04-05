# Phase 2 — Enrich: Data Story, Integrations, Deep Analysis

## Why

Phase 1 built the data pipeline and basic dashboard. The data flows, Claude can query, the daily loop works. But the platform is still missing its highest-value features: the data story that connects subjective and objective signals, integration with external training systems, automated data ingestion, and deep per-run analysis. The dashboard shows charts but doesn't yet answer "why was this run slow?" with cross-domain evidence.

Additionally, Phase 1 has tech debt to address: `db.py` uses `executescript` which auto-commits (breaking transaction safety), `get_coaching_context()` is monolithic (100+ lines), and the dashboard zoom toggle is a non-functional placeholder.

## What Changes

Split into two sub-phases to manage scope:

**Phase 2a** moved to `phase-1-gaps` change (unified batch with Phase 1 spec fixes).

**Phase 2b — "Deep Analysis + Plan"** (this change): .fit file analysis (per-km splits, cardiac drift), Runna plan integration (adherence tracking), Run Story narrative, milestones, ioBroker.

## Capabilities

- **tech-debt** — Fix `executescript` auto-commit in migration runner, refactor `get_coaching_context()` into composable sections, implement or remove the dashboard zoom toggle, add shared retry/backoff utility in garmin.py.

- **correlation-engine** — Cross-domain analysis using **Spearman rank correlation** (not Pearson — alcohol is skewed, sleep_quality is ordinal). Predefined pairs: alcohol → HRV/RHR/sleep_quality, sleep duration+quality → next-day HR-at-pace, weight → RPE at constant pace, temp → cardiac drift. Minimum sample sizes: 20 for reporting, 30 for coaching. Uses differenced values for trended metrics. Correlation panel on Coach tab (not Fitness — already overloaded). Plus a real-time **alerts engine** (`fit/alerts.py`) for threshold checks on fresh data.

- **runna-integration** — Import Runna training plan via CSV with **plan versioning** (supersede old plans, don't delete). Planned_workouts table with **structure JSON** for multi-segment workouts (intervals). Weekly **plan compliance score** (0-100%). Detect **systematic intensity override** pattern. Track **rest day compliance**. Plan CSV includes plan_week and plan_phase columns. `fit plan validate` dry-run before import.

- **fitdays-auto-import** — Automated weight + body comp sync from **configured path** (not ~/Downloads/ scanning). Import tracking via `import_log` table. Auto-update weight calibration on new measurements.

- **fit-file-analysis** — Parse .fit files gated behind **`--splits` flag or config toggle** (not every sync). Cache files in `~/.fit/fit-files/`. Per-file failure handling with `splits_status` column. **Rolling 1km drift detection** (not just first/second half). **Pace variability** (CV across splits), **cadence drift**, **time_above_z2_ceiling_sec** per split. Constant-pace filter for drift validity. Split viz as **dual-axis bar+line** (pace bars + HR line) with **fade point annotation** and **elevation profile background**.

- **goal-tracking** — Individual goal setting and tracking beyond the marathon. `fit goal add/list/complete` CLI. Race goals (with target time), metric goals (VO2max, weight, efficiency), habit goals (runs per week, check-in streak). Progress displayed on Today tab and `fit status`.

- **sync-ux** — Rich progress bars per sync step, ETA for `--full`, shared retry/backoff, better auth errors. Post-sync hook system for ioBroker. `fit doctor` diagnostic command.

- **coaching-signals** — Auto-detection rules: "all runs too hard" (Z2 < 50% over 2 weeks), volume ramp guard (>10% + <8 weeks), readiness-to-planned-workout gate, long run distance projection, heat acclimatization tracker. **Run Story narrative** for most recent long run (splits + correlations + checkin synthesized into coaching text). **Milestone/PB tracking** on Today tab.

## Impact

- **Correlation engine + alerts** answer "why was this run slow?" with evidence and catch same-day signals
- **Runna integration** tracks plan adherence systematically — "you've overridden 80% of easy runs"
- **Fitdays auto-import** keeps weight calibration fresh
- **.fit file analysis** enables "your HR decoupled at km 14 — that's your current aerobic ceiling"
- **Run Story narrative** is the data storytelling vision — a single paragraph synthesizing everything about a run
- **Coaching signals** catch problems proactively before they become injuries
