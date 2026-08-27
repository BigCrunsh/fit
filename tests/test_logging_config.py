"""Tests for fit/logging_config.py — console stays readable, file stays complete.

The console handler is what the user reads after a failed command; the file
handler is what we read when diagnosing one. They have opposite needs, so the
traceback belongs only in the file unless `-v` is passed.
"""

import logging

from fit.logging_config import ConsoleFormatter, setup_logging


def _record_with_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys
        exc_info = sys.exc_info()
    return logging.LogRecord(
        name="fit.cli", level=logging.ERROR, pathname=__file__, lineno=1,
        msg="Sync failed", args=(), exc_info=exc_info,
    )


class TestConsoleFormatter:
    def test_drops_the_traceback(self):
        out = ConsoleFormatter("%(message)s").format(_record_with_traceback())
        assert out == "Sync failed"
        assert "Traceback" not in out
        assert "ValueError" not in out

    def test_leaves_the_record_reusable_by_the_file_handler(self):
        # Handlers share one record. If the console formatter consumed or
        # cached the exception text, the file handler would silently lose the
        # traceback -- the one place we actually want it.
        record = _record_with_traceback()
        ConsoleFormatter("%(message)s").format(record)
        file_out = logging.Formatter("%(message)s").format(record)
        assert "Traceback" in file_out
        assert "ValueError: boom" in file_out

    def test_order_does_not_matter(self):
        # Same as above but with the file handler formatting first, which
        # populates record.exc_text -- the console must not print that cache.
        record = _record_with_traceback()
        logging.Formatter("%(message)s").format(record)
        console_out = ConsoleFormatter("%(message)s").format(record)
        assert "Traceback" not in console_out

    def test_records_without_exceptions_are_untouched(self):
        record = logging.LogRecord(
            name="fit.sync", level=logging.WARNING, pathname=__file__, lineno=1,
            msg="Body comp is %d days old", args=(48,), exc_info=None,
        )
        assert ConsoleFormatter("%(message)s").format(record) == "Body comp is 48 days old"


class TestSetupLogging:
    def test_console_hides_tracebacks_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        setup_logging(verbose=False)
        console = _console_handler()
        assert isinstance(console.formatter, ConsoleFormatter)

    def test_verbose_shows_tracebacks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        setup_logging(verbose=True)
        console = _console_handler()
        assert not isinstance(console.formatter, ConsoleFormatter)
        assert console.level == logging.DEBUG

    def test_is_idempotent(self, tmp_path, monkeypatch):
        # Called once per CLI invocation. Without a reset, a long-lived process
        # (and every test that invokes the CLI twice) accumulates handlers and
        # prints each line N times, some to already-closed streams.
        monkeypatch.setenv("HOME", str(tmp_path))
        setup_logging()
        first = len(logging.getLogger("fit").handlers)
        setup_logging()
        setup_logging()
        assert len(logging.getLogger("fit").handlers) == first

    def test_third_party_garmin_logs_reach_the_file(self, tmp_path, monkeypatch):
        # garminconnect logs *why* a token refresh failed at DEBUG and then
        # swallows it. Without this wiring, a 401 arrives at the user with an
        # empty reason and nothing recorded anywhere.
        monkeypatch.setenv("HOME", str(tmp_path))
        setup_logging()
        garmin_logger = logging.getLogger("garminconnect")
        assert garmin_logger.handlers, "garminconnect logs are not captured"
        assert garmin_logger.level == logging.DEBUG


def _console_handler():
    handlers = logging.getLogger("fit").handlers
    return next(h for h in handlers if not hasattr(h, "baseFilename"))
