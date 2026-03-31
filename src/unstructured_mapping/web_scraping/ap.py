"""AP News RSS scraper with optional full-text extraction.

Full-text extraction requires the ``scraping`` extra::

    pip install unstructured-mapping[scraping]
"""

import logging
from concurrent.futures import ThreadPoolExecutor

import feedparser

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    DEFAULT_TIMEOUT,
)
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.parsing import (
    parse_feed_date,
)

logger = logging.getLogger(__name__)

_DEFAULT_FEED_URL = (
    "https://news.google.com/rss/search"
    "?q=when:24h+allinurl:apnews.com"
    "&ceid=US:en&hl=en-US&gl=US"
)

_MAX_WORKERS = 8


def _has_scraping_deps() -> bool:
    """Check if optional scraping deps are installed."""
    try:
        import googlenewsdecoder  # noqa: F401
        import trafilatura  # noqa: F401
    except ImportError:
        return False
    return True


class APScraper(Scraper):
    """Scraper that fetches AP News articles via RSS.

    Uses a Google News RSS feed filtered to AP News.
    When ``fetch_full_text`` is enabled and the
    ``scraping`` extra is installed, decodes Google News
    URLs and extracts full article text with trafilatura.

    :param feed_urls: RSS feed URLs. Pass a single string
        or a list. Defaults to Google News filtered to
        AP News.
    :param fetch_full_text: Whether to fetch full article
        text. Requires ``scraping`` extra. Falls back to
        RSS summary if unavailable.
    :param timeout: HTTP request timeout in seconds.
    :param max_workers: Max parallel threads for full-text
        extraction.
    """

    def __init__(
        self,
        feed_urls: str | list[str] = _DEFAULT_FEED_URL,
        fetch_full_text: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
        max_workers: int = _MAX_WORKERS,
    ) -> None:
        super().__init__(
            feed_urls=feed_urls, timeout=timeout
        )
        self._fetch_full_text = (
            fetch_full_text and _has_scraping_deps()
        )
        self._max_workers = max_workers
        if fetch_full_text and not self._fetch_full_text:
            logger.warning(
                "scraping extra not installed; "
                "falling back to RSS summaries"
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

        entries = [
            (
                entry.get("link", ""),
                entry.get("title", ""),
                entry.get("summary", ""),
                parse_feed_date(entry),
            )
            for entry in feed.entries
        ]

        if self._fetch_full_text:
            gnews_urls = [url for url, _, _, _ in entries]
            bodies = self._extract_bodies(gnews_urls)
        else:
            bodies = {}

        articles: list[Article] = []
        for url, title, summary, published in entries:
            body = bodies.get(url) or summary
            real_url = (
                bodies.get(f"_resolved_{url}") or url
            )
            articles.append(
                Article(
                    title=title,
                    body=body,
                    url=real_url,
                    source=self.source,
                    published=published,
                )
            )
        return articles

    def _extract_bodies(
        self, gnews_urls: list[str]
    ) -> dict[str, str]:
        """Decode and fetch multiple articles in parallel.

        :param gnews_urls: Google News redirect URLs.
        :return: Mapping of original URL to body text,
            plus ``_resolved_<url>`` keys with real URLs.
        """
        results: dict[str, str] = {}
        urls_to_fetch = [u for u in gnews_urls if u]
        with ThreadPoolExecutor(
            max_workers=self._max_workers
        ) as pool:
            futures = {
                pool.submit(
                    self._extract_body, url
                ): url
                for url in urls_to_fetch
            }
            for future in futures:
                gnews_url = futures[future]
                body, real_url = future.result()
                results[gnews_url] = body
                if real_url:
                    results[
                        f"_resolved_{gnews_url}"
                    ] = real_url
        return results

    def _extract_body(
        self, gnews_url: str
    ) -> tuple[str, str]:
        """Decode a Google News URL and extract text.

        :param gnews_url: Google News redirect URL.
        :return: Tuple of (extracted text, real URL).
            Text is empty on failure.
        """
        from googlenewsdecoder import new_decoderv1

        try:
            result = new_decoderv1(gnews_url)
        except Exception:
            logger.warning(
                "Failed to decode %s", gnews_url
            )
            return "", ""

        if not result.get("status"):
            logger.warning(
                "Decoder failed for %s", gnews_url
            )
            return "", ""

        real_url = result["decoded_url"]

        import trafilatura

        try:
            html = trafilatura.fetch_url(real_url)
            text = (
                trafilatura.extract(html) if html else ""
            )
        except Exception:
            logger.warning(
                "Failed to extract %s", real_url
            )
            return "", real_url

        return text or "", real_url
