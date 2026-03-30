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
from pathlib import Path

from unstructured_mapping.web_scraping import (
    BBC_FEEDS,
    ArticleStore,
    BBCScraper,
    ReutersScraper,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Scrape news articles into SQLite.",
    )
    p.add_argument(
        "--sources",
        nargs="+",
        choices=["bbc", "reuters"],
        default=["bbc", "reuters"],
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
        default=30.0,
        help="HTTP timeout in seconds (default: 30).",
    )
    return p


def _show_stats(store: ArticleStore) -> None:
    total = store.count()
    bbc = store.count(source="bbc")
    reuters = store.count(source="reuters")
    print(f"Total:   {total}")
    print(f"BBC:     {bbc}")
    print(f"Reuters: {reuters}")


def main(argv: list[str] | None = None) -> None:
    """Entry point for the scrape CLI."""
    args = _build_parser().parse_args(argv)
    store = ArticleStore(db_path=args.db)

    if args.stats:
        _show_stats(store)
        store.close()
        return

    fetch_full = not args.no_full_text
    total_new = 0

    if "bbc" in args.sources:
        if args.feeds == "all":
            feed_urls = list(BBC_FEEDS.values())
        else:
            feed_urls = [BBC_FEEDS["top"]]

        print(
            f"Scraping BBC ({len(feed_urls)} feeds, "
            f"full_text={fetch_full})..."
        )
        scraper = BBCScraper(
            feed_urls=feed_urls,
            fetch_full_text=fetch_full,
            timeout=args.timeout,
        )
        articles = scraper.fetch()
        new = store.save(articles)
        total_new += new
        print(
            f"  Fetched {len(articles)}, "
            f"saved {new} new articles"
        )

    if "reuters" in args.sources:
        print("Scraping Reuters (RSS headlines)...")
        scraper_r = ReutersScraper(
            timeout=args.timeout
        )
        articles_r = scraper_r.fetch()
        new_r = store.save(articles_r)
        total_new += new_r
        print(
            f"  Fetched {len(articles_r)}, "
            f"saved {new_r} new articles"
        )

    print(
        f"\nDone: {total_new} new articles "
        f"({store.count()} total in DB)"
    )
    store.close()


if __name__ == "__main__":
    main()
