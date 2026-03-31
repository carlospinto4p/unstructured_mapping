"""Shared parsing utilities for RSS feed scrapers."""

from datetime import datetime, timezone

import feedparser


def parse_feed_date(
    entry: feedparser.FeedParserDict,
) -> datetime | None:
    """Extract publication date from an RSS feed entry.

    :param entry: A single RSS feed entry.
    :return: Parsed datetime in UTC, or ``None`` if the
        entry has no publication date.
    """
    parsed = entry.get("published_parsed")
    if parsed is None:
        return None
    return datetime(*parsed[:6], tzinfo=timezone.utc)
