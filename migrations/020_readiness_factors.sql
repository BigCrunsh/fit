-- Garmin's Training Readiness factor breakdown.
--
-- We stored only the final 0-100 score, so "why is readiness 1?" was answerable
-- only by inference. Garmin returns the inputs it scored: how much recovery time
-- is still counting down plus a 0-100 rating per factor. Storing them lets the
-- readiness alert and the coaching context name the driver instead of implying
-- that every low score means accumulated fatigue.
--
-- History synced before this migration keeps NULL factors — Garmin's readiness
-- endpoint only answers for recent dates, so there is nothing to backfill from.
ALTER TABLE daily_health ADD COLUMN readiness_recovery_time_min INTEGER;   -- minutes still counting down
ALTER TABLE daily_health ADD COLUMN readiness_recovery_factor_pct INTEGER; -- 0-100 per-factor ratings
ALTER TABLE daily_health ADD COLUMN readiness_sleep_factor_pct INTEGER;
ALTER TABLE daily_health ADD COLUMN readiness_hrv_factor_pct INTEGER;
ALTER TABLE daily_health ADD COLUMN readiness_acwr_factor_pct INTEGER;
ALTER TABLE daily_health ADD COLUMN readiness_sleep_history_pct INTEGER;
ALTER TABLE daily_health ADD COLUMN readiness_stress_history_pct INTEGER;
ALTER TABLE daily_health ADD COLUMN readiness_feedback TEXT;               -- Garmin's own one-phrase reason
ALTER TABLE daily_health ADD COLUMN sleep_score INTEGER;                   -- Garmin sleep score 0-100
