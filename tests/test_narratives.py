"""Tests for narratives module: trend badges, why connectors, WoW context,
race countdown, walk-break detection, and Z2 remediation."""

import sqlite3
from datetime import date, timedelta

import pytest

from fit.narratives import (
    detect_walk_break_need,
    generate_race_countdown,
    generate_trend_badges,
    generate_why_connectors,
    generate_wow_context,
    generate_wow_sentence,
    generate_z2_remediation,
)


@pytest.fixture
def db():
    """In-memory DB with full schema for narrative tests."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")

    conn.executescript("""
        CREATE TABLE activities (
            id TEXT PRIMARY KEY, date DATE, type TEXT, name TEXT,
            distance_km REAL, duration_min REAL, pace_sec_per_km REAL,
            avg_hr INTEGER, speed_per_bpm REAL, run_type TEXT,
            temp_at_start_c REAL, humidity_at_start_pct REAL,
            training_load REAL, hr_zone TEXT, splits_status TEXT,
            max_hr INTEGER, rpe INTEGER, srpe REAL,
            hr_zone_maxhr TEXT, hr_zone_lthr TEXT, effort_class TEXT,
            speed_per_bpm_z2 REAL, max_hr_used INTEGER, lthr_used INTEGER,
            subtype TEXT, avg_cadence REAL, elevation_gain_m REAL,
            calories INTEGER, vo2max REAL, aerobic_te REAL,
            avg_stride_m REAL, avg_speed REAL, start_lat REAL, start_lon REAL,
            fit_file_path TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE daily_health (
            date DATE PRIMARY KEY, training_readiness INTEGER,
            sleep_duration_hours REAL, resting_heart_rate INTEGER,
            hrv_last_night REAL, avg_spo2 REAL,
            total_steps INTEGER, total_distance_m REAL,
            total_calories INTEGER, active_calories INTEGER,
            max_heart_rate INTEGER, min_heart_rate INTEGER,
            avg_stress_level INTEGER, max_stress_level INTEGER,
            body_battery_high INTEGER, body_battery_low INTEGER,
            deep_sleep_hours REAL, light_sleep_hours REAL,
            rem_sleep_hours REAL, awake_hours REAL, deep_sleep_pct REAL,
            readiness_level TEXT, hrv_weekly_avg REAL, hrv_status TEXT,
            avg_respiration REAL
        );
        CREATE TABLE checkins (
            date DATE PRIMARY KEY, hydration TEXT, alcohol REAL DEFAULT 0,
            alcohol_detail TEXT, legs TEXT, eating TEXT,
            water_liters REAL, energy TEXT, rpe INTEGER,
            sleep_quality TEXT, notes TEXT
        );
        CREATE TABLE body_comp (
            date DATE PRIMARY KEY, weight_kg REAL NOT NULL,
            body_fat_pct REAL, muscle_mass_kg REAL, visceral_fat REAL,
            bmi REAL, source TEXT DEFAULT 'fitdays'
        );
        CREATE TABLE weekly_agg (
            week TEXT PRIMARY KEY, run_count INTEGER, run_km REAL,
            run_avg_pace REAL, run_avg_hr REAL, longest_run_km REAL,
            run_avg_cadence REAL, easy_run_count INTEGER,
            quality_session_count INTEGER, cross_train_count INTEGER,
            cross_train_min REAL, total_load REAL, total_activities INTEGER,
            acwr REAL, avg_readiness REAL, avg_sleep REAL, avg_rhr REAL,
            avg_hrv REAL, weight_avg REAL,
            z1_min REAL, z2_min REAL, z3_min REAL, z4_min REAL, z5_min REAL,
            z12_pct REAL, z45_pct REAL, training_days INTEGER,
            consecutive_weeks_3plus INTEGER, monotony REAL, strain REAL,
            cycling_km REAL, cycling_min REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, type TEXT,
            target_time TEXT, target_pace REAL, target_value REAL,
            target_unit TEXT, target_date DATE, active BOOLEAN DEFAULT 1,
            race_id INTEGER
        );
        CREATE TABLE training_phases (
            id INTEGER PRIMARY KEY AUTOINCREMENT, goal_id INTEGER,
            phase TEXT, name TEXT, start_date DATE, end_date DATE,
            z12_pct_target REAL, z45_pct_target REAL,
            weekly_km_min REAL, weekly_km_max REAL,
            targets TEXT, actuals TEXT, status TEXT DEFAULT 'planned',
            notes TEXT, created_at DATETIME, updated_at DATETIME
        );
        CREATE TABLE race_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, name TEXT,
            distance TEXT, distance_km REAL, status TEXT,
            target_time TEXT, result_time TEXT, garmin_time TEXT,
            result_pace REAL, activity_id TEXT, organizer TEXT
        );
    """)
    return conn


# ── Trend Badges ──


class TestTrendBadges:
    def _insert_weeks(self, db, count=8):
        """Insert count weeks of weekly_agg data."""
        today = date.today()
        for i in range(count):
            d = today - timedelta(weeks=i)
            iso = d.isocalendar()
            week_str = f"{iso.year}-W{iso.week:02d}"
            db.execute("""
                INSERT OR IGNORE INTO weekly_agg
                    (week, run_count, run_km, z12_pct, total_load, z1_min,
                     z2_min, z3_min, z4_min, z5_min, z45_pct, training_days,
                     consecutive_weeks_3plus)
                VALUES (?, 4, ?, 85, 300, 10, 50, 8, 3, 0, 5, 5, ?)
            """, (week_str, 30 + i, count - i))
        db.commit()

    def test_insufficient_data_returns_fallback(self, db):
        """With < 4 weeks, should return fallback badge."""
        self._insert_weeks(db, count=2)
        badges = generate_trend_badges(db)
        assert len(badges) == 1
        assert badges[0]["metric"] == "insufficient_data"
        assert badges[0]["color"] == "gray"
        assert "2 more week" in badges[0]["value"]

    def test_sufficient_data_returns_multiple_badges(self, db):
        """With 4+ weeks and activity data, should return real badges."""
        self._insert_weeks(db, count=8)
        # Insert activities for efficiency and VO2max badges
        today = date.today()
        for i in range(56):
            d = (today - timedelta(days=i)).isoformat()
            eff = 0.045 if i < 28 else 0.040
            db.execute("""
                INSERT INTO activities (id, date, type, speed_per_bpm_z2, vo2max)
                VALUES (?, ?, 'running', ?, ?)
            """, (f"a{i}", d, eff, 52 if i < 28 else 50))
        db.commit()

        badges = generate_trend_badges(db)
        metrics = [b["metric"] for b in badges]
        # Should have at least Z2 time and Volume badges
        assert "Z2 time" in metrics
        assert "Volume" in metrics

    def test_z2_trend_shows_change(self, db):
        """Z2 badge should show trend direction (pp change), not absolute value."""
        self._insert_weeks(db, count=8)
        badges = generate_trend_badges(db)
        z2_badge = next((b for b in badges if b["metric"] == "Z2 time"), None)
        assert z2_badge is not None
        assert "pp" in z2_badge["value"]

    def test_volume_badge_shows_change(self, db):
        """Volume badge should show week-over-week % change."""
        self._insert_weeks(db, count=5)
        badges = generate_trend_badges(db)
        vol_badge = next((b for b in badges if b["metric"] == "Volume"), None)
        assert vol_badge is not None
        assert "%" in vol_badge["value"]


# ── Why Connectors ──


class TestWhyConnectors:
    def test_insufficient_data_returns_message(self, db):
        """With < 10 runs paired with checkins, should return insufficient_data."""
        result = generate_why_connectors(db)
        assert len(result) == 1
        assert result[0]["pattern"] == "insufficient_data"

    def test_sleep_impact_detected(self, db):
        """When worst runs follow poor sleep, should detect sleep_impact pattern."""
        today = date.today()
        # Insert 15 runs with checkin data (need >=10 paired)
        for i in range(15):
            d = (today - timedelta(days=i * 2)).isoformat()
            prev_d = (today - timedelta(days=i * 2 + 1)).isoformat()
            # First 5 runs are the worst (lowest speed_per_bpm)
            eff = 0.020 + (i * 0.003) if i < 5 else 0.045
            sleep_q = "Poor" if i < 3 else "Good"
            db.execute("""
                INSERT INTO activities (id, date, type, speed_per_bpm, name)
                VALUES (?, ?, 'running', ?, 'Run')
            """, (f"a{i}", d, eff))
            db.execute("""
                INSERT OR IGNORE INTO checkins (date, sleep_quality, alcohol)
                VALUES (?, ?, 0)
            """, (prev_d, sleep_q))
            db.execute("""
                INSERT OR IGNORE INTO daily_health (date, sleep_duration_hours)
                VALUES (?, ?)
            """, (prev_d, 5.0 if i < 3 else 8.0))
        db.commit()

        result = generate_why_connectors(db)
        patterns = [c["pattern"] for c in result]
        assert "sleep_impact" in patterns

    def test_no_pattern_when_data_is_clean(self, db):
        """When worst runs have no preceding poor data, should return empty list."""
        today = date.today()
        for i in range(15):
            d = (today - timedelta(days=i * 2)).isoformat()
            prev_d = (today - timedelta(days=i * 2 + 1)).isoformat()
            eff = 0.035 + (i * 0.001)
            db.execute("""
                INSERT INTO activities (id, date, type, speed_per_bpm, name)
                VALUES (?, ?, 'running', ?, 'Run')
            """, (f"a{i}", d, eff))
            db.execute("""
                INSERT OR IGNORE INTO checkins (date, sleep_quality, alcohol)
                VALUES (?, 'Good', 0)
            """, (prev_d,))
            db.execute("""
                INSERT OR IGNORE INTO daily_health (date, sleep_duration_hours)
                VALUES (?, 8.0)
            """, (prev_d,))
        db.commit()

        result = generate_why_connectors(db)
        # Should have no pattern connectors (all clean data)
        patterns = [c["pattern"] for c in result if c.get("pattern") != "insufficient_data"]
        assert "sleep_impact" not in patterns
        assert "alcohol_impact" not in patterns


# ── WoW Context ──


class TestWoWContext:
    def test_insufficient_weeks_returns_none(self, db):
        """With < 2 weeks, should return None."""
        result = generate_wow_context(db)
        assert result is None

    def test_volume_increase_with_phase_warning(self, db):
        """Volume increase exceeding phase target should produce warning."""
        today = date.today()
        iso_this = today.isocalendar()
        iso_last = (today - timedelta(weeks=1)).isocalendar()
        this_week = f"{iso_this.year}-W{iso_this.week:02d}"
        last_week = f"{iso_last.year}-W{iso_last.week:02d}"

        db.execute("""
            INSERT INTO weekly_agg (week, run_count, run_km, z12_pct)
            VALUES (?, 4, 35, 85)
        """, (this_week,))
        db.execute("""
            INSERT INTO weekly_agg (week, run_count, run_km, z12_pct)
            VALUES (?, 4, 25, 82)
        """, (last_week,))
        # Active phase with 10% max ramp
        db.execute("""
            INSERT INTO training_phases (goal_id, phase, name, start_date,
                z12_pct_target, weekly_km_min, weekly_km_max,
                targets, status)
            VALUES (1, 'Phase 1', 'Base', '2026-01-01', 80, 20, 30,
                '{"max_volume_increase_pct": 10}', 'active')
        """)
        db.commit()

        result = generate_wow_context(db)
        assert result is not None
        assert result["volume_change_km"] == 10
        assert result["phase_warning"] is not None
        assert "40%" in result["phase_warning"]  # 10km/25km = 40%

    def test_normal_volume_no_warning(self, db):
        """Volume within limits should not trigger warning."""
        today = date.today()
        iso_this = today.isocalendar()
        iso_last = (today - timedelta(weeks=1)).isocalendar()
        this_week = f"{iso_this.year}-W{iso_this.week:02d}"
        last_week = f"{iso_last.year}-W{iso_last.week:02d}"

        db.execute("""
            INSERT INTO weekly_agg (week, run_count, run_km, z12_pct)
            VALUES (?, 4, 26, 85)
        """, (this_week,))
        db.execute("""
            INSERT INTO weekly_agg (week, run_count, run_km, z12_pct)
            VALUES (?, 4, 25, 82)
        """, (last_week,))
        db.commit()

        result = generate_wow_context(db)
        assert result is not None
        assert result["phase_warning"] is None


# ── WoW Sentence (Rolling) ──


class TestWoWSentence:
    def test_rolling_input_produces_deltas(self, db):
        """Rolling 7d dicts passed directly produce correct volume delta."""
        current = {"run_km": 30, "run_count": 4, "z12_pct": 85}
        previous = {"run_km": 20, "run_count": 3, "z12_pct": 80}
        result = generate_wow_sentence(db, current=current, previous=previous)
        assert result is not None
        assert "Volume up 50%" in result
        assert "30km from 20km" in result
        assert "4 runs" in result

    def test_rolling_input_volume_down(self, db):
        """Volume decrease is reported correctly."""
        current = {"run_km": 10, "run_count": 2, "z12_pct": 90}
        previous = {"run_km": 25, "run_count": 4, "z12_pct": 85}
        result = generate_wow_sentence(db, current=current, previous=previous)
        assert "Volume down 60%" in result
        assert "10km from 25km" in result

    def test_rolling_input_zone_compliance_flip(self, db):
        """Zone compliance flipping from low to high produces special message."""
        current = {"run_km": 20, "run_count": 3, "z12_pct": 85}
        previous = {"run_km": 20, "run_count": 3, "z12_pct": 40}
        result = generate_wow_sentence(db, current=current, previous=previous)
        assert "first truly easy week" in result

    def test_no_previous_runs(self, db):
        """Zero previous volume is handled gracefully."""
        current = {"run_km": 15, "run_count": 2, "z12_pct": 80}
        previous = {"run_km": 0, "run_count": 0, "z12_pct": None}
        result = generate_wow_sentence(db, current=current, previous=previous)
        assert "15km" in result
        assert "no runs last period" in result

    def test_fallback_to_weekly_agg(self, db):
        """Without rolling input, falls back to weekly_agg."""
        result = generate_wow_sentence(db)
        assert result is None  # no weekly_agg data

    def test_fallback_with_weekly_data(self, db):
        """Falls back to weekly_agg when no rolling dicts provided."""
        today = date.today()
        iso_this = today.isocalendar()
        iso_last = (today - timedelta(weeks=1)).isocalendar()
        db.execute(
            "INSERT INTO weekly_agg (week, run_count, run_km, z12_pct, acwr) "
            "VALUES (?, 4, 30, 85, 1.1)",
            (f"{iso_this.year}-W{iso_this.week:02d}",),
        )
        db.execute(
            "INSERT INTO weekly_agg (week, run_count, run_km, z12_pct, acwr) "
            "VALUES (?, 3, 25, 80, 1.0)",
            (f"{iso_last.year}-W{iso_last.week:02d}",),
        )
        db.commit()
        result = generate_wow_sentence(db)
        assert result is not None
        assert "Volume up" in result


# ── Race Countdown ──


class TestRaceCountdown:
    def test_no_race_returns_none(self, db):
        """No upcoming race should return None."""
        result = generate_race_countdown(db)
        assert result is None

    def test_far_race_no_taper(self, db):
        """Race > 21 days away should not have taper rules."""
        race_date = (date.today() + timedelta(days=60)).isoformat()
        db.execute("""
            INSERT INTO race_calendar (date, name, distance, status)
            VALUES (?, 'Berlin Marathon', 'Marathon', 'registered')
        """, (race_date,))
        db.commit()

        result = generate_race_countdown(db)
        assert result is not None
        assert result["days_remaining"] == 60
        assert result["taper_rules"] is None

    def test_taper_period_returns_rules(self, db):
        """Race <= 21 days away should include taper rules."""
        race_date = (date.today() + timedelta(days=10)).isoformat()
        db.execute("""
            INSERT INTO race_calendar (date, name, distance, status)
            VALUES (?, 'Berlin Marathon', 'Marathon', 'registered')
        """, (race_date,))
        db.commit()

        result = generate_race_countdown(db)
        assert result is not None
        assert result["days_remaining"] == 10
        assert result["taper_rules"] is not None
        assert "50%" in result["taper_rules"]


# ── Walk-Break Detection ──


class TestWalkBreakDetection:
    def _insert_z2_runs(self, db, drift=False):
        """Insert Z2 runs with or without drift."""
        today = date.today()
        for i in range(10):
            d = (today - timedelta(days=i * 3)).isoformat()
            dist = 4.0 if i % 2 == 0 else 8.0
            # If drift: long runs have lower efficiency
            if drift and dist >= 5:
                eff = 0.030
            else:
                eff = 0.045
            db.execute("""
                INSERT INTO activities (id, date, type, distance_km,
                    duration_min, pace_sec_per_km, avg_hr, speed_per_bpm,
                    hr_zone)
                VALUES (?, ?, 'running', ?, 50, 330, 140, ?, 'Z2')
            """, (f"z2_{i}", d, dist, eff))
        db.commit()

    def test_no_drift_returns_none(self, db):
        """When efficiency is consistent, should return None."""
        today = date.today()
        for i in range(10):
            d = (today - timedelta(days=i * 3)).isoformat()
            dist = 4.0 if i % 2 == 0 else 8.0
            db.execute("""
                INSERT INTO activities (id, date, type, distance_km,
                    duration_min, pace_sec_per_km, avg_hr, speed_per_bpm,
                    hr_zone)
                VALUES (?, ?, 'running', ?, 50, 330, 140, 0.045, 'Z2')
            """, (f"z2_{i}", d, dist))
        db.commit()

        result = detect_walk_break_need(db)
        assert result is None or result["status"] == "graduated"

    def test_drift_detected(self, db):
        """When long runs are less efficient, should suggest walk breaks."""
        self._insert_z2_runs(db, drift=True)
        result = detect_walk_break_need(db)
        assert result is not None
        assert result["status"] == "suggested"
        assert result["drift_pct"] > 5

    def test_insufficient_data_returns_none(self, db):
        """With < 3 Z2 runs, should return None."""
        today = date.today().isoformat()
        db.execute("""
            INSERT INTO activities (id, date, type, distance_km,
                duration_min, pace_sec_per_km, avg_hr, speed_per_bpm,
                hr_zone)
            VALUES ('z2_1', ?, 'running', 8.0, 50, 330, 140, 0.045, 'Z2')
        """, (today,))
        db.commit()

        result = detect_walk_break_need(db)
        assert result is None


# ── Z2 Remediation ──


class TestZ2Remediation:
    def test_insufficient_weeks_returns_none(self, db):
        """With < 3 weeks of data, should return None."""
        config = {"profile": {"zones_max_hr": {"z2": [115, 134]}}}
        result = generate_z2_remediation(db, config)
        assert result is None

    def test_non_compliant_3_weeks(self, db):
        """3 consecutive weeks below 50% Z2 should trigger remediation."""
        today = date.today()
        for i in range(4):
            d = today - timedelta(weeks=i)
            iso = d.isocalendar()
            week_str = f"{iso.year}-W{iso.week:02d}"
            db.execute("""
                INSERT INTO weekly_agg (week, run_count, run_km, z12_pct)
                VALUES (?, 4, 25, ?)
            """, (week_str, 30 + i))  # all below 50
        db.commit()

        config = {"profile": {"zones_max_hr": {"z2": [115, 134]}}}
        result = generate_z2_remediation(db, config)
        assert result is not None
        assert result["status"] == "remediation"
        assert result["low_weeks"] == 3
        assert result["hr_ceiling"] == 134

    def test_compliant_weeks_returns_none(self, db):
        """Weeks with >= 50% compliance should not trigger remediation."""
        today = date.today()
        for i in range(4):
            d = today - timedelta(weeks=i)
            iso = d.isocalendar()
            week_str = f"{iso.year}-W{iso.week:02d}"
            db.execute("""
                INSERT INTO weekly_agg (week, run_count, run_km, z12_pct)
                VALUES (?, 4, 25, 85)
            """, (week_str,))
        db.commit()

        config = {"profile": {"zones_max_hr": {"z2": [115, 134]}}}
        result = generate_z2_remediation(db, config)
        assert result is None
