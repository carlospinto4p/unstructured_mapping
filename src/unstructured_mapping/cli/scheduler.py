"""Periodic news scraper scheduler for Docker deployment.

Runs the scrape CLI on a configurable interval, logging
each cycle. Designed as the entrypoint for the Docker
container.

Environment variables:

    ``SCRAPE_INTERVAL_HOURS``
        Hours between scrape cycles (default: 4).
    ``SCRAPE_SOURCES``
        Space-separated sources (default: ``bbc reuters``).
    ``SCRAPE_FEEDS``
        Feed selection: ``default`` or ``all``
        (default: ``all``).
    ``SCRAPE_DB``
        Path to SQLite database
        (default: ``data/articles.db``).
    ``SCRAPE_FULL_TEXT``
        Set to ``0`` to disable full-text extraction
        (default: ``1``).
"""

import logging
import os
import time

from unstructured_mapping.cli.scrape import main as scrape

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def _build_argv() -> list[str]:
    """Build CLI arguments from environment variables."""
    argv: list[str] = []

    sources = os.environ.get("SCRAPE_SOURCES", "bbc reuters")
    argv.extend(["--sources", *sources.split()])

    feeds = os.environ.get("SCRAPE_FEEDS", "all")
    argv.extend(["--feeds", feeds])

    db = os.environ.get("SCRAPE_DB", "data/articles.db")
    argv.extend(["--db", db])

    if os.environ.get("SCRAPE_FULL_TEXT", "1") == "0":
        argv.append("--no-full-text")

    return argv


def run() -> None:
    """Run the scraper in a loop with a configurable
    interval."""
    interval_h = float(
        os.environ.get("SCRAPE_INTERVAL_HOURS", "4")
    )
    interval_s = interval_h * 3600
    argv = _build_argv()

    log.info(
        "Scheduler started: interval=%.1fh, argv=%s",
        interval_h,
        argv,
    )

    while True:
        log.info("Starting scrape cycle...")
        try:
            scrape(argv)
        except Exception:
            log.exception("Scrape cycle failed")
        log.info(
            "Cycle complete. Sleeping %.1f hours...",
            interval_h,
        )
        time.sleep(interval_s)


if __name__ == "__main__":
    run()
