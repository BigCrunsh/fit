# Phase 1 Gaps — Spec Compliance Fixes

## Why

A thorough audit of the Phase 1 implementation against its archived specs found 7 missing requirements, 25 partial implementations, and 5 divergences. Most are small fixes. Some overlap with Phase 2 tech debt (executescript, zoom toggle) and will be addressed there. This change covers the remaining Phase 1-specific gaps.

## What Changes

Fix spec compliance gaps that don't belong in Phase 2:

## Capabilities

- **config-fix** — Document that env vars are placeholder-substitution, not general override. This is by-design, not a bug — update the spec to match reality.

- **sync-gaps** — Garmin auth error message with instructions, activity type coverage (add more types to fetch list), Move IQ detection improvement, hourly weather using actual start time, LTHR auto-extraction save/prompt, backfill migration derived metrics note.

- **status-gaps** — `fit status` displays calibration status, data health, active phase, ACWR, consistency streak (all functions exist, just not wired into CLI).

- **dashboard-gaps** — Offline fonts (inline or remove Google Fonts import), run type breakdown stacked chart, event annotations on all time-series charts, status card improvements (VO2 peak/delta, weight target/delta, sleep REM), zone chart phase target overlay, journey timeline per-phase metrics, sleep chart averages, weight chart race target, headline sleep quality check, week-in-progress label.

- **mcp-gaps** — Missing DB error message, LTHR detection in data health check.

## Impact

Brings Phase 1 to full spec compliance. Most fixes are small (5-20 lines each). The dashboard gaps are the largest group but individually small.
