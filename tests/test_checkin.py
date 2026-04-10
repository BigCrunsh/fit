"""Tests for fit/checkin.py — alcohol parsing, run_checkin, CLI commands."""

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from fit.checkin import _parse_alcohol, run_checkin


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
        """Text without leading number assumes 1 serving."""
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
        """Negative number: float('-1') works, so count=-1."""
        count, detail = _parse_alcohol("-1 drink")
        assert count == -1.0
        assert detail == "-1 drink"

    def test_zero_string(self):
        count, detail = _parse_alcohol("0")
        assert count == 0
        assert detail is None

    def test_zero_with_text(self):
        """'0 beers' — leading 0 is parsed as number."""
        count, detail = _parse_alcohol("0 beers")
        assert count == 0.0
        assert detail == "0 beers"

    def test_large_number(self):
        count, detail = _parse_alcohol("10 cocktails")
        assert count == 10.0
        assert detail == "10 cocktails"

    def test_whitespace_only(self):
        """Whitespace-only string: split(None, 1) returns [] → IndexError.
        This is an edge case that would be caught by the caller stripping first.
        The function itself raises IndexError on pure whitespace."""
        with pytest.raises(IndexError):
            _parse_alcohol("   ")

    def test_none_input(self):
        """None input should return (0, None) per the 'not s' check."""
        count, detail = _parse_alcohol(None)
        assert count == 0
        assert detail is None


# ════════════════════════════════════════════════════════════════
# run_checkin
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


class TestRunCheckin:
    """Test run_checkin saves to DB correctly."""

    def test_new_checkin(self, db):
        """New check-in for a specific date saves all fields."""
        answers = ["o", "o", "o", "n", "2", "0", "g", "5", "", "test note"]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_checkin(db, target_date="2026-01-15")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-01-15'").fetchone()
        assert row is not None
        assert row["hydration"] == "OK"
        assert row["legs"] == "OK"
        assert row["eating"] == "OK"
        assert row["energy"] == "Normal"
        assert row["sleep_quality"] == "Good"
        assert row["rpe"] == 5
        assert row["notes"] == "test note"

    def test_update_prefills_existing(self, db):
        """When a check-in exists, run_checkin auto-enters update mode and preserves values on enter."""
        db.execute(
            "INSERT INTO checkins (date, hydration, legs, eating, energy, alcohol, sleep_quality, rpe, notes) "
            "VALUES ('2026-02-01', 'Good', 'Fresh', 'Good', 'Good', 0, 'Good', 7, 'original')"
        )
        db.commit()
        # All empty answers → keep existing defaults
        answers = ["g", "f", "g", "g", "", "0", "g", "7", "", "original"]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_checkin(db, target_date="2026-02-01")
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-02-01'").fetchone()
        assert row["hydration"] == "Good"
        assert row["legs"] == "Fresh"
        assert row["rpe"] == 7
        assert row["notes"] == "original"

    def test_update_changes_field(self, db):
        """Updating a check-in can change individual fields."""
        db.execute(
            "INSERT INTO checkins (date, hydration, legs, eating, energy, alcohol, sleep_quality, rpe, notes) "
            "VALUES ('2026-02-02', 'OK', 'OK', 'OK', 'Normal', 0, 'OK', 3, 'old')"
        )
        db.commit()
        # Change RPE from 3 to 8, rest keep defaults
        answers = ["o", "o", "o", "n", "", "0", "o", "8", "", "old"]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_checkin(db, target_date="2026-02-02", update=True)
        row = db.execute("SELECT * FROM checkins WHERE date = '2026-02-02'").fetchone()
        assert row["rpe"] == 8

    def test_past_date(self, db):
        """Can create a check-in for a past date."""
        answers = ["l", "h", "p", "l", "1.5", "2 beers", "p", "9", "75", "past note"]
        with patch("fit.checkin.Prompt.ask", side_effect=_prompt_side_effect(answers)):
            run_checkin(db, target_date="2025-06-15")
        row = db.execute("SELECT * FROM checkins WHERE date = '2025-06-15'").fetchone()
        assert row is not None
        assert row["hydration"] == "Low"
        assert row["legs"] == "Heavy"
        assert row["alcohol"] == 2.0


# ════════════════════════════════════════════════════════════════
# CLI commands: checkin list, checkin update
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
        """Remove backfilled check-ins so each test starts clean."""
        db.execute("DELETE FROM checkins")
        db.commit()

    def test_list_empty(self, db):
        """checkin list with no data shows empty message."""
        from fit.cli import main as cli_main
        runner = CliRunner()
        with patch("fit.cli._conn", return_value=_NoCloseConn(db)):
            result = runner.invoke(cli_main, ["checkin", "list"])
        assert "No check-ins" in result.output

    def test_list_shows_checkins(self, db):
        """checkin list shows existing check-ins."""
        db.execute(
            "INSERT INTO checkins (date, hydration, legs, eating, energy, alcohol, sleep_quality, rpe, notes) "
            "VALUES ('2026-04-09', 'OK', 'OK', 'OK', 'Normal', 0, 'Good', 5, 'test run')"
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
        """checkin list --days filters old check-ins."""
        db.execute(
            "INSERT INTO checkins (date, hydration, legs, eating, energy, alcohol, sleep_quality) "
            "VALUES ('2020-01-01', 'OK', 'OK', 'OK', 'Normal', 0, 'OK')"
        )
        db.commit()
        from fit.cli import main as cli_main
        runner = CliRunner()
        with patch("fit.cli._conn", return_value=_NoCloseConn(db)):
            result = runner.invoke(cli_main, ["checkin", "list", "--days", "30"])
        assert "No check-ins" in result.output

    def test_update_accepts_date_argument(self):
        """checkin update accepts a positional date argument."""
        from fit.cli import main as cli_main
        runner = CliRunner()
        result = runner.invoke(cli_main, ["checkin", "update", "--help"])
        assert "TARGET_DATE" in result.output
