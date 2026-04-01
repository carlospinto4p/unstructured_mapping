"""Shared logging configuration for CLI tools."""

import logging

_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    level: int = logging.INFO,
) -> None:
    """Configure root logger for CLI output.

    :param level: Logging level (default ``INFO``).
    """
    logging.basicConfig(
        level=level,
        format=_FORMAT,
        datefmt=_DATEFMT,
    )
