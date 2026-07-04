-- Sleep respiration average (brpm) from Garmin's respiration endpoint.
-- The illness/overtraining early-warning signal keys on the SLEEP average;
-- avg_respiration keeps holding the waking average (unchanged).
ALTER TABLE daily_health ADD COLUMN avg_sleep_respiration REAL;
