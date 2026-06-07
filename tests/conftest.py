"""Shared test fixtures for the fit test suite."""

import os
import tempfile
from pathlib import Path

import pytest

# Resolve config.yaml's ${FIT_*} placeholders with test defaults at import time.
# config.yaml is a template normally filled by config.local.yaml or the environment;
# tests that load the real config (CLI, report, and the module-scoped MCP server
# fixture, which loads config at *import* time) would otherwise raise on a fresh
# checkout with neither present (e.g. CI). Set at module level — before any fixture
# of any scope or collection runs — so even import-time config loads resolve.
# `setdefault` respects a real env var if the developer has one, and the
# placeholder-raising tests use their own distinct var names, so they're unaffected.
# This keeps the suite hermetic without weakening the production "raise on unset" guard.
os.environ.setdefault("FIT_USER_NAME", "Test Athlete")
os.environ.setdefault("FIT_USER_AGE", "35")
os.environ.setdefault("FIT_USER_MAX_HR", "190")
os.environ.setdefault("FIT_LAT", "52.52")
os.environ.setdefault("FIT_LON", "13.40")


@pytest.fixture
def config():
    """Sample config with standard 5-zone model."""
    return {
        "profile": {
            "name": "Test Runner",
            "max_hr": 192,
            "zone_model": "max_hr",
            "zones_max_hr": {
                "z1": [0, 115], "z2": [115, 134], "z3": [134, 154],
                "z4": [154, 173], "z5": [173, 200],
            },
            "zones_lthr": {
                "z1_pct": [0, 85], "z2_pct": [85, 89], "z3_pct": [90, 94],
                "z4_pct": [95, 99], "z5_pct": [100, 106],
            },
            "location": {"city": "Berlin", "lat": 52.52, "lon": 13.405},
        },
        "sync": {
            "garmin_token_dir": "~/.fit/garmin-tokens/",
            "db_path": "",  # set per test
        },
        "analysis": {
            "speed_per_bpm_hr_range": [115, 134],
            "acwr_safe_range": [0.8, 1.3],
            "acwr_danger_threshold": 1.5,
            "low_cadence_threshold": 165,
        },
    }


@pytest.fixture
def db(config):
    """In-memory SQLite DB with schema applied."""
    with tempfile.TemporaryDirectory() as tmpdir:
        config["sync"]["db_path"] = f"{tmpdir}/test.db"
        from fit.db import get_db
        conn = get_db(config, migrations_dir=Path(__file__).parent.parent / "migrations")
        yield conn
        conn.close()
