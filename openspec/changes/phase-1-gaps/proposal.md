# Phase 1 Gaps + Phase 2a — Unified Batch

## Why

Merges Phase 1 spec compliance fixes (26 items from audit) with Phase 2a quick wins (30 items) into a single implementation batch. 8 overlapping tasks deduplicated (auth errors, retry, zoom toggle, coaching refactor). Foundation/tech-debt first, then pipeline fixes, dashboard, then new features.

## What Changes

50 tasks across 10 groups:

1. **Foundation & Tech Debt** (6) — executescript fix, retry/backoff, auth errors, MCP schema, coaching context refactor
2. **Sync & Data Pipeline** (8) — activity types, hourly weather, LTHR save, non-running guard, ACWR fix, Rich progress bars
3. **MCP Server** (3) — DB check, LTHR detection, goal logging
4. **fit status & CLI** (4) — wire calibration, data health, phase, ACWR into status display
5. **Dashboard Charts** (9) — zoom toggle, offline fonts, run type stacked chart, annotations, zone targets, journey metrics
6. **Dashboard Cards & Headlines** (5) — VO2/weight deltas, sleep quality in headline, week-in-progress, race prediction
7. **Correlation Engine** (7) — Spearman, alerts engine, CLI, Coach tab viz
8. **Fitdays Auto-Import** (5) — configured path, import_log, auto-calibration
9. **Goal Tracking** (6) — fit goal add/list/complete, Today tab progress
10. **fit doctor & Docs** (4) — diagnostic command, spec/doc corrections

## Capabilities

Inherits all capabilities from both phase-1-gaps and phase-2-enrich (Phase 2a section).

## Impact

- Achieves full Phase 1 spec compliance
- Delivers the "data story" promise (correlations + alerts)
- Adds goal tracking, auto weight import, diagnostic tooling
- Fixes UX pain points (sync progress, auth errors, offline dashboard)
