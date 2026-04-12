"""Reuters RSS scraper."""

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    google_news_rss,
)

_DEFAULT_FEED_URL = google_news_rss("reuters.com")


class ReutersScraper(Scraper):
    """Scraper that fetches Reuters headlines via RSS.

    Uses a Google News RSS feed filtered to Reuters
    articles. Only titles and summaries are available
    (Reuters blocks direct article scraping), so the
    base-class default ``fetch_full_text=False`` is
    retained.

    Constructor parameters are inherited from
    :class:`~.base.Scraper`; this class only overrides
    the default feed URL.
    """

    default_feed_urls = _DEFAULT_FEED_URL
    source = "reuters"
