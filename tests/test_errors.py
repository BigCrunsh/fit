"""Tests for fit/errors.py — the actionable-error carrier.

An "actionable" error is one we anticipated and can explain in a sentence
(expired login, missing file, bad config). The CLI prints those as a clean
message plus a next step, and keeps the traceback in the log file.
"""

import pytest

from fit.errors import ConfigError, FitError, GarminAuthError


class TestFitError:
    def test_is_a_runtime_error(self):
        # Callers (and existing tests) catch RuntimeError from fit.garmin;
        # subclassing keeps every one of them working.
        assert issubclass(FitError, RuntimeError)

    def test_hint_defaults_to_none(self):
        err = FitError("something broke")
        assert err.hint is None
        assert str(err) == "something broke"

    def test_hint_is_not_folded_into_the_message(self):
        # The whole point: the message stays a sentence, the next step stays
        # separate, so the CLI can render them on their own lines.
        err = FitError("Garmin rejected the saved login.", hint="Run `fit auth login`.")
        assert str(err) == "Garmin rejected the saved login."
        assert err.hint == "Run `fit auth login`."

    def test_garmin_auth_error_is_a_fit_error(self):
        assert issubclass(GarminAuthError, FitError)
        with pytest.raises(FitError):
            raise GarminAuthError("expired", hint="log in")


class TestConfigError:
    def test_is_both_a_fit_error_and_a_value_error(self):
        # Config resolution has raised ValueError since it was written, and
        # callers catch it that way. Being a FitError too is what earns it the
        # clean CLI rendering, without breaking any of them.
        assert issubclass(ConfigError, FitError)
        assert issubclass(ConfigError, ValueError)

    def test_caught_by_either_clause(self):
        for clause in (ValueError, FitError, RuntimeError):
            with pytest.raises(clause):
                raise ConfigError("missing FIT_LAT", hint="set it")

    def test_carries_a_hint_like_any_fit_error(self):
        err = ConfigError("missing FIT_LAT", hint="Set FIT_LAT in config.local.yaml.")
        assert err.hint == "Set FIT_LAT in config.local.yaml."
