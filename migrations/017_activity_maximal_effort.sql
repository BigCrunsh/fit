-- Per-activity maximal-effort flag (maximal-effort-flag change).
-- Marks genuinely all-out efforts so the marathon model can FIT the duration-intensity fade
-- slope β from them (prior-regularized) instead of holding β at the population −6.5 constant.
-- Derived at sync/backfill by precedence (RPE ≥ 9 → 'rpe'); a sticky manual override
-- (source 'manual') always wins. Garmin `feel` is deliberately NOT a signal — it's a
-- strong↔weak subjective scale, orthogonal to exertion (all-out RPE-10 races read feel 1–2).
ALTER TABLE activities ADD COLUMN is_maximal INTEGER;          -- 1 = all-out, 0 = explicitly not, NULL = undetermined
ALTER TABLE activities ADD COLUMN max_effort_source TEXT;      -- 'rpe' | 'race' | 'manual' | 'heuristic' (future)
