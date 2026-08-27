"""Tests for how `fit` reports failures to the person who ran it.

The contract: an anticipated failure (expired Garmin login, unreadable token
file) prints one sentence plus one next step -- no traceback, no stacked
"X failed: Y failed: Z failed" prefixes. An unanticipated one still prints
short, but points at the log file.
"""

import re
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from fit.cli import main
from fit.errors import ConfigError, FitError, GarminAuthError


_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _flat(text: str) -> str:
    """Strip rich's colour codes and line wrapping so assertions are stable."""
    return re.sub(r"\s+", " ", _ANSI.sub("", text))


@pytest.fixture
def sync_env(monkeypatch, tmp_path):
    """Run `fit sync` with the DB and the Garmin pull both stubbed out."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("fit.db.get_db", lambda *a, **k: MagicMock())

    def _run(outcome):
        kwargs = {"side_effect": outcome} if isinstance(outcome, Exception) else {"return_value": outcome}
        monkeypatch.setattr("fit.sync.run_sync", MagicMock(**kwargs))
        return CliRunner().invoke(main, ["sync"])

    return _run


COUNTS = {"health": 8, "activities": 4, "enriched": 4, "weather": 4, "weekly_agg": 2}


class TestActionableFailures:
    def test_expired_login_prints_message_and_next_step(self, sync_env):
        result = sync_env(GarminAuthError(
            "Garmin rejected the saved login.",
            hint="Run `fit auth login` to sign in again.",
        ))
        out = _flat(result.output)
        assert result.exit_code == 1
        assert "Garmin rejected the saved login." in out
        assert "fit auth login" in out

    def test_expired_login_prints_no_traceback(self, sync_env):
        result = sync_env(GarminAuthError("expired", hint="Run `fit auth login`."))
        assert "Traceback" not in result.output
        assert "garminconnect" not in result.output

    def test_message_is_not_stacked_behind_prefixes(self, sync_env):
        # The bug: "Sync failed: Garmin auth probe failed: Authentication
        # failed: API Error 401 - ." Three wrappers, and the only useful words
        # last. An actionable error speaks for itself.
        result = sync_env(GarminAuthError("Garmin rejected the saved login.", hint="Run `fit auth login`."))
        out = _flat(result.output)
        assert "Sync failed: Garmin rejected" not in out
        assert out.count("failed:") <= 1

    def test_the_failure_is_not_echoed_a_second_time_as_a_log_line(self, sync_env):
        # The command prints the message itself, then logs it with a traceback
        # for sync.log. Both used to reach the console, so the user read the
        # same failure twice -- once readable, once as
        # `2026-08-27 07:25:30 fit.cli ERROR Sync failed: ...`.
        result = sync_env(GarminAuthError("Garmin rejected the saved login.", hint="Run `fit auth login`."))
        out = _flat(result.output)
        assert "fit.cli ERROR" not in out
        assert out.count("Garmin rejected the saved login.") == 1

    def test_hint_is_optional(self, sync_env):
        result = sync_env(FitError("Weather provider is not configured."))
        assert result.exit_code == 1
        assert "Weather provider is not configured." in _flat(result.output)


class TestUnexpectedFailures:
    def test_still_exits_one_and_names_the_error(self, sync_env):
        result = sync_env(ZeroDivisionError("division by zero"))
        out = _flat(result.output)
        assert result.exit_code == 1
        assert "division by zero" in out

    def test_points_at_the_log_instead_of_dumping_a_traceback(self, sync_env):
        result = sync_env(ZeroDivisionError("division by zero"))
        out = _flat(result.output)
        assert "Traceback" not in result.output
        assert "sync.log" in out
        assert "-v" in out


class TestSuccessPathUnchanged:
    def test_reports_counts_and_exits_zero(self, sync_env):
        result = sync_env(COUNTS)
        assert result.exit_code == 0, result.output
        assert "8 health" in _flat(result.output)


class TestFailuresOutsideACommandsOwnHandler:
    """Not every failure happens inside a command's try/except.

    `fit sync` loads config and opens the DB before its own error handling
    starts. A missing config value used to escape uncaught and print a raw
    traceback -- the same experience, one layer up. The group catches
    FitError for every command so no path can leak one.
    """

    def test_config_error_before_the_handler_still_reads_cleanly(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(
            "fit.config.get_config",
            MagicMock(side_effect=ConfigError(
                "Config placeholder ${FIT_LAT} has no value",
                hint="Set FIT_LAT in config.local.yaml.",
            )),
        )
        result = CliRunner().invoke(main, ["sync"])
        out = _flat(result.output)
        assert result.exit_code == 1
        assert "Config placeholder" in out
        assert "Set FIT_LAT in config.local.yaml." in out
        assert "Traceback" not in result.output

    def test_a_non_fit_error_before_the_handler_is_not_swallowed(self, monkeypatch, tmp_path):
        # The group only claims FitError. A genuine bug must keep propagating
        # so it is visible rather than silently reported as a clean failure.
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr("fit.config.get_config", MagicMock(side_effect=TypeError("boom")))
        result = CliRunner().invoke(main, ["sync"])
        assert result.exit_code != 0
        assert isinstance(result.exception, TypeError)

    def test_help_still_works(self):
        result = CliRunner().invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Personal fitness data platform" in result.output
