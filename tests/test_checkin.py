"""Tests for fit/checkin.py — alcohol parsing, morning/run/evening check-ins, CLI."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from fit.checkin import (
    _parse_alcohol,
    run_morning,
    run_post_run,
    run_evening,
    run_checkin,
)


# ════════════════════════════════════════════════════════════════
# Alcohol Parsing
# ════════════════════════════════════════════════════════════════


class TestParseAlcohol:
    # Happy
    def test_zero(self):
        count, detail = _parse_alcohol("0")
        assert count == 0
        assert detail is None

    def test_number_with_description(self):
        count, detail = _parse_alcohol("2 beers")
        assert count == 2.0
        assert detail == "2 beers"

    def test_number_only(self):
        count, detail = _parse_alcohol("3")
        assert count == 3.0
        assert detail == "3"

    def test_float_number(self):
        count, detail = _parse_alcohol("1.5 glasses")
        assert count == 1.5
        assert detail == "1.5 glasses"

    def test_one_beer(self):
        count, detail = _parse_alcohol("1 beer")
        assert count == 1.0
        assert detail == "1 beer"

    # Unhappy
    def test_empty_string(self):
        count, detail = _parse_alcohol("")
        assert count == 0
        assert detail is None

    def test_text_only_assumes_one(self):
        count, detail = _parse_alcohol("small glass wine")
        assert count == 1.0
        assert detail == "small glass wine"

    def test_abc_non_numeric(self):
        count, detail = _parse_alcohol("abc")
        assert count == 1.0
        assert detail == "abc"

    def test_just_text_word(self):
        count, detail = _parse_alcohol("beer")
        assert count == 1.0
        assert detail == "beer"

    def test_negative_number(self):
        count, detail = _parse_alcohol("-1 drink")
        assert count == -1.0
        assert detail == "-1 drink"

    def test_zero_string(self):
        count, detail = _parse_alcohol("0")
        assert count == 0
        assert detail is None

    def test_zero_with_text(self):
        count, detail = _parse_alcohol("0 beers")
        assert count == 0.0
        assert detail == "0 beers"

    def test_large_number(self):
        count, detail = _parse_alcohol("10 cocktails")
        assert count == 10.0
        assert detail == "10 cocktails"

    def test_whitespace_only(self):
        with pytest.raises(IndexError):
            _parse_alcohol("   ")

    def test_none_input(self):
        count, detail = _parse_alcohol(None)
        assert count == 0
        assert detail is None


# ════════════════════════════════════════════════════════════════
# Helper
# ════════════════════════════════════════════════════════════════


def _prompt_side_effect(values):
    """Return a mock Prompt.ask that yields values in order."""
    it = iter(values)

    def _ask(prompt, **kwargs):
        try:
            return next(it)
        except StopIteration:
            return kwargs.get("default", "")
    return _ask


# ════════════════════════════════════════════════════════════════
# Morning check-in
# ════════════════════════════════════════════════════════════════


class TestMorning:
    def test_new_morning(self, db):
        """Morning check-in saves sleep, legs, energy, notes."""
        # sleep=Good, legs=Fresh, energy=Good, notes="slept well"
        answers = ["g", "f", "g", "slept well"]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_morning(db, target_date="2026-01-15")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-01-15'").fetchone()
        assert row is not None
        assert row["sleep_quality"] == "Good"
        assert row["legs"] == "Fresh"
        assert row["energy"] == "Good"
        assert row["notes"] == "slept well"

    def test_morning_preserves_evening(self, db):
        """Morning check-in doesn't overwrite existing evening fields."""
        db.execute(
            "INSERT INTO checkins (date, hydration, eating, alcohol) "
            "VALUES ('2026-01-16', 'Good', 'Good', 2)"
        )
        db.commit()
        answers = ["p", "h", "l", ""]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_morning(db, target_date="2026-01-16")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-01-16'").fetchone()
        assert row["sleep_quality"] == "Poor"
        assert row["legs"] == "Heavy"
        # Evening fields preserved
        assert row["hydration"] == "Good"
        assert row["eating"] == "Good"
        assert row["alcohol"] == 2


# ════════════════════════════════════════════════════════════════
# Post-run check-in
# ════════════════════════════════════════════════════════════════


class TestPostRun:
    def test_post_run_saves_rpe(self, db):
        """Post-run saves RPE and session notes."""
        answers = ["7", "felt strong"]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_post_run(db, target_date="2026-01-15")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-01-15'").fetchone()
        assert row is not None
        assert row["rpe"] == 7
        assert row["notes"] == "felt strong"

    def test_post_run_preserves_morning(self, db):
        """Post-run doesn't overwrite morning fields."""
        db.execute(
            "INSERT INTO checkins (date, sleep_quality, legs, energy) "
            "VALUES ('2026-01-17', 'Good', 'Fresh', 'Good')"
        )
        db.commit()
        answers = ["8", "hard tempo"]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_post_run(db, target_date="2026-01-17")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-01-17'").fetchone()
        assert row["rpe"] == 8
        assert row["sleep_quality"] == "Good"
        assert row["legs"] == "Fresh"


# ════════════════════════════════════════════════════════════════
# Evening check-in
# ════════════════════════════════════════════════════════════════


