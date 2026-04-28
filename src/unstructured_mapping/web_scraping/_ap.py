"""AP News RSS scraper with optional full-text extraction.

Full-text extraction requires the ``scraping`` extra::

    pip install unstructured-mapping[scraping]
"""

import logging

from unstructured_mapping.web_scraping._gnews import (
    _extract_text,
    _has_scraping_deps,
    _resolve_gnews_url,
)
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

    default_feed_urls = _DEFAULT_FEED_URL
    default_fetch_full_text = True
    source = "ap"

    def __init__(
        self,
        feed_urls: str | list[str] | None = None,
        fetch_full_text: bool | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        requested_full_text = (
            fetch_full_text
            if fetch_full_text is not None
            else self.default_fetch_full_text
        )
        has_deps = _has_scraping_deps()
        super().__init__(
            feed_urls=feed_urls,
            timeout=timeout,
            fetch_full_text=(requested_full_text and has_deps),
            max_workers=max_workers,
        )
        if requested_full_text and not has_deps:
            logger.warning(
                "scraping extra not installed; falling back to RSS summaries"
            )

    def _extract_body(self, gnews_url: str) -> ExtractionResult:
        """Decode a Google News URL and extract text.

        :param gnews_url: Google News redirect URL.
        :return: Extraction result with text and real URL.
        """
        real_url = _resolve_gnews_url(gnews_url)
        if not real_url:
            return ExtractionResult()
        text = _extract_text(real_url)
        return ExtractionResult(body=text, url=real_url)
