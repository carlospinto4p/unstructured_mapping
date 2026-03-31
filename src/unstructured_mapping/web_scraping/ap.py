"""AP News RSS scraper."""

import feedparser

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    DEFAULT_TIMEOUT,
)
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.parsing import (
    parse_feed_date,
)

_DEFAULT_FEED_URL = (
    "https://news.google.com/rss/search"
    "?q=when:24h+allinurl:apnews.com"
    "&ceid=US:en&hl=en-US&gl=US"
)


class APScraper(Scraper):
    """Scraper that fetches AP News headlines via RSS.

    Uses a Google News RSS feed filtered to AP News
    articles. Only titles and summaries are available
    (AP blocks direct article scraping).

    :param feed_urls: RSS feed URLs. Pass a single string
        or a list. Defaults to Google News filtered to
        AP News.
    :param timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        feed_urls: str | list[str] = _DEFAULT_FEED_URL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(
            feed_urls=feed_urls, timeout=timeout
        )

    @property
    def source(self) -> str:
        """Return ``"ap"``."""
        return "ap"

    def _parse_feed(self, xml: str) -> list[Article]:
        """Parse RSS XML into articles.

        :param xml: Raw RSS XML string.
        :return: Parsed articles.
        """
        feed = feedparser.parse(xml)
        articles: list[Article] = []
        for entry in feed.entries:
            articles.append(
                Article(
                    title=entry.get("title", ""),
                    body=entry.get("summary", ""),
                    url=entry.get("link", ""),
                    source=self.source,
                    published=parse_feed_date(entry),
                )
            )
        return articles
