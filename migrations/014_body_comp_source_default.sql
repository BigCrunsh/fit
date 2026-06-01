-- Change body_comp.source DEFAULT from 'fitdays' to 'apple_health'.
--
-- The FitDays CSV importer was removed; Apple Health Export.zip is now the
-- only ingest path (`fit import-health`). Any INSERT that doesn't specify
-- `source` (e.g. test fixtures, hypothetical future code paths) should land
-- as 'apple_health', matching the actual provenance, not 'fitdays'.
--
-- SQLite doesn't support ALTER COLUMN DEFAULT directly, so we recreate the
-- table. Existing rows keep their original `source` values via the SELECT.

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
