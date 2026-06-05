"""Tests for the MCP coaching-context builders (mcp/server.py).

The server module loads config at import time and `mcp/` shadows the
installed `mcp` library name, so we path-load it once and monkeypatch the
module-level `config` to isolate the zone-model logic. The regression that
matters: the "IMPORTANT easy ceiling" line must reflect the ACTIVE zone
model — emitting the max-HR ceiling (134) while zone_model is 'lthr' would
make coaching flag legitimate Z2 easy runs (up to 153 at LTHR 172) as too
hard.
"""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = REPO_ROOT / "mcp" / "server.py"


@pytest.fixture(scope="module")
def server():
    spec = importlib.util.spec_from_file_location("fit_mcp_server", SERVER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE calibration (
            id INTEGER PRIMARY KEY AUTOINCREMENT, metric TEXT, value REAL,
            method TEXT, source_activity_id TEXT, confidence TEXT,
            date DATE, notes TEXT, active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP, flags TEXT DEFAULT '[]'
        );
        CREATE TABLE activities (
            id TEXT PRIMARY KEY, date DATE, type TEXT, vo2max REAL,
            distance_km REAL, duration_min REAL, avg_hr INTEGER, max_hr INTEGER,
            pace_sec_per_km REAL, name TEXT
        );
        CREATE TABLE activity_splits (
            activity_id TEXT, split_num INTEGER, pace_sec_per_km REAL
        );
        CREATE TABLE race_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, date DATE, distance_km REAL,
            result_time TEXT
        );
    """)
    # Recent LTHR calibration so it isn't flagged stale in unrelated assertions.
    c.execute(
        "INSERT INTO calibration (metric, value, method, confidence, date, active) "
        "VALUES ('lthr', 172, 'race_candidate', 'high', date('now','-10 days'), 1)"
    )
    c.commit()
    return c


LTHR_CONFIG = {
    "profile": {
        "max_hr": 192,
        "zone_model": "lthr",
        "zones_max_hr": {"z2": [115, 134], "z3": [134, 154], "z4": [154, 173]},
        "zones_lthr": {"z2_pct": [85, 89], "z4_pct": [95, 99]},
    }
}

MAXHR_CONFIG = {
    "profile": {
        "max_hr": 192,
        "zone_model": "max_hr",
        "zones_max_hr": {"z2": [115, 134], "z3": [134, 154], "z4": [154, 173]},
        "zones_lthr": {"z2_pct": [85, 89], "z4_pct": [95, 99]},
    }
}


def _profile_text(server, conn, monkeypatch, cfg):
    monkeypatch.setattr(server, "config", cfg)
    return "\n".join(server._ctx_profile(conn))


class TestZoneCeilingModelAware:
    def test_lthr_model_uses_lthr_ceiling(self, server, conn, monkeypatch):
        """zone_model=lthr → IMPORTANT line must say 153, not 134."""
        text = _profile_text(server, conn, monkeypatch, LTHR_CONFIG)
        important = [ln for ln in text.splitlines() if ln.startswith("IMPORTANT")][0]
        assert "153 bpm" in important
        assert "LTHR Z2 ceiling" in important

    def test_lthr_model_does_not_present_134_as_the_ceiling(self, server, conn, monkeypatch):
        """The max-HR ceiling (134) may appear as a contrast, never as THE ceiling."""
        text = _profile_text(server, conn, monkeypatch, LTHR_CONFIG)
        important = [ln for ln in text.splitlines() if ln.startswith("IMPORTANT")][0]
        # 134 should be framed as the rejected max-HR ceiling, not the rule.
        assert "stay below 134" not in important
        assert "NOT the max-HR ceiling (134)" in important

    def test_maxhr_model_uses_maxhr_ceiling(self, server, conn, monkeypatch):
        """zone_model=max_hr → ceiling is the max-HR Z2 upper (134)."""
        text = _profile_text(server, conn, monkeypatch, MAXHR_CONFIG)
        important = [ln for ln in text.splitlines() if ln.startswith("IMPORTANT")][0]
        assert "stay below 134 bpm" in important

    def test_lthr_zone_bounds_from_config_not_hardcoded(self, server, conn, monkeypatch):
        """Changing the config z2_pct must move the reported ceiling."""
        cfg = {
            "profile": {
                "max_hr": 192,
                "zone_model": "lthr",
                "zones_max_hr": {"z2": [115, 134], "z3": [134, 154], "z4": [154, 173]},
                # widen Z2 to 92% → ceiling = round(172*0.92) = 158
                "zones_lthr": {"z2_pct": [85, 92], "z4_pct": [95, 99]},
            }
        }
        text = _profile_text(server, conn, monkeypatch, cfg)
        important = [ln for ln in text.splitlines() if ln.startswith("IMPORTANT")][0]
        assert "158 bpm" in important

    def test_no_lthr_calibration_falls_back_to_maxhr(self, server, conn, monkeypatch):
        """zone_model=lthr but no LTHR row → can't use LTHR ceiling, use max-HR."""
        conn.execute("DELETE FROM calibration WHERE metric = 'lthr'")
        conn.commit()
        text = _profile_text(server, conn, monkeypatch, LTHR_CONFIG)
        important = [ln for ln in text.splitlines() if ln.startswith("IMPORTANT")][0]
        assert "stay below 134 bpm" in important


