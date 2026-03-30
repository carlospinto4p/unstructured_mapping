"""Data models for web scraping."""

from dataclasses import dataclass
from datetime import datetime


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
