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


class TestSyncSurfacesCalibrationSuggestions:
    """`fit sync` must SHOW a pending anchor suggestion, not just log it.

    The governance model is "anchors never change silently — the human accepts or
    rejects". `run_sync` did detect the suggestion and wrote it to
    ~/.fit/logs/sync.log at INFO, and `counts["calibration_suggestions"]` was set
    — but the console summary printed health/activities/enriched/weather/weeks and
    dropped it. So a VDOT anchor of 38.9 sat 4.6 points below what the athlete's
    races implied, sync noticed every single day, and said nothing where anyone
    would look. `fit status` and the dashboard both showed it; the one command run
    daily did not.
    """

    BASE = {"health": 1, "activities": 1, "enriched": 1, "weather": 0, "weekly_agg": 1}

    def _run(self, monkeypatch, config, counts):
        import fit.sync as S
        import fit.config as C
        import fit.db as D
        monkeypatch.setattr(C, "get_config", lambda: config)
        monkeypatch.setattr(D, "get_db", lambda *a, **k: get_db(config, migrations_dir=cli.MIGRATIONS_DIR))
        monkeypatch.setattr(S, "run_sync", lambda *a, **k: counts)
        return CliRunner().invoke(main, ["sync"])

    def test_pending_suggestion_is_printed(self, db, config, monkeypatch):
        r = self._run(monkeypatch, config, {**self.BASE, "calibration_suggestions": [
            {"metric": "vdot", "value": 43.5, "active": 38.9,
             "reason": "max of 8 effort(s) in last 180d", "confidence": "low"}]})
        assert r.exit_code == 0, r.output
        out = " ".join(r.output.split())
        assert "vdot" in out and "43.5" in out and "38.9" in out
        assert "fit calibrate vdot" in out          # the exact next step, not a hint

    def test_several_pending_metrics_all_appear(self, db, config, monkeypatch):
        r = self._run(monkeypatch, config, {**self.BASE, "calibration_suggestions": [
            {"metric": "vdot", "value": 43.5, "active": 38.9, "reason": "", "confidence": "low"},
            {"metric": "max_hr", "value": 197, "active": 195, "reason": "", "confidence": "high"}]})
        out = " ".join(r.output.split())
        assert "vdot" in out and "max_hr" in out

    def test_nothing_printed_when_no_suggestion_pending(self, db, config, monkeypatch):
        r = self._run(monkeypatch, config, {**self.BASE, "calibration_suggestions": []})
        assert r.exit_code == 0, r.output
        assert "calibrate" not in r.output.lower()

    def test_missing_key_does_not_crash(self, db, config, monkeypatch):
        """Older count shapes (and any sync whose suggestion step was skipped) must
        still complete — the summary is not worth failing a sync over."""
        r = self._run(monkeypatch, config, dict(self.BASE))
        assert r.exit_code == 0, r.output
        assert "Synced" in r.output
