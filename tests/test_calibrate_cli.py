"""`fit calibrate` — including --date back-dating for historical corrections."""

from click.testing import CliRunner

import fit.cli as cli
from fit.cli import main
from fit.db import get_db


def _patch_conn(monkeypatch, config):
    monkeypatch.setattr(cli, "_conn",
                        lambda: get_db(config, migrations_dir=cli.MIGRATIONS_DIR))


class TestCalibrateDate:
    def test_backdates_calibration(self, db, config, monkeypatch):
        _patch_conn(monkeypatch, config)
        r = CliRunner().invoke(main, ["calibrate", "vdot", "38", "--date", "2025-01-01"])
        assert r.exit_code == 0, r.output
        row = db.execute(
            "SELECT value, date, method FROM calibration WHERE metric='vdot'").fetchone()
        assert row["date"] == "2025-01-01"
        assert row["value"] == 38.0 and row["method"] == "manual"
        # Back-dating nudges a reclassify of that window.
        assert "recompute --force" in r.output

    def test_defaults_to_today(self, db, config, monkeypatch):
        from datetime import date
        _patch_conn(monkeypatch, config)
        r = CliRunner().invoke(main, ["calibrate", "vdot", "38"])
        assert r.exit_code == 0, r.output
        row = db.execute("SELECT date FROM calibration WHERE metric='vdot'").fetchone()
        assert row["date"] == date.today().isoformat()
        assert "recompute --force" not in r.output   # no back-date hint for today

    def test_invalid_date_rejected(self, db, config, monkeypatch):
        _patch_conn(monkeypatch, config)
        r = CliRunner().invoke(main, ["calibrate", "vdot", "38", "--date", "nonsense"])
        assert "Invalid --date" in r.output
        assert db.execute("SELECT COUNT(*) FROM calibration WHERE metric='vdot'").fetchone()[0] == 0
