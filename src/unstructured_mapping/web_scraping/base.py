"""Base scraper interface."""

from abc import ABC, abstractmethod

import httpx

from unstructured_mapping.web_scraping.config import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
)
from unstructured_mapping.web_scraping.models import Article


class Scraper(ABC):
    """Abstract base class for news scrapers.

    Provides a template-method :meth:`fetch` that iterates
    over feed URLs, fetches each one, deduplicates by URL,
    and delegates parsing to :meth:`_parse_feed`.

    Uses a persistent ``httpx.Client`` for connection
    pooling. Call :meth:`close` when done, or use as a
    context manager.

    :param feed_urls: One or more RSS feed URLs.
    :param timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        feed_urls: str | list[str],
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if isinstance(feed_urls, str):
            self._feed_urls = [feed_urls]
        else:
            self._feed_urls = list(feed_urls)
        self._timeout = timeout
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    @property
    @abstractmethod
    def source(self) -> str:
        """Short identifier for this news source."""

    @abstractmethod
    def _parse_feed(self, xml: str) -> list[Article]:
        """Parse raw RSS XML into articles.

        :param xml: Raw RSS XML string.
        :return: Parsed articles.
        """

    def fetch(self) -> list[Article]:
        """Fetch articles from all configured RSS feeds.

        Deduplicates by URL across feeds.

        :return: List of scraped articles.
        :raises httpx.HTTPStatusError: If any feed request
            fails.
        """
        seen_urls: set[str] = set()
        articles: list[Article] = []
        for feed_url in self._feed_urls:
            response = self._client.get(feed_url)
            response.raise_for_status()
            for article in self._parse_feed(
                response.text
            ):
                if article.url not in seen_urls:
                    seen_urls.add(article.url)
                    articles.append(article)
        return articles

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "Scraper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
