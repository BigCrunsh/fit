"""Migration 008: activity_splits table + fit_file_path/splits_status on activities."""


def run(conn):
    conn.execute("""
        CREATE TABLE activity_splits (
            activity_id TEXT NOT NULL REFERENCES activities(id),
            split_num INTEGER NOT NULL,
            distance_km REAL,
            time_sec REAL,
            pace_sec_per_km REAL,
            avg_hr REAL,
            avg_cadence REAL,
            elevation_gain_m REAL,
            avg_speed_m_s REAL,
            time_above_z2_ceiling_sec REAL,
            start_distance_m REAL,
            end_distance_m REAL,
            PRIMARY KEY (activity_id, split_num)
        )
    """)
    conn.execute("CREATE INDEX idx_splits_activity ON activity_splits(activity_id)")
    conn.execute("ALTER TABLE activities ADD COLUMN fit_file_path TEXT")
    conn.execute("ALTER TABLE activities ADD COLUMN splits_status TEXT")
