-- Race calendar: explicit registry of race events
-- Matched to activities by date. Unmatched = upcoming or missed.
-- Activities NOT in this table are training runs.

CREATE TABLE IF NOT EXISTS race_calendar (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    date            DATE NOT NULL,
    name            TEXT NOT NULL,
    organizer       TEXT,
    distance        TEXT NOT NULL,           -- "5km", "10km", "Halbmarathon", "Marathon"
    distance_km     REAL,                    -- numeric: 5, 10, 21.1, 42.195
    status          TEXT DEFAULT 'planned',  -- planned / registered / completed / dns / dnf
    target_time     TEXT,                    -- "0:24:00", "1:45:00", "3:59:59"
    result_time     TEXT,                    -- actual finish time
    result_pace     REAL,                    -- sec/km
    activity_id     TEXT,                    -- FK to activities.id (matched after race)
    notes           TEXT,
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_race_calendar_date ON race_calendar(date);
