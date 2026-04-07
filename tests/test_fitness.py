"""Tests for fit/fitness.py — fitness profile, VDOT computation, trends."""

import sqlite3
from datetime import date, timedelta

import pytest

from fit.fitness import (
    compute_vdot_from_race,
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
