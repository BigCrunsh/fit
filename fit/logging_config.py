"""Logging configuration for the fit platform."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(verbose: bool = False) -> None:
    """Configure logging with rotating file handlers and console output.

    Log files are written to ~/.fit/logs/ with 7-day rotation.
    Console output uses the root logger at INFO level (DEBUG if verbose).
    """
    log_dir = Path.home() / ".fit" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger("fit")
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        "%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Rotating file handler — sync.log covers all operations
    file_handler = RotatingFileHandler(
        log_dir / "sync.log",
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=7,
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Console handler — INFO by default, DEBUG if verbose
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
