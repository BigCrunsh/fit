"""Tests for fit/fitness.py — fitness profile, VDOT computation, trends."""

import sqlite3
from datetime import date, timedelta

import pytest

from fit.fitness import (
    compute_vdot_from_race,
    get_fitness_anchors,
    get_fitness_profile,
    inverse_vdot,
    vdot_to_race_time,
    _compute_trend,
    _compute_effective_vdot,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE activities (
            id TEXT PRIMARY KEY, date DATE, type TEXT, vo2max REAL,
            speed_per_bpm REAL, speed_per_bpm_z2 REAL, distance_km REAL,
            duration_min REAL, avg_hr INTEGER, hr_zone TEXT, splits_status TEXT,
            run_type TEXT, pace_sec_per_km REAL,
            name TEXT, subtype TEXT, max_hr INTEGER, avg_cadence REAL,
            elevation_gain_m REAL, calories INTEGER, aerobic_te REAL,
            training_load REAL, avg_stride_m REAL, avg_speed REAL,
            start_lat REAL, start_lon REAL, temp_at_start_c REAL,
            humidity_at_start_pct REAL, rpe INTEGER, srpe REAL,
            hr_zone_maxhr TEXT, hr_zone_lthr TEXT, effort_class TEXT,
            max_hr_used INTEGER, lthr_used INTEGER, fit_file_path TEXT
        );
        CREATE TABLE race_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, name TEXT,
            distance TEXT, distance_km REAL, status TEXT, target_time TEXT,
            result_time TEXT, result_pace REAL, activity_id TEXT,
            garmin_time TEXT, organizer TEXT, notes TEXT
        );
        CREATE TABLE activity_splits (
            activity_id TEXT, split_num INTEGER, distance_km REAL,
            time_sec REAL, pace_sec_per_km REAL, avg_hr REAL,
            avg_cadence REAL, elevation_gain_m REAL, avg_speed_m_s REAL,
            time_above_z2_ceiling_sec REAL, start_distance_m REAL, end_distance_m REAL,
            PRIMARY KEY (activity_id, split_num)
        );
        CREATE TABLE calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT, metric TEXT, value REAL,
            method TEXT, source_activity_id TEXT, confidence TEXT,
            date DATE, notes TEXT, active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, flags TEXT DEFAULT '[]'
        );
    """)
    return conn


# ── VDOT from Race Results ──


class TestVDOTFromRace:
    def test_5k_22min(self):
        """22:00 5K → VDOT ~44-45 (Daniels formula)."""
        vdot = compute_vdot_from_race(5.0, 22 * 60)
        assert vdot is not None
        assert 43 <= vdot <= 46

    def test_10k_45min(self):
        """45:00 10K → VDOT ~43-45."""
        vdot = compute_vdot_from_race(10.0, 45 * 60)
        assert vdot is not None
        assert 42 <= vdot <= 46

    def test_hm_1h49(self):
        """1:49:24 HM → VDOT ~40-42."""
        vdot = compute_vdot_from_race(21.1, 1 * 3600 + 49 * 60 + 24)
        assert vdot is not None
        assert 39 <= vdot <= 43

    def test_marathon_4h(self):
        """4:00:00 marathon → VDOT ~37-40 (formula underestimates marathon VDOT)."""
        vdot = compute_vdot_from_race(42.195, 4 * 3600)
        assert vdot is not None
        assert 36 <= vdot <= 41

    def test_cross_distance_consistency(self):
        """Same-fitness runner: 5K and HM VDOT should be within ~2 of each other."""
        # Daniels says VDOT 45 = 5K in 22:00, HM in 1:40:20
        vdot_5k = compute_vdot_from_race(5.0, 1320)
        vdot_hm = compute_vdot_from_race(21.1, 6020)
        assert abs(vdot_5k - vdot_hm) < 2.0

    def test_nonstandard_12k(self):
        vdot = compute_vdot_from_race(12.0, 70 * 60 + 33)
        assert vdot is not None
        assert 25 <= vdot <= 60

    def test_zero_distance(self):
        assert compute_vdot_from_race(0, 1200) is None

    def test_zero_time(self):
        assert compute_vdot_from_race(10, 0) is None


class TestVDOTToRaceTime:
    def test_vdot45_5k(self):
        """VDOT 45 → ~21-22 min 5K."""
        t = vdot_to_race_time(45, 5.0)
        assert t is not None
        assert 1260 <= t <= 1380  # 21:00 - 23:00

    def test_vdot45_hm(self):
        """VDOT 45 → ~1:35-1:45 HM."""
        t = vdot_to_race_time(45, 21.1)
        assert t is not None
        assert 5700 <= t <= 6300  # 1:35 - 1:45

    def test_zero_vdot(self):
        assert vdot_to_race_time(0, 10) is None


class TestInverseVDOT:
    def test_marathon_sub4(self):
        """Sub-4:00 marathon needs VDOT ~37-40."""
        vdot = inverse_vdot(4 * 3600, 42.195)
        assert vdot is not None
        assert 36 <= vdot <= 41

    def test_hm_sub147(self):
        """Sub-1:47 HM needs VDOT ~41-43."""
        vdot = inverse_vdot(1 * 3600 + 47 * 60, 21.1)
        assert vdot is not None
        assert 40 <= vdot <= 44

    def test_5k_sub22(self):
        """Sub-22:00 5K needs VDOT ~44-46."""
        vdot = inverse_vdot(22 * 60, 5.0)
        assert vdot is not None
        assert 43 <= vdot <= 46

    def test_inverse_equals_forward(self):
        """inverse_vdot is just compute_vdot_from_race."""
        forward = compute_vdot_from_race(10.0, 2700)
        inverse = inverse_vdot(2700, 10.0)
        assert forward == inverse

    def test_roundtrip(self):
        """VDOT → race time → VDOT should be consistent."""
        original_vdot = 45.0
        time = vdot_to_race_time(original_vdot, 10.0)
        recovered_vdot = compute_vdot_from_race(10.0, time)
        assert recovered_vdot is not None
        assert abs(recovered_vdot - original_vdot) < 1.0


# ── Effective VDOT ──


class TestEffectiveVDOT:
    def test_recent_race_preferred(self):
        """Recent race VDOT should be used directly (no Garmin blend)."""
        recent_date = (date.today() - timedelta(days=14)).isoformat()
        result = _compute_effective_vdot(49.0, 46.0, recent_date)
        assert result == 46.0  # Race VDOT used directly, Garmin ignored

    def test_stale_race_still_used_within_6mo(self):
        """Race VDOT within 6 months still preferred over Garmin."""
        date_4mo = (date.today() - timedelta(days=120)).isoformat()
        result = _compute_effective_vdot(49.0, 42.0, date_4mo)
        assert result == 42.0  # Race still within 6 months

    def test_very_stale_race_uses_discounted_garmin(self):
        """Race older than 6 months falls back to Garmin - 5."""
        stale_date = (date.today() - timedelta(days=200)).isoformat()
        result = _compute_effective_vdot(49.0, 42.0, stale_date)
        assert result == 44.0  # Garmin 49 - 5 = 44

    def test_no_race_uses_discounted_garmin(self):
        result = _compute_effective_vdot(49.0, None, None)
        assert result == 44.0  # Garmin 49 - 5 = 44

    def test_no_garmin_uses_race(self):
        recent_date = (date.today() - timedelta(days=7)).isoformat()
        result = _compute_effective_vdot(None, 46.0, recent_date)
        assert result == 46.0

    def test_nothing(self):
        result = _compute_effective_vdot(None, None, None)
        assert result is None


# ── Trend Computation ──


class TestTrend:
    def test_improving(self):
        base = date.today() - timedelta(days=42)
        vals = [((base + timedelta(days=i * 7)).isoformat(), 48 + i * 0.5) for i in range(7)]
        trend, rate = _compute_trend(vals)
        assert trend == "improving"
        assert rate > 0

    def test_declining(self):
        base = date.today() - timedelta(days=42)
        vals = [((base + timedelta(days=i * 7)).isoformat(), 50 - i * 0.5) for i in range(7)]
        trend, rate = _compute_trend(vals)
        assert trend == "declining"
        assert rate < 0

    def test_flat(self):
        base = date.today() - timedelta(days=42)
        vals = [((base + timedelta(days=i * 7)).isoformat(), 49.0) for i in range(7)]
        trend, rate = _compute_trend(vals)
        assert trend == "flat"

    def test_insufficient_data(self):
        vals = [("2026-04-01", 49.0), ("2026-04-02", 49.5)]
        trend, rate = _compute_trend(vals)
        assert trend == "insufficient_data"


# ── Full Profile ──


class TestFitnessProfile:
    def test_profile_with_data(self, db):
        base = date.today() - timedelta(days=28)
        for i in range(5):
            d = (base + timedelta(days=i * 7)).isoformat()
            db.execute("""
                INSERT INTO activities (id, date, type, vo2max, speed_per_bpm,
                    speed_per_bpm_z2, distance_km, duration_min, avg_hr)
                VALUES (?, ?, 'running', ?, ?, ?, 10.0, 55.0, 140)
            """, (f"r{i}", d, 48 + i * 0.3, 1.05 + i * 0.01, 0.95 + i * 0.01))
        db.commit()

        profile = get_fitness_profile(db)
        assert profile["aerobic"]["current_value"] is not None
        assert profile["economy"]["current_value"] is not None
        assert profile["garmin_vo2max"] is not None

    def test_profile_empty_db(self, db):
        profile = get_fitness_profile(db)
        assert profile["aerobic"]["trend"] == "insufficient_data"
        assert profile["economy"]["trend"] == "insufficient_data"
        assert profile["effective_vdot"] is None

    def test_profile_with_race(self, db):
        db.execute("""
            INSERT INTO race_calendar (date, name, distance, distance_km, status, result_time)
            VALUES ('2026-04-04', 'Test 10K', '10km', 10.0, 'completed', '0:45:00')
        """)
        db.commit()

        profile = get_fitness_profile(db)
        assert profile["race_vdot"] is not None
        assert 40 <= profile["race_vdot"] <= 50


# ── Fitness Anchors (training-or-race effort-based filter) ──


def _ins_activity(db, aid, days_ago, dist_km, dur_min, avg_hr,
                  rtype="running", name="test"):
    """Insert one running activity N days ago. Returns (date, activity_id)."""
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    pace = dur_min * 60 / dist_km if dist_km > 0 else None
    db.execute(
        "INSERT INTO activities (id, date, type, distance_km, duration_min, "
        "avg_hr, max_hr, name, pace_sec_per_km) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, d, rtype, dist_km, dur_min, avg_hr, avg_hr + 10, name, pace),
    )
    return d, aid


def _ins_splits(db, aid, paces):
    """Insert per-km splits with given paces (sec/km)."""
    for i, p in enumerate(paces, 1):
        db.execute(
            "INSERT INTO activity_splits (activity_id, split_num, pace_sec_per_km) "
            "VALUES (?, ?, ?)",
            (aid, i, p),
        )


class TestGetFitnessAnchors:
    """Filter activities by the physiological criteria for a VDOT anchor."""

    def test_no_lthr_returns_empty(self, db):
        """Without LTHR there's no criterion-2 threshold — return [], don't crash."""
        _ins_activity(db, "a1", 30, 10.0, 45.0, 180)
        db.commit()
        assert get_fitness_anchors(db) == []

    def test_qualifying_10k(self, db):
        """A 10K at avg HR above LTHR with no splits → returns one anchor."""
        _ins_activity(db, "a1", 30, 10.0, 45.0, 175, name="Hard 10K")
        db.commit()
        anchors = get_fitness_anchors(db, lthr=172)
        assert len(anchors) == 1
        assert anchors[0]["activity_id"] == "a1"
        assert anchors[0]["distance_km"] == 10.0
        assert anchors[0]["avg_hr"] == 175
        assert 40 <= anchors[0]["vdot"] <= 50
        assert anchors[0]["source"] == "training"  # no race_calendar row

    def test_excludes_below_lthr(self, db):
        """Tempo run at HR below LTHR is excluded (criterion 2)."""
        _ins_activity(db, "tempo", 14, 10.0, 56.0, 166)  # below LTHR=172
        db.commit()
        assert get_fitness_anchors(db, lthr=172) == []

    def test_excludes_too_short(self, db):
        """Sub-5km efforts excluded by default (formula too noisy)."""
        _ins_activity(db, "short", 7, 3.0, 14.0, 180)
        db.commit()
        assert get_fitness_anchors(db, lthr=172) == []

    def test_excludes_too_long(self, db):
        """Marathon-length runs excluded by default (glycogen-limited)."""
        _ins_activity(db, "mara", 60, 30.0, 180.0, 175)
        db.commit()
        assert get_fitness_anchors(db, lthr=172) == []

    def test_excludes_interval_workout(self, db):
        """Interval session (high pace CV) excluded by criterion 3."""
        _ins_activity(db, "intervals", 10, 8.0, 40.0, 178)
        # Alternating fast/slow: pace CV will be huge
        _ins_splits(db, "intervals", [240, 360, 240, 360, 240, 360, 240, 360])
        db.commit()
        assert get_fitness_anchors(db, lthr=172) == []

    def test_includes_consistent_splits(self, db):
        """Evenly-paced 10K is included (low pace CV)."""
        _ins_activity(db, "even", 20, 10.0, 45.0, 178)
        # Roughly even — ~270 sec/km with tiny variation
        _ins_splits(db, "even", [268, 270, 272, 270, 268, 270, 272, 270, 270, 270])
        db.commit()
        anchors = get_fitness_anchors(db, lthr=172)
        assert len(anchors) == 1
        assert anchors[0]["confidence"] == "high"  # tight CV + 3.5% margin

    def test_marks_race_source_when_calendar_match(self, db):
        """If race_calendar has a row on the same date, source='race'."""
        d, aid = _ins_activity(db, "race10k", 90, 10.0, 45.0, 175)
        db.execute(
            "INSERT INTO race_calendar (date, name, distance_km, status, result_time) "
            "VALUES (?, 'Real Race', 10.0, 'completed', '0:45:00')",
            (d,),
        )
        db.commit()
        anchors = get_fitness_anchors(db, lthr=172)
        assert len(anchors) == 1
        assert anchors[0]["source"] == "race"

    def test_outside_window_excluded(self, db):
        """Activities older than `days` are excluded."""
        _ins_activity(db, "old", 400, 10.0, 45.0, 178)
        db.commit()
        assert get_fitness_anchors(db, lthr=172, days=365) == []

    def test_sorted_by_vdot_desc(self, db):
        """Best fitness signal first — VDOT-descending."""
        _ins_activity(db, "slow", 30, 10.0, 55.0, 175)  # ~VDOT 35
        _ins_activity(db, "fast", 60, 10.0, 40.0, 175)  # ~VDOT 50
        db.commit()
        anchors = get_fitness_anchors(db, lthr=172)
        assert [a["activity_id"] for a in anchors] == ["fast", "slow"]

    def test_low_confidence_at_lthr_threshold(self, db):
        """Avg HR exactly at LTHR with no splits → medium confidence."""
        _ins_activity(db, "at_lthr", 10, 10.0, 45.0, 172)
        db.commit()
        anchors = get_fitness_anchors(db, lthr=172)
        assert len(anchors) == 1
        assert anchors[0]["confidence"] == "medium"
        assert anchors[0]["hr_margin_pct"] == 0.0

    def test_pace_cv_borderline_keeps(self, db):
        """Pace CV near but below the 15% exclusion threshold still qualifies."""
        _ins_activity(db, "borderline", 20, 10.0, 50.0, 178)
        # CV ~11.6%: under 15% exclusion, but over 6% "high" threshold
        _ins_splits(db, "borderline",
                    [240, 330, 260, 320, 290, 340, 240, 290, 310, 310])
        db.commit()
        anchors = get_fitness_anchors(db, lthr=172)
        assert len(anchors) == 1
        assert anchors[0]["confidence"] in ("medium", "low")
