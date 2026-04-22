"""Backfill historical articles via Google News date-ranged search.

Use when the live scrapers missed a range of days (e.g. because the
scheduled runner was down). Fetches one day per query to stay within
Google News' result cap and saves into the same articles DB that the
live scrapers use. Duplicate URLs are silently skipped by
:class:`ArticleStore`.

Usage::

    uv run python -m unstructured_mapping.cli.backfill \\
        --from 2026-04-17 --until 2026-04-20

    # Single source only
    uv run python -m unstructured_mapping.cli.backfill \\
        --from 2026-04-17 --until 2026-04-20 --source ap
"""

import argparse
import logging
from datetime import date

from unstructured_mapping.cli._argparse_helpers import (
    ARTICLES_DEFAULT_DB,
    add_db_argument,
)
from unstructured_mapping.web_scraping.backfill import (
    ARCHIVE_SOURCES,
    fetch_range,
)
from unstructured_mapping.web_scraping.storage import ArticleStore

logger = logging.getLogger(__name__)


def _parse_date(s: str) -> date:
    """Parse ``YYYY-MM-DD`` for argparse ``type=``."""
    try:
        return date.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"expected YYYY-MM-DD, got {s!r}"
        ) from exc


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Backfill historical articles missed by the live "
            "scrapers, using Google News date-ranged search."
        ),
    )
    p.add_argument(
        "--from",
        dest="from_date",
        type=_parse_date,
        required=True,
        help="First day to backfill (YYYY-MM-DD, inclusive).",
    )
    p.add_argument(
        "--until",
        dest="until_date",
        type=_parse_date,
        required=True,
        help="Last day to backfill (YYYY-MM-DD, inclusive).",
    )
    p.add_argument(
        "--source",
        choices=(*ARCHIVE_SOURCES.keys(), "all"),
        default="all",
        help=(
            "Source to backfill. Defaults to all three (ap, bbc, reuters)."
        ),
    )
    add_db_argument(
        p,
        default=ARTICLES_DEFAULT_DB,
        label="articles SQLite database",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Entry point for the backfill CLI."""
    args = _build_parser().parse_args(argv)
    if args.from_date > args.until_date:
        raise SystemExit("--from must be <= --until")

    sources = (
        list(ARCHIVE_SOURCES.keys())
        if args.source == "all"
        else [args.source]
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    store = ArticleStore(args.db)
    total_inserted = 0
    for source in sources:
        logger.info(
            "Backfilling %s from %s to %s",
            source,
            args.from_date,
            args.until_date,
        )
        articles = fetch_range(
            source=source,
            from_date=args.from_date,
            until_date=args.until_date,
        )
        inserted = store.save(articles)
        total_inserted += inserted
        logger.info(
            "%s: fetched %d, inserted %d new",
            source,
            len(articles),
            inserted,
        )
    logger.info("Total new articles inserted: %d", total_inserted)


if __name__ == "__main__":
    main()
