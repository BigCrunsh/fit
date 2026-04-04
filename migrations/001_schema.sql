-- ══════════════════════════════════════════════════
-- fit — fitness.db schema
-- ══════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS activities (
    id              TEXT PRIMARY KEY,        -- Garmin activity_id
    date            DATE NOT NULL,
    type            TEXT NOT NULL,           -- running, cycling, swimming, hiking, walking, ...
    subtype         TEXT,                    -- manual / auto_detected (Move IQ) / imported
    name            TEXT,
    distance_km     REAL,
    duration_min    REAL,
    pace_sec_per_km REAL,                   -- null for non-distance activities
    avg_hr          INTEGER,
    max_hr          INTEGER,
    avg_cadence     REAL,
    elevation_gain_m REAL,
    calories        INTEGER,
    vo2max          REAL,
    aerobic_te      REAL,
    training_load   REAL,
    avg_stride_m    REAL,
    avg_speed       REAL,
    start_lat       REAL,
    start_lon       REAL,
    -- Derived (computed on insert via analysis.py)
    hr_zone         TEXT,                   -- Z1/Z2/Z3/Z4/Z5
    cardiac_efficiency REAL,               -- pace / avg_hr (HR 140-160 only)
    effort_class    TEXT,                   -- Easy / Moderate / Hard
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_activities_date ON activities(date);
CREATE INDEX IF NOT EXISTS idx_activities_type ON activities(type);

CREATE TABLE IF NOT EXISTS daily_health (
    date                    DATE PRIMARY KEY,
    total_steps             INTEGER,
    total_distance_m        REAL,
    total_calories          INTEGER,
    active_calories         INTEGER,
    resting_heart_rate      INTEGER,
    max_heart_rate          INTEGER,
    min_heart_rate          INTEGER,
    avg_stress_level        INTEGER,
    max_stress_level        INTEGER,
    body_battery_high       INTEGER,
    body_battery_low        INTEGER,
    sleep_duration_hours    REAL,
    deep_sleep_hours        REAL,
    light_sleep_hours       REAL,
    rem_sleep_hours         REAL,
    awake_hours             REAL,
    deep_sleep_pct          REAL,
    training_readiness      INTEGER,
    readiness_level         TEXT,
    hrv_weekly_avg          REAL,
    hrv_last_night          REAL,
    hrv_status              TEXT,
    avg_respiration         REAL,
    avg_spo2                REAL,
    created_at              DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS checkins (
    date            DATE PRIMARY KEY,
    hydration       TEXT,                   -- Low / OK / Good
    alcohol         REAL DEFAULT 0,         -- drinks count
    alcohol_detail  TEXT,                   -- "2 beers", "1 glass wine"
    legs            TEXT,                   -- Heavy / OK / Fresh
    eating          TEXT,                   -- Poor / OK / Good
    water_liters    REAL,
    energy          TEXT,                   -- Low / Normal / Good
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS body_comp (
    date            DATE PRIMARY KEY,
    weight_kg       REAL NOT NULL,
    body_fat_pct    REAL,
    muscle_mass_kg  REAL,
    visceral_fat    REAL,
    bmi             REAL,
    source          TEXT DEFAULT 'fitdays',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weather (
    date            DATE PRIMARY KEY,
    temp_c          REAL,
    temp_max_c      REAL,
    temp_min_c      REAL,
    humidity_pct    REAL,
    wind_speed_kmh  REAL,
    precipitation_mm REAL,
    conditions      TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,           -- marathon / half_marathon / 10k / metric
    target_time     TEXT,
    target_pace     REAL,                   -- sec/km
    target_value    REAL,
    target_unit     TEXT,
    target_date     DATE,
    active          BOOLEAN DEFAULT 1,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS weekly_agg (
    week            TEXT PRIMARY KEY,        -- "2026-W13"
    runs            INTEGER,
    total_km        REAL,
    avg_pace        REAL,
    avg_hr          REAL,
    total_load      REAL,
    avg_readiness   REAL,
    avg_sleep       REAL,
    avg_rhr         REAL,
    avg_hrv         REAL,
    weight_avg      REAL,
    z2_pct          REAL,
    z3_pct          REAL,
    z4_pct          REAL,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ══════════════════════════════════════════════════
-- Views
-- ══════════════════════════════════════════════════

CREATE VIEW IF NOT EXISTS v_run_days AS
SELECT
    a.date, a.name, a.distance_km, a.pace_sec_per_km, a.avg_hr, a.max_hr,
    a.vo2max, a.training_load, a.hr_zone, a.cardiac_efficiency,
    h.resting_heart_rate, h.sleep_duration_hours, h.deep_sleep_hours,
    h.training_readiness, h.hrv_last_night, h.avg_stress_level, h.avg_spo2,
    c.hydration, c.alcohol, c.legs, c.eating, c.water_liters,
    w.temp_c, w.humidity_pct, w.wind_speed_kmh,
    b.weight_kg
FROM activities a
LEFT JOIN daily_health h ON a.date = h.date
LEFT JOIN checkins c ON a.date = c.date
LEFT JOIN weather w ON a.date = w.date
LEFT JOIN body_comp b ON a.date = b.date
WHERE a.type = 'running';

CREATE VIEW IF NOT EXISTS v_all_training AS
SELECT
    a.date, a.type, a.name, a.distance_km, a.duration_min,
    a.avg_hr, a.calories, a.training_load, a.subtype,
    h.resting_heart_rate, h.training_readiness, h.sleep_duration_hours
FROM activities a
LEFT JOIN daily_health h ON a.date = h.date
ORDER BY a.date DESC;
