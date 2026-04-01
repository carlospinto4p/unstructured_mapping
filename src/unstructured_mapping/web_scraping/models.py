"""Data models for web scraping."""

from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple


class ExtractionResult(NamedTuple):
    """Result of full-text extraction.

    :param body: Extracted article text (empty on failure).
    :param url: Resolved URL (empty to keep original).
    """

    body: str = ""
    url: str = ""


@dataclass(frozen=True, slots=True)
class Article:
    """A scraped news article.

    :param title: Headline of the article.
    :param body: Full text content.
    :param url: Canonical URL of the article.
    :param source: Name of the news source (e.g. ``"reuters"``).
    :param published: Publication timestamp, if available.
    """

    title: str
    body: str
    url: str
    source: str
    published: datetime | None = None
