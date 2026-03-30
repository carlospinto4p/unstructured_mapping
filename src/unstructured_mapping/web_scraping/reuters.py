"""Reuters RSS scraper."""

from datetime import datetime, timezone

import feedparser
import httpx

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.models import Article

_DEFAULT_FEED_URL = (
    "https://news.google.com/rss/search"
    "?q=when:24h+allinurl:reuters.com"
    "&ceid=US:en&hl=en-US&gl=US"
)


class ReutersScraper(Scraper):
    """Scraper that fetches articles from a Reuters RSS feed.

    :param feed_url: RSS feed URL. Defaults to the Reuters
        agency feed.
    :param timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        feed_url: str = _DEFAULT_FEED_URL,
        timeout: float = 30.0,
    ) -> None:
        self._feed_url = feed_url
        self._timeout = timeout

    @property
    def source(self) -> str:
        """Return ``"reuters"``."""
        return "reuters"

    def fetch(self) -> list[Article]:
        """Fetch articles from the Reuters RSS feed.

        :return: List of articles parsed from the feed.
        :raises httpx.HTTPStatusError: If the feed request
            fails.
        """
        response = httpx.get(
            self._feed_url,
            timeout=self._timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        return self._parse_feed(response.text)

    def _parse_feed(self, xml: str) -> list[Article]:
        """Parse RSS XML into articles.

        :param xml: Raw RSS XML string.
        :return: Parsed articles.
        """
        feed = feedparser.parse(xml)
        articles: list[Article] = []
        for entry in feed.entries:
            published = self._parse_date(entry)
            articles.append(
                Article(
                    title=entry.get("title", ""),
                    body=entry.get("summary", ""),
                    url=entry.get("link", ""),
                    source=self.source,
                    published=published,
                )
            )
        return articles

    @staticmethod
    def _parse_date(
        entry: feedparser.FeedParserDict,
    ) -> datetime | None:
        """Extract publication date from a feed entry.

        :param entry: A single RSS feed entry.
        :return: Parsed datetime or ``None``.
        """
        parsed = entry.get("published_parsed")
        if parsed is None:
            return None
        from time import mktime

        return datetime.fromtimestamp(
            mktime(parsed), tz=timezone.utc
        )
