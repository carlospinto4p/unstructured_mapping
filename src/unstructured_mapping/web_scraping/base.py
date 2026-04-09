"""Base scraper interface."""

from abc import ABC
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import TypeVar

import feedparser
import httpx

from unstructured_mapping.web_scraping.config import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_TIMEOUT,
    USER_AGENT,
)
from unstructured_mapping.web_scraping.models import (
    Article,
    ExtractionResult,
)
from unstructured_mapping.web_scraping.parsing import (
    parse_feed_date,
)

_T = TypeVar("_T")


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
    :param fetch_full_text: Enable full-text extraction
        via :meth:`_extract_body`. Defaults to ``False``.
    :param max_workers: Thread pool size for parallel
        full-text extraction.
    """

    def __init__(
        self,
        feed_urls: str | list[str],
        timeout: float = DEFAULT_TIMEOUT,
        fetch_full_text: bool = False,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        if isinstance(feed_urls, str):
            self._feed_urls = [feed_urls]
        else:
            self._feed_urls = list(feed_urls)
        self._timeout = timeout
        self._fetch_full_text = fetch_full_text
        self._max_workers = max_workers
        self._client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT},
        )

    source: str
    """Short identifier for this news source.

    Subclasses must set this as a class variable
    (e.g. ``source = "bbc"``).
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not getattr(cls, "source", None):
            raise TypeError(
                f"{cls.__name__} must define a "
                f"'source' class variable"
            )

    def _parse_feed(self, xml: str) -> list[Article]:
        """Parse raw RSS XML into articles.

        Extracts title, summary, URL, and publication date
        from each feed entry. Enrichment (full-text
        extraction) is applied once in :meth:`fetch` after
        cross-feed URL deduplication, so subclasses should
        override this method only for source-specific
        parsing or filtering -- not for enrichment.

        :param xml: Raw RSS XML string.
        :return: Parsed (unenriched) articles.
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

    def _enrich(
        self, articles: list[Article]
    ) -> list[Article]:
        """Enrich articles with full-text extraction.

        When ``fetch_full_text`` is enabled, runs
        :meth:`_extract_body` in parallel for each article
        URL and merges the results back. Subclasses only
        need to override :meth:`_extract_body`.

        :param articles: Articles from RSS parsing.
        :return: Enriched articles.
        """
        if not self._fetch_full_text:
            return articles
        _empty = ExtractionResult()
        results = self._parallel_map(
            self._extract_body,
            [a.url for a in articles],
            self._max_workers,
        )
        enriched: list[Article] = []
        for a in articles:
            ex = results.get(a.url, _empty)
            enriched.append(replace(
                a,
                body=ex.body or a.body,
                url=ex.url or a.url,
            ))
        return enriched

    def _extract_body(
        self, url: str
    ) -> ExtractionResult:
        """Extract full text from an article URL.

        Override in subclasses to provide source-specific
        extraction. The default returns an empty result.

        :param url: Article URL.
        :return: Extraction result with body and/or URL.
        """
        return ExtractionResult()

    def _fetch_feed(self, feed_url: str) -> str:
        """Fetch a single RSS feed.

        :param feed_url: RSS feed URL.
        :return: Raw XML string.
        :raises httpx.HTTPStatusError: On HTTP errors.
        """
        response = self._client.get(feed_url)
        response.raise_for_status()
        return response.text

    def fetch(self) -> list[Article]:
        """Fetch articles from all configured RSS feeds.

        Feeds are fetched in parallel when there are
        multiple URLs. Articles are deduplicated by URL
        across feeds *before* :meth:`_enrich` runs, so a
        URL appearing in multiple feeds triggers at most
        one full-text extraction.

        :return: List of scraped articles.
        :raises httpx.HTTPStatusError: If any feed request
            fails.
        """
        feeds = self._parallel_map(
            self._fetch_feed,
            self._feed_urls,
            self._max_workers,
        )
        seen_urls: set[str] = set()
        articles: list[Article] = []
        for feed_url in self._feed_urls:
            xml = feeds.get(feed_url, "")
            if not xml:
                continue
            for article in self._parse_feed(xml):
                if article.url not in seen_urls:
                    seen_urls.add(article.url)
                    articles.append(article)
        return self._enrich(articles)

    @staticmethod
    def _parallel_map(
        fn: Callable[[str], _T],
        keys: list[str],
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> dict[str, _T]:
        """Run `fn` on each key in parallel.

        :param fn: Callable taking a URL string.
        :param keys: URLs to process.
        :param max_workers: Thread pool size.
        :return: Mapping of key to result.
        """
        results: dict[str, _T] = {}
        to_fetch = [k for k in keys if k]
        with ThreadPoolExecutor(
            max_workers=max_workers
        ) as pool:
            futures = {
                pool.submit(fn, k): k
                for k in to_fetch
            }
            for future in futures:
                results[futures[future]] = (
                    future.result()
                )
        return results

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> "Scraper":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
