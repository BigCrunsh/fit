## Context

Phase 1 delivered the complete ingest → store → analyze → visualize loop with 362 tests, 10 tables, 5-tab dashboard, 8 MCP tools, and coaching workflow. Phase 2 adds depth: correlations, plan adherence, .fit analysis, and automated integrations.

Tech debt from Phase 1: `executescript` auto-commit in migration runner, monolithic `get_coaching_context()`, non-functional zoom toggle, no retry/backoff in garmin.py.

## Goals / Non-Goals

**Goals:**
- Answer "why was this run slow?" with cross-domain evidence
- Detect coaching signals proactively (not just dashboard)
- Close planned vs executed training gap (Runna)
- Enable per-km analysis from .fit files
- Set and track individual goals
- Make `fit sync` pleasant to use

**Non-Goals:**
- Real-time streaming / live dashboards
- Training plan generation (Runna generates, we track adherence)
- Garmin watch face or widget
- Multi-user support

## Decisions

### 1. Sub-phase: 2a (quick wins + data story) → 2b (deep analysis + plan)

**Phase 2a**: tech debt fixes, sync UX, correlation engine + alerts, Fitdays auto-import, goal tracking, `fit doctor`.
**Phase 2b**: .fit file analysis, Runna plan integration, Run Story narrative, milestones, ioBroker hooks.

This mirrors Phase 1's successful sub-phasing. 2a delivers the "data story" promise fast; 2b adds heavier I/O and external dependencies.

### 2. Fix `executescript` auto-commit (Phase 1 tech debt)

SQLite's `executescript()` issues an implicit COMMIT, making the explicit BEGIN/COMMIT wrapping in `db.py` ineffective. Fix: parse SQL file into individual statements and execute each with `conn.execute()`, keeping the explicit transaction control working.

### 3. Spearman rank correlation (not Pearson)

Most correlation pairs involve ordinal (sleep_quality: Poor/OK/Good) or skewed (alcohol: mostly 0, occasionally 1-3) data. Pearson assumes normality and linearity. Spearman rank is appropriate for these distributions and robust to outliers.

For continuous-continuous pairs (temp→drift), compute both and display whichever has higher |r|.

Avoid scipy dependency: implement Spearman via rank transformation + numpy.corrcoef (~15 lines). P-value via t-distribution (~10 lines). No heavy dependency needed.

### 4. Differenced values for trended metrics

HRV is autocorrelated (today's HRV correlates with yesterday's regardless of alcohol). Weekly pace trends have serial dependence from fitness progression. Use differenced values: correlate *change* in HRV with alcohol, not raw HRV with alcohol. This prevents spurious correlations from shared trends.

### 5. Alerts engine separate from correlation engine

Correlations answer "over the last N weeks, does X predict Y?" — batch analysis.
Alerts answer "right now, based on today's data, should I change my plan?" — real-time rules.

`fit/alerts.py` runs after each sync, checks threshold rules, stores fired alerts in an `alerts` table. Alerts surface in Today tab headline and coaching context. This is more actionable day-to-day than stored r-values.

### 6. Runna plan: versioned import with structure JSON

Plans change weekly. Old plans are not deleted — superseded rows preserve history. Structure JSON supports multi-segment workouts (intervals can't be described by distance+zone alone).

Plan compliance computed as weekly score + systematic override detection. The system connects readiness data with planned workouts for readiness-gated recommendations.

### 7. .fit files: opt-in, cached, fail-safe

Not downloaded on every sync (too slow, hits API limits). Gated behind config toggle or `--splits` flag. Cached locally in `~/.fit/fit-files/`. Per-file failures don't crash sync. Max downloads per sync capped.

Rolling 1km drift detection identifies the exact km where HR decouples — "drift onset km" is the aerobic ceiling distance. More actionable than first/second half comparison.

### 8. Coaching context refactored into composable sections

`get_coaching_context()` is split into: `_ctx_health()`, `_ctx_training()`, `_ctx_correlations()`, `_ctx_plan()`, `_ctx_splits()`, `_ctx_goals()`. Each returns a list of context lines. This keeps the function maintainable as Phase 2 adds more data dimensions.

### 9. Post-sync hook system for ioBroker

Generic `hooks.post_sync` config list. Each hook is a Python callable path. ioBroker JSON export is one hook, not hardcoded. Allows future integrations (Home Assistant, webhooks) without modifying sync.py.

### 10. Individual goal lifecycle

Goals table already exists from Phase 1. Phase 2 adds: `fit goal add/list/complete` CLI commands, progress tracking against current data (VO2max vs target, weight vs target, streak vs target), habit goals (consecutive weeks), display on Today tab and `fit status`.

## Risks / Trade-offs

**[Correlation validity with small samples]** n=20 minimum still produces unreliable coefficients.
→ Mitigation: Display confidence level, p-value, sample size. Flag n<30 as "preliminary". Note confounders.

**[Runna plan maintenance]** Manual CSV re-import when plans change.
→ Mitigation: `fit plan validate` before import, versioned storage. Investigate API later.

**[.fit download volume]** Historical backfill could be slow.
→ Mitigation: Opt-in, capped per sync, separate `fit splits --backfill` command.

**[fitparse dependency]** Adds ~5MB dependency.
→ Mitigation: Well-maintained, fallback to skip split analysis if not installed.
