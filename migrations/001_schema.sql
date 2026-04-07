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
    temp_at_start_c REAL,                  -- hourly weather at activity start time
    humidity_at_start_pct REAL,
    rpe             INTEGER,               -- Rate of Perceived Exertion 1-10 (optional, set via checkin or MCP)
    run_type        TEXT,                   -- easy / long / tempo / intervals / recovery / race / progression (auto-classified or manual)
    -- Derived (computed on insert via analysis.py — frozen at insert time)
    max_hr_used     INTEGER,               -- max HR config value when zones were computed (for backward compat)
    lthr_used       INTEGER,               -- LTHR value when zones were computed (NULL if no LTHR calibrated at insert time)
    hr_zone_maxhr   TEXT,                   -- Z1/Z2/Z3/Z4/Z5 via max HR model (always computed)
    hr_zone_lthr    TEXT,                   -- Z1/Z2/Z3/Z4/Z5 via LTHR model (NULL if no LTHR calibrated)
    hr_zone         TEXT,                   -- primary zone — alias for preferred model per config (for backward compat + queries)
    speed_per_bpm   REAL,                  -- (m/min) / avg_hr — higher = more efficient (all runs, raw)
    speed_per_bpm_z2 REAL,                 -- same but Z2 HR only — pure aerobic trending
    effort_class    TEXT,                   -- Recovery / Easy / Moderate / Hard / Very Hard (5 levels matching 5 zones)
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
    rpe             INTEGER,               -- Rate of Perceived Exertion 1-10 (overall day / last workout)
    sleep_quality   TEXT,                  -- Poor / OK / Good (subjective — complements Garmin sleep data)
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

CREATE TABLE IF NOT EXISTS training_phases (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id         INTEGER REFERENCES goals(id),
    phase           TEXT NOT NULL,           -- "Phase 1", "Phase 2", etc.
    name            TEXT,                    -- "Base Building", "Volume", "Peak", "Taper"
    start_date      DATE,
    end_date        DATE,
    -- Denormalized targets for fast compliance queries
    z12_pct_target  REAL,                    -- target Z1+Z2 time percentage (e.g., 90 for Phase 1)
    z45_pct_target  REAL,                    -- target Z4+Z5 time percentage (e.g., 0 for Phase 1)
    weekly_km_min   REAL,                    -- target weekly km range lower bound
    weekly_km_max   REAL,                    -- target weekly km range upper bound
    -- Full target/actual picture (all dimensions as JSON)
    targets         TEXT,                    -- JSON: {"run_frequency": [3,4], "quality_sessions_per_week": 0, "rest_days_min": 2, "cross_train_min_per_week": 60, "acwr_range": [0.8, 1.2], ...}
    actuals         TEXT,                    -- JSON: updated when phase ends {"z2_pct": 72, "weekly_km_avg": 22, ...}
    status          TEXT DEFAULT 'planned',  -- planned / active / completed / revised
    notes           TEXT,                    -- free text: adjustments, context
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS goal_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE NOT NULL,
    goal_id         INTEGER REFERENCES goals(id),
    phase_id        INTEGER REFERENCES training_phases(id),
    type            TEXT NOT NULL,           -- goal_created / goal_updated / phase_started / phase_completed / phase_revised / milestone_achieved / setback
    description     TEXT NOT NULL,           -- what changed and why
    previous_value  TEXT,                    -- JSON: what it was before (for updates)
    new_value       TEXT,                    -- JSON: what it is now (for updates)
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS calibration (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    metric          TEXT NOT NULL,           -- max_hr / lthr / weight / vo2max
    value           REAL NOT NULL,
    method          TEXT NOT NULL,           -- lab_test / time_trial / race_extract / garmin_estimate / manual / scale
    source_activity_id TEXT,                 -- activity_id if extracted from a race/TT (FK to activities)
    confidence      TEXT,                    -- high / medium / low
    date            DATE NOT NULL,
    notes           TEXT,
    active          BOOLEAN DEFAULT 1,       -- most recent calibration per metric is active
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_calibration_metric ON calibration(metric, active);

CREATE TABLE IF NOT EXISTS weekly_agg (
    week            TEXT PRIMARY KEY,        -- "2026-W13"
    -- Running metrics
    run_count       INTEGER,
    run_km          REAL,
    run_avg_pace    REAL,
    run_avg_hr      REAL,
    longest_run_km  REAL,                   -- longest single run distance this week
    run_avg_cadence REAL,                   -- avg cadence across all runs this week (spm)
    easy_run_count  INTEGER,                -- runs classified as easy/recovery
    quality_session_count INTEGER,          -- runs classified as tempo/intervals/race
    -- Cross-training metrics
    cross_train_count INTEGER,              -- non-running activities (cycling, swimming, hiking, etc.)
    cross_train_min REAL,                   -- total cross-training duration
    -- Combined load
    total_load      REAL,                   -- all activity types
    total_activities INTEGER,
    acwr            REAL,                   -- Acute:Chronic Workload Ratio (this week / avg of prev 4 weeks). Safe: 0.8-1.3
    -- Recovery context
    avg_readiness   REAL,
    avg_sleep       REAL,
    avg_rhr         REAL,
    avg_hrv         REAL,
    weight_avg      REAL,
    -- Zone distribution by TIME (minutes), not count
    z1_min          REAL,
    z2_min          REAL,
    z3_min          REAL,
    z4_min          REAL,
    z5_min          REAL,
    z12_pct         REAL,                   -- (z1+z2 time) / total time — target: 80%
    z45_pct         REAL,                   -- (z4+z5 time) / total time — target: 20%
    -- Consistency
    training_days   INTEGER,               -- days with at least one activity
    consecutive_weeks_3plus INTEGER,        -- streak: consecutive weeks with 3+ runs
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ══════════════════════════════════════════════════
-- Views
-- ══════════════════════════════════════════════════

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

CREATE VIEW IF NOT EXISTS v_all_training AS
SELECT
    a.date, a.type, a.name, a.distance_km, a.duration_min,
    a.avg_hr, a.calories, a.training_load, a.subtype,
    h.resting_heart_rate, h.training_readiness, h.sleep_duration_hours
FROM activities a
LEFT JOIN daily_health h ON a.date = h.date
ORDER BY a.date DESC;
