"""AP News RSS scraper with optional full-text extraction.

Full-text extraction requires the ``scraping`` extra::

    pip install unstructured-mapping[scraping]
"""

import logging

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_TIMEOUT,
    google_news_rss,
)
from unstructured_mapping.web_scraping.models import (
    ExtractionResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_FEED_URL = google_news_rss("apnews.com")


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
        has_deps = _has_scraping_deps()
        super().__init__(
            feed_urls=feed_urls,
            timeout=timeout,
            fetch_full_text=fetch_full_text and has_deps,
            max_workers=max_workers,
        )
        if fetch_full_text and not has_deps:
            logger.warning(
                "scraping extra not installed; "
                "falling back to RSS summaries"
            )

    source = "ap"

    def _extract_body(
        self, gnews_url: str
    ) -> ExtractionResult:
        """Decode a Google News URL and extract text.

        :param gnews_url: Google News redirect URL.
        :return: Extraction result with text and real URL.
        """
        real_url = self._resolve_url(gnews_url)
        if not real_url:
            return ExtractionResult()
        text = self._fetch_page(real_url)
        return ExtractionResult(body=text, url=real_url)

    @staticmethod
    def _resolve_url(gnews_url: str) -> str:
        """Resolve a Google News redirect URL.

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
    def _fetch_page(url: str) -> str:
        """Fetch article page and extract text.

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
