"""Logging configuration for the fit platform."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_FILENAME = "sync.log"


def log_path() -> Path:
    """Where the full diagnostic log lives — quoted in error messages."""
    return Path.home() / ".fit" / "logs" / LOG_FILENAME


ALREADY_SHOWN = "already_shown"


class AlreadyShownFilter(logging.Filter):
    """Suppresses records the CLI has already rendered for the user.

    A failed command prints its own message through rich, then logs the same
    failure with a traceback so the file has it. Without this filter the
    console prints both — the readable version, immediately followed by
    `2026-08-27 07:25:30 fit.cli ERROR Sync failed: ...` saying it again in
    log format. Passing `extra={"already_shown": True}` keeps the record out
    of the console while it still reaches sync.log in full.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not getattr(record, ALREADY_SHOWN, False)


class ConsoleFormatter(logging.Formatter):
    """Formats the message only, never the traceback.

    The console and the log file want opposite things from the same record.
    On the console a traceback buries the CLI's own error message under stack
    frames from libraries the user did not call. In the file it is the whole
    point. This formatter drops the exception for its handler alone, leaving
    the record untouched so whichever handler runs next still gets it.
    """

    def format(self, record: logging.LogRecord) -> str:
        exc_info, exc_text, stack_info = record.exc_info, record.exc_text, record.stack_info
        record.exc_info = record.exc_text = record.stack_info = None
        try:
            return super().format(record)
        finally:
            record.exc_info, record.exc_text, record.stack_info = exc_info, exc_text, stack_info


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with rotating file handlers and console output.

    Log files are written to ~/.fit/logs/ with 7-day rotation. The file gets
    everything including tracebacks; the console gets warnings and errors as
    single lines, unless `verbose` asks for the full picture.
    """
    log_dir = log_path().parent
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("fit")
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Called once per CLI invocation, but a long-lived process (the MCP server,
    # the test suite) can reach it repeatedly. Without this reset each call
    # stacks another pair of handlers, duplicating every line and writing to
    # streams that closed with the previous invocation.
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
        handler.close()

    # Rotating file handler — sync.log covers all operations
    file_handler = RotatingFileHandler(
        log_dir / LOG_FILENAME,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=7,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console handler — warnings and errors only, DEBUG if verbose. `-v` means
    # "show me everything", so it opts back into tracebacks and into the
    # records the CLI already printed in friendlier form.
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    if verbose:
        console_handler.setFormatter(formatter)
    else:
        console_handler.setFormatter(ConsoleFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S",
        ))
        console_handler.addFilter(AlreadyShownFilter())
    root_logger.addHandler(console_handler)

    # garminconnect reports *why* a token refresh failed at DEBUG level and
    # then swallows the exception, retrying once and surfacing a bare 401 with
    # an empty body. Routing its logger to our file — and only to our file —
    # is the difference between "auth failed, reason unknown" and a recorded
    # cause we can act on.
    for name in ("garminconnect", "garth"):
        third_party = logging.getLogger(name)
        third_party.setLevel(logging.DEBUG)
        for handler in list(third_party.handlers):
            third_party.removeHandler(handler)
            handler.close()
        third_party.addHandler(file_handler)
        third_party.propagate = False
