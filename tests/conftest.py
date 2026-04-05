"""Shared test fixtures for the fit test suite."""

import tempfile
from pathlib import Path

import pytest


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