class TestZoneDistributionWindow:
    """The 'last 4 wks' zone line must average only the 4 most recent weeks —
    an ISO-week-string vs date('now') comparison used to silently widen this
    to ~6 months and inflate the Z4+Z5 share with old race/interval weeks.
    """

    def _conn(self):
        c = sqlite3.connect(":memory:")
        c.row_factory = sqlite3.Row
        c.executescript("""
            CREATE TABLE weekly_agg (week TEXT, z12_pct REAL, z45_pct REAL);
            CREATE TABLE training_phases (
                phase TEXT, name TEXT, start_date TEXT, end_date TEXT,
                status TEXT, z12_pct_target REAL);
            CREATE TABLE activities (
                id TEXT, date DATE, type TEXT, run_type TEXT,
                speed_per_bpm REAL, speed_per_bpm_z2 REAL);
        """)
        return c

    def test_window_excludes_old_high_hard_zone_weeks(self, server):
        c = self._conn()
        # 4 most recent weeks — almost no hard-zone time
        for wk, z12, z45 in [("2026-W20", 70, 0), ("2026-W21", 48, 0),
                             ("2026-W22", 75, 0), ("2026-W23", 100, 0)]:
            c.execute("INSERT INTO weekly_agg VALUES (?, ?, ?)", (wk, z12, z45))
        # Older race-season weeks heavy on Z4+Z5 — must NOT enter the average
        for wk in ["2025-W50", "2025-W51", "2025-W52", "2026-W01", "2026-W02"]:
            c.execute("INSERT INTO weekly_agg VALUES (?, 40, 40)", (wk,))
        c.commit()
        line = [l for l in server._ctx_training(c) if "Zone distribution" in l][0]
        assert "Z4+Z5=0.0%" in line       # recent reality
        assert "Z4+Z5=40" not in line     # not the 6-month artifact

    def test_skips_empty_current_week(self, server):
        """A null-zone current week shouldn't blank the average."""
        c = self._conn()
        c.execute("INSERT INTO weekly_agg VALUES ('2026-W23', NULL, NULL)")
        for wk, z12, z45 in [("2026-W19", 80, 5), ("2026-W20", 70, 10),
                             ("2026-W21", 60, 8), ("2026-W22", 72, 6)]:
            c.execute("INSERT INTO weekly_agg VALUES (?, ?, ?)", (wk, z12, z45))
        c.commit()
        line = [l for l in server._ctx_training(c) if "Zone distribution" in l][0]
        # avg of the 4 non-null weeks: z45 = (5+10+8+6)/4 = 7.25
        assert "Z4+Z5=7.2" in line or "Z4+Z5=7.3" in line


class TestFitnessAnchorLine:
    def test_anchor_line_present_with_gap(self, server, conn, monkeypatch):
        """A VDOT anchor + Garmin VO2max → anchor line with the gap."""
        # The standardized anchor reads a vdot calibration row, not a raw activity.
        conn.execute(
            "INSERT INTO calibration (metric, value, method, confidence, date, active, flags) "
            "VALUES ('vdot', 41, 'race_observation', 'low', date('now','-10 days'), 0, '[]')"
        )
        conn.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min, "
            "avg_hr, max_hr, pace_sec_per_km, name, vo2max) VALUES "
            "('a2', date('now','-1 days'), 'running', 8.0, 48.0, 140, 150, 360, 'easy', 49)"
        )
        conn.commit()
        text = _profile_text(server, conn, monkeypatch, LTHR_CONFIG)
        assert "Fitness anchor: VDOT 41" in text
        assert "Garmin VO2max 49" in text

    def test_no_anchor_prompts_time_trial(self, server, conn, monkeypatch):
        """No VDOT anchor but a Garmin estimate → nudge a race/effort to anchor."""
        conn.execute(
            "INSERT INTO activities (id, date, type, distance_km, duration_min, "
            "avg_hr, max_hr, pace_sec_per_km, name, vo2max) VALUES "
            "('a1', date('now','-2 days'), 'running', 6.0, 40.0, 140, 150, 400, 'easy', 49)"
        )
        conn.commit()
        text = _profile_text(server, conn, monkeypatch, LTHR_CONFIG)
        assert "Fitness anchor: none yet" in text
