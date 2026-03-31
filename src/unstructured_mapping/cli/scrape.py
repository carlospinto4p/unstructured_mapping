"""Scrape news articles and store them in SQLite.

Usage::

    uv run python -m unstructured_mapping.cli.scrape
    uv run python -m unstructured_mapping.cli.scrape --feeds all
    uv run python -m unstructured_mapping.cli.scrape --sources bbc reuters
    uv run python -m unstructured_mapping.cli.scrape --db data/articles.db
    uv run python -m unstructured_mapping.cli.scrape --no-full-text
    uv run python -m unstructured_mapping.cli.scrape --stats
"""

import argparse
import logging
from pathlib import Path

from unstructured_mapping.web_scraping import (
    APScraper,
    BBC_FEEDS,
    ArticleStore,
    BBCScraper,
    ReutersScraper,
    Scraper,
)
from unstructured_mapping.web_scraping.config import (
    DEFAULT_TIMEOUT,
)

logger = logging.getLogger(__name__)

_SOURCES = ["bbc", "reuters", "ap"]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Scrape news articles into SQLite.",
    )
    p.add_argument(
        "--sources",
        nargs="+",
        choices=_SOURCES,
        default=_SOURCES,
        help="News sources to scrape (default: all).",
    )
    p.add_argument(
        "--feeds",
        choices=["default", "all"],
        default="all",
        help=(
            "BBC feed selection: 'default' for top stories "
            "only, 'all' for every topic feed "
            "(default: all)."
        ),
    )
    p.add_argument(
        "--db",
        type=Path,
        default=Path("data/articles.db"),
        help="Path to SQLite database "
        "(default: data/articles.db).",
    )
    p.add_argument(
        "--no-full-text",
        action="store_true",
        help="Skip full-text extraction (RSS summaries "
        "only).",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Show database stats and exit.",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help="HTTP timeout in seconds "
        f"(default: {DEFAULT_TIMEOUT}).",
    )
    return p


def _show_stats(store: ArticleStore) -> None:
    total = store.count()
    for src in _SOURCES:
        count = store.count(source=src)
        logger.info("%8s %d", src.upper(), count)
    logger.info("%8s %d", "TOTAL", total)


def _build_scraper(
    name: str,
    feeds: str,
    fetch_full_text: bool,
    timeout: float,
) -> Scraper:
    """Create a scraper instance by source name.

    :param name: Source name (``bbc``, ``reuters``,
        ``ap``).
    :param feeds: BBC feed selection.
    :param fetch_full_text: Enable full-text extraction.
    :param timeout: HTTP timeout in seconds.
    :return: Configured scraper instance.
    """
    if name == "bbc":
        feed_urls = (
            list(BBC_FEEDS.values())
            if feeds == "all"
            else [BBC_FEEDS["top"]]
        )
        return BBCScraper(
            feed_urls=feed_urls,
            fetch_full_text=fetch_full_text,
            timeout=timeout,
        )
    if name == "reuters":
        return ReutersScraper(timeout=timeout)
    return APScraper(
        fetch_full_text=fetch_full_text,
        timeout=timeout,
    )


def main(argv: list[str] | None = None) -> None:
    """Entry point for the scrape CLI."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    args = _build_parser().parse_args(argv)
    store = ArticleStore(db_path=args.db)

    if args.stats:
        _show_stats(store)
        store.close()
        return

    fetch_full = not args.no_full_text
    total_new = 0

    for name in args.sources:
        scraper = _build_scraper(
            name, args.feeds, fetch_full, args.timeout
        )
        logger.info("Scraping %s...", name)
        articles = scraper.fetch()
        new = store.save(articles)
        total_new += new
        logger.info(
            "  Fetched %d, saved %d new articles",
            len(articles),
            new,
        )

    logger.info(
        "Done: %d new articles (%d total in DB)",
        total_new,
        store.count(),
    )
    store.close()


if __name__ == "__main__":
    main()
