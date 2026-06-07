-- Change body_comp.source DEFAULT from 'fitdays' to 'apple_health'.
--
-- The FitDays CSV importer was removed; Apple Health Export.zip is now the
-- only ingest path (`fit import-health`). Any INSERT that doesn't specify
-- `source` (e.g. test fixtures, hypothetical future code paths) should land
-- as 'apple_health', matching the actual provenance, not 'fitdays'.
--
-- SQLite doesn't support ALTER COLUMN DEFAULT directly, so we recreate the
-- table. Existing rows keep their original `source` values via the SELECT.
--
-- The `v_run_days` view (001) joins body_comp, so it must be dropped before the
-- DROP/RENAME and recreated after — otherwise SQLite (>= 3.25.2, the default
-- non-legacy ALTER) re-validates the view mid-rename, finds no `body_comp`, and
-- fails with "error in view v_run_days: no such table". Drop-then-recreate is
-- the canonical, version-independent table-rebuild procedure.

DROP VIEW IF EXISTS v_run_days;

CREATE TABLE body_comp_v2 (
    date            DATE PRIMARY KEY,
    weight_kg       REAL NOT NULL,
    body_fat_pct    REAL,
    muscle_mass_kg  REAL,
    visceral_fat    REAL,
    bmi             REAL,
    source          TEXT DEFAULT 'apple_health',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO body_comp_v2 (date, weight_kg, body_fat_pct, muscle_mass_kg, visceral_fat, bmi, source, created_at)
    SELECT date, weight_kg, body_fat_pct, muscle_mass_kg, visceral_fat, bmi, source, created_at
    FROM body_comp;

DROP TABLE body_comp;
ALTER TABLE body_comp_v2 RENAME TO body_comp;

-- Recreate the view (identical to its 001 definition) now that body_comp exists.
CREATE VIEW IF NOT EXISTS v_run_days AS
SELECT
    a.date, a.name, a.distance_km, a.duration_min, a.pace_sec_per_km,
    a.avg_hr, a.max_hr, a.vo2max, a.training_load, a.hr_zone,
    a.speed_per_bpm, a.speed_per_bpm_z2, a.effort_class, a.run_type,
    a.rpe AS activity_rpe, a.avg_cadence, a.temp_at_start_c, a.humidity_at_start_pct,
    h.resting_heart_rate, h.sleep_duration_hours, h.deep_sleep_hours,
    h.training_readiness, h.hrv_last_night, h.avg_stress_level, h.avg_spo2,
    c.hydration, c.alcohol, c.legs, c.eating, c.water_liters, c.rpe AS daily_rpe,
    w.temp_c, w.humidity_pct, w.wind_speed_kmh,
    b.weight_kg
FROM activities a
LEFT JOIN daily_health h ON a.date = h.date
LEFT JOIN checkins c ON a.date = c.date
LEFT JOIN weather w ON a.date = w.date
LEFT JOIN body_comp b ON a.date = b.date
WHERE a.type IN ('running', 'track_running', 'trail_running');
