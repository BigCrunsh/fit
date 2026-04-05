-- Correlation results and real-time alerts

CREATE TABLE IF NOT EXISTS correlations (
    metric_pair     TEXT PRIMARY KEY,       -- "alcohol_lag1_hrv", "weight_weekly_rpe"
    lag_days        INTEGER DEFAULT 0,
    spearman_r      REAL,
    pearson_r       REAL,
    p_value         REAL,
    sample_size     INTEGER,
    confidence      TEXT,                   -- high / moderate / low
    status          TEXT DEFAULT 'computed', -- computed / insufficient_data
    last_computed   DATETIME,
    data_count_at_compute INTEGER
);

CREATE TABLE IF NOT EXISTS alerts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE NOT NULL,
    type            TEXT NOT NULL,           -- all_runs_too_hard / volume_ramp / readiness_gate / alcohol_hrv / long_run_projection
    message         TEXT NOT NULL,
    data_context    TEXT,                    -- JSON with supporting data
    acknowledged    BOOLEAN DEFAULT 0,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filename        TEXT NOT NULL,
    file_hash       TEXT,
    row_count       INTEGER,
    rows_imported   INTEGER,
    source_type     TEXT NOT NULL,           -- weight_csv / runna_plan
    import_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
