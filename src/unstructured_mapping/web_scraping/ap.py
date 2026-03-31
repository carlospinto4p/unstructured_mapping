"""AP News RSS scraper with optional full-text extraction.

Full-text extraction requires the ``scraping`` extra::

    pip install unstructured-mapping[scraping]
"""

import logging
from dataclasses import replace

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_TIMEOUT,
)
from unstructured_mapping.web_scraping.models import Article

logger = logging.getLogger(__name__)

_DEFAULT_FEED_URL = (
    "https://news.google.com/rss/search"
    "?q=when:24h+allinurl:apnews.com"
    "&ceid=US:en&hl=en-US&gl=US"
)


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
        max_workers: int = DEFAULT_MAX_WORKERS,
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

    def _enrich(
        self, articles: list[Article]
    ) -> list[Article]:
        """Decode Google News URLs and extract full text.

        Falls back to RSS summary when extraction fails.

        :param articles: Articles from RSS parsing.
        :return: Articles with resolved URLs and full text.
        """
        if not self._fetch_full_text:
            return articles
        results = self._parallel_map(
            self._extract_body,
            [a.url for a in articles],
            self._max_workers,
        )
        return [
            replace(
                a,
                body=(results.get(a.url, ("", ""))[0]
                      or a.body),
                url=(results.get(a.url, ("", ""))[1]
                     or a.url),
            )
            for a in articles
        ]

    def _extract_body(
        self, gnews_url: str
    ) -> tuple[str, str]:
        """Decode a Google News URL and extract text.

        :param gnews_url: Google News redirect URL.
        :return: Tuple of (extracted text, real URL).
            Text is empty on failure.
        """
        real_url = self._decode_url(gnews_url)
        if not real_url:
            return "", ""
        text = self._fetch_text(real_url)
        return text, real_url

    @staticmethod
    def _decode_url(gnews_url: str) -> str:
        """Resolve a Google News redirect to a real URL.

        :param gnews_url: Google News redirect URL.
        :return: Resolved URL, or empty string on failure.
        """
        from googlenewsdecoder import new_decoderv1

        try:
            result = new_decoderv1(gnews_url)
        except (ValueError, KeyError, OSError):
            logger.warning(
                "Failed to decode %s",
                gnews_url,
                exc_info=True,
            )
            return ""

        if not result.get("status"):
            logger.warning(
                "Decoder failed for %s", gnews_url
            )
            return ""
        return result["decoded_url"]

    @staticmethod
    def _fetch_text(url: str) -> str:
        """Fetch and extract article text with trafilatura.

        :param url: Direct article URL.
        :return: Extracted text, or empty string on failure.
        """
        import trafilatura

        try:
            html = trafilatura.fetch_url(url)
            text = (
                trafilatura.extract(html) if html else ""
            )
        except (OSError, ValueError):
            logger.warning(
                "Failed to extract %s",
                url,
                exc_info=True,
            )
            return ""
        return text or ""
