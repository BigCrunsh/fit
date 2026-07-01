-- Remove the daily check-in feature and the cross-domain correlation engine.
--
-- Both features are retired: `fit checkin` and `fit correlate` are gone, along
-- with every consumer that read their data. This migration drops the backing
-- tables and rebuilds the `v_run_days` view without its check-in columns.
--
-- The `v_run_days` view (defined in 001, recreated in 014) LEFT JOINs `checkins`
-- and exposes hydration/alcohol/legs/eating/water_liters/daily_rpe. SQLite
-- re-validates views that reference a table when that table is dropped, so the
-- view must be dropped first, then recreated without the checkins join — the
-- canonical drop-then-recreate procedure (see 014 for the same pattern).

DROP VIEW IF EXISTS v_run_days;

DROP TABLE IF EXISTS checkins;
DROP TABLE IF EXISTS correlations;

-- Recreate v_run_days identical to its 014 definition, minus the checkins join
-- and the six check-in columns it exposed. Activity + health + weather + weight.
CREATE VIEW IF NOT EXISTS v_run_days AS
SELECT
    a.date, a.name, a.distance_km, a.duration_min, a.pace_sec_per_km,
    a.avg_hr, a.max_hr, a.vo2max, a.training_load, a.hr_zone,
    a.speed_per_bpm, a.speed_per_bpm_z2, a.effort_class, a.run_type,
    a.rpe AS activity_rpe, a.avg_cadence, a.temp_at_start_c, a.humidity_at_start_pct,
    h.resting_heart_rate, h.sleep_duration_hours, h.deep_sleep_hours,
    h.training_readiness, h.hrv_last_night, h.avg_stress_level, h.avg_spo2,
    w.temp_c, w.humidity_pct, w.wind_speed_kmh,
    b.weight_kg
FROM activities a
LEFT JOIN daily_health h ON a.date = h.date
LEFT JOIN weather w ON a.date = w.date
LEFT JOIN body_comp b ON a.date = b.date
WHERE a.type IN ('running', 'track_running', 'trail_running');