class TestEvening:
    def test_evening_saves_recovery(self, db):
        """Evening saves hydration, eating, alcohol, water."""
        # hydration=Good, eating=Good, alcohol="2 beers", water="2.5", weight=""
        answers = ["g", "g", "2 beers", "2.5", ""]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_evening(db, target_date="2026-01-15")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-01-15'").fetchone()
        assert row is not None
        assert row["hydration"] == "Good"
        assert row["eating"] == "Good"
        assert row["alcohol"] == 2.0
        assert row["alcohol_detail"] == "2 beers"
        assert row["water_liters"] == 2.5

    def test_evening_with_weight(self, db):
        """Evening can record weight, cross-written to body_comp."""
        answers = ["o", "o", "0", "", "78.5"]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_evening(db, target_date="2026-01-18")
        bc = db.execute(
            "SELECT weight_kg FROM body_comp WHERE date = '2026-01-18'"
        ).fetchone()
        assert bc is not None
        assert bc["weight_kg"] == 78.5

    def test_evening_preserves_morning(self, db):
        """Evening doesn't overwrite morning fields."""
        db.execute(
            "INSERT INTO checkins (date, sleep_quality, legs, energy, rpe) "
            "VALUES ('2026-01-19', 'Good', 'Fresh', 'Good', 5)"
        )
        db.commit()
        answers = ["g", "g", "0", "2", ""]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_evening(db, target_date="2026-01-19")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-01-19'").fetchone()
        assert row["hydration"] == "Good"
        # Morning + run fields preserved
        assert row["sleep_quality"] == "Good"
        assert row["legs"] == "Fresh"
        assert row["rpe"] == 5


# ════════════════════════════════════════════════════════════════
# Smart default (run_checkin)
# ════════════════════════════════════════════════════════════════


class TestSmartDefault:
    def test_morning_before_noon(self, db):
        """Before noon with no check-in → morning."""
        answers = ["g", "f", "g", ""]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            with patch("fit.checkin.datetime") as mock_dt:
                mock_dt.now.return_value.hour = 8
                mock_dt.side_effect = lambda *a, **k: __import__("datetime").datetime(*a, **k)
                run_checkin(db, target_date="2026-03-01")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-03-01'").fetchone()
        assert row["sleep_quality"] == "Good"
        assert row["legs"] == "Fresh"

    def test_all_done_shows_message(self, db):
        """When all sections filled, shows 'all done' message."""
        db.execute(
            "INSERT INTO checkins (date, sleep_quality, legs, energy, "
            "hydration, eating, rpe, alcohol) "
            "VALUES ('2026-03-02', 'Good', 'Fresh', 'Good', "
            "'OK', 'OK', 5, 0)"
        )
        db.commit()
        with patch("fit.checkin.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 14
            mock_dt.side_effect = lambda *a, **k: __import__("datetime").datetime(*a, **k)
            run_checkin(db, target_date="2026-03-02")
        # Should not crash — just prints "all done"


# ════════════════════════════════════════════════════════════════
# CLI commands
# ════════════════════════════════════════════════════════════════


class _NoCloseConn:
    """Wrapper that prevents close() from closing the shared test DB."""
    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        if name == "close":
            return lambda: None
        return getattr(self._conn, name)


class TestCheckinCLI:
    """Test checkin CLI subcommands."""

    @pytest.fixture(autouse=True)
    def _clear_checkins(self, db):
        db.execute("DELETE FROM checkins")
        db.commit()

    def test_list_empty(self, db):
        from fit.cli import main as cli_main
        runner = CliRunner()
        with patch("fit.cli._conn", return_value=_NoCloseConn(db)):
            result = runner.invoke(cli_main, ["checkin", "list"])
        assert "No check-ins" in result.output

    def test_list_shows_checkins(self, db):
        db.execute(
            "INSERT INTO checkins (date, hydration, legs, eating, energy, "
            "alcohol, sleep_quality, rpe, notes) "
            "VALUES ('2026-04-09', 'OK', 'OK', 'OK', 'Normal', 0, "
            "'Good', 5, 'test run')"
        )
        db.commit()
        from fit.cli import main as cli_main
        runner = CliRunner()
        with patch("fit.cli._conn", return_value=_NoCloseConn(db)):
            result = runner.invoke(cli_main, ["checkin", "list", "--days", "365"])
        assert "2026-04-09" in result.output
        assert "test run" in result.output
        assert "1 check-in shown" in result.output

    def test_list_days_filter(self, db):
        db.execute(
            "INSERT INTO checkins (date, hydration, legs, eating, energy, "
            "alcohol, sleep_quality) "
            "VALUES ('2020-01-01', 'OK', 'OK', 'OK', 'Normal', 0, 'OK')"
        )
        db.commit()
        from fit.cli import main as cli_main
        runner = CliRunner()
        with patch("fit.cli._conn", return_value=_NoCloseConn(db)):
            result = runner.invoke(cli_main, ["checkin", "list", "--days", "30"])
        assert "No check-ins" in result.output

    def test_morning_subcommand_help(self):
        from fit.cli import main as cli_main
        runner = CliRunner()
        result = runner.invoke(cli_main, ["checkin", "morning", "--help"])
        assert "Pre-run readiness" in result.output

    def test_run_subcommand_help(self):
        from fit.cli import main as cli_main
        runner = CliRunner()
        result = runner.invoke(cli_main, ["checkin", "run", "--help"])
        assert "Post-run" in result.output

    def test_evening_subcommand_help(self):
        from fit.cli import main as cli_main
        runner = CliRunner()
        result = runner.invoke(cli_main, ["checkin", "evening", "--help"])
        assert "Recovery" in result.output
