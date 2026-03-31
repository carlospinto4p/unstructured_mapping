"""Base scraper interface."""

from abc import ABC, abstractmethod

import feedparser
import httpx

from unstructured_mapping.web_scraping.config import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
)
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.parsing import (
    parse_feed_date,
)


class Scraper(ABC):
    """Abstract base class for news scrapers.

    Provides a template-method :meth:`fetch` that iterates
    over feed URLs, fetches each one, deduplicates by URL,
    and delegates parsing to :meth:`_parse_feed`.

    Subclasses that only need basic RSS parsing can rely on
    the default :meth:`_parse_feed`, which builds articles
    from feed entry fields. Subclasses needing enrichment
    (e.g. full-text extraction) should override
    :meth:`_enrich` to transform the article list.

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

    def _parse_feed(self, xml: str) -> list[Article]:
        """Parse raw RSS XML into articles.

        Extracts title, summary, URL, and publication date
        from each feed entry, then passes the list through
        :meth:`_enrich` for optional enrichment.

        :param xml: Raw RSS XML string.
        :return: Parsed (and possibly enriched) articles.
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
        return self._enrich(articles)

    def _enrich(
        self, articles: list[Article]
    ) -> list[Article]:
        """Enrich articles after initial RSS parsing.

        The default implementation returns articles
        unchanged. Subclasses can override this to add
        full-text extraction or URL resolution.

        :param articles: Articles from RSS parsing.
        :return: Enriched articles.
        """
        return articles

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
