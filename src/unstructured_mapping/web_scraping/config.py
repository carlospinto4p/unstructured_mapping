"""Shared configuration for web scraping."""

DEFAULT_TIMEOUT: float = 30.0

DEFAULT_MAX_WORKERS: int = 8

USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def google_news_rss(domain: str) -> str:
    """Build a Google News RSS URL filtered by domain.

    :param domain: Site domain (e.g. ``"apnews.com"``).
    :return: Google News RSS feed URL.
    """
    return (
        "https://news.google.com/rss/search"
        f"?q=when:24h+allinurl:{domain}"
        "&ceid=US:en&hl=en-US&gl=US"
    )
