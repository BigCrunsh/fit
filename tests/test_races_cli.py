"""Tests for `fit races` display + `fit races set-result`."""

from click.testing import CliRunner

import fit.cli as cli
from fit.cli import main
from fit.db import get_db


def _patch_conn(monkeypatch, config):
    """Point cli._conn at the same temp DB the `db` fixture created."""
    monkeypatch.setattr(cli, "_conn",
                        lambda: get_db(config, migrations_dir=cli.MIGRATIONS_DIR))


def _seed_completed_race(db, *, name="Müggelturm HM", distance_km=21.1,
                         result_time=None, garmin_time="2:01:48", activity_id="a1"):
    db.execute(
        "INSERT INTO activities (id, date, type, name, distance_km, duration_min, avg_hr) "
        "VALUES (?, '2026-03-22', 'running', ?, ?, 120, 173)",
        (activity_id, name, distance_km),
    )
    db.execute(
        "INSERT INTO race_calendar (date, name, distance, distance_km, status, "
        "activity_id, result_time, garmin_time) "
        "VALUES ('2026-03-22', ?, ?, ?, 'completed', ?, ?, ?)",
        (name, f"{distance_km:g}km", distance_km, activity_id, result_time, garmin_time),
    )
    db.commit()
    return db.execute("SELECT id FROM race_calendar WHERE name = ?", (name,)).fetchone()[0]


class TestRacesList:
    def test_shows_official_and_watch_columns(self, db, config, monkeypatch):
        _seed_completed_race(db, garmin_time="2:01:48")  # no official time
        _patch_conn(monkeypatch, config)
        result = CliRunner().invoke(main, ["races"])
        assert result.exit_code == 0
        assert "Official" in result.output and "Watch" in result.output

    def test_warns_about_missing_official_time(self, db, config, monkeypatch):
        _seed_completed_race(db, result_time=None, garmin_time="2:01:48")
        _patch_conn(monkeypatch, config)
        result = CliRunner().invoke(main, ["races"])
        assert "missing an official time" in result.output


class TestSetResult:
    def test_sets_official_time(self, db, config, monkeypatch):
        rid = _seed_completed_race(db, result_time=None)
        _patch_conn(monkeypatch, config)
        result = CliRunner().invoke(main, ["races", "set-result", str(rid), "1:50:00"])
        assert result.exit_code == 0
        stored = db.execute("SELECT result_time FROM race_calendar WHERE id = ?", (rid,)).fetchone()[0]
        assert stored == "1:50:00"

    def test_clear_official_time(self, db, config, monkeypatch):
        rid = _seed_completed_race(db, result_time="1:50:00")
        _patch_conn(monkeypatch, config)
        result = CliRunner().invoke(main, ["races", "set-result", str(rid), "clear"])
        assert result.exit_code == 0
        assert db.execute("SELECT result_time FROM race_calendar WHERE id = ?", (rid,)).fetchone()[0] is None

    def test_rejects_bad_time_format(self, db, config, monkeypatch):
        rid = _seed_completed_race(db, result_time=None)
        _patch_conn(monkeypatch, config)
        result = CliRunner().invoke(main, ["races", "set-result", str(rid), "ninety"])
        assert result.exit_code == 1
        assert "isn't a valid time" in result.output
        # unchanged
        assert db.execute("SELECT result_time FROM race_calendar WHERE id = ?", (rid,)).fetchone()[0] is None

    def test_unknown_id_errors(self, db, config, monkeypatch):
        _patch_conn(monkeypatch, config)
        result = CliRunner().invoke(main, ["races", "set-result", "999999", "1:50:00"])
        assert result.exit_code == 1
        assert "No race with id" in result.output

    def test_accepts_mmss_format(self, db, config, monkeypatch):
        rid = _seed_completed_race(db, name="10K", distance_km=10.0, result_time=None)
        _patch_conn(monkeypatch, config)
        result = CliRunner().invoke(main, ["races", "set-result", str(rid), "42:30"])
        assert result.exit_code == 0
        assert db.execute("SELECT result_time FROM race_calendar WHERE id = ?", (rid,)).fetchone()[0] == "42:30"
