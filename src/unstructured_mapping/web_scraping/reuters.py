"""Reuters RSS scraper."""

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    DEFAULT_TIMEOUT,
)

_DEFAULT_FEED_URL = (
    "https://news.google.com/rss/search"
    "?q=when:24h+allinurl:reuters.com"
    "&ceid=US:en&hl=en-US&gl=US"
)


class ReutersScraper(Scraper):
    """Scraper that fetches Reuters headlines via RSS.

    Uses a Google News RSS feed filtered to Reuters
    articles. Only titles and summaries are available
    (Reuters blocks direct article scraping).

    :param feed_urls: RSS feed URLs. Pass a single string
        or a list. Defaults to Google News filtered to
        Reuters.
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
        """Return ``"reuters"``."""
        return "reuters"
