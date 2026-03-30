"""BBC News RSS scraper with full-text extraction."""

import logging

import feedparser
import httpx
from bs4 import BeautifulSoup

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    DEFAULT_TIMEOUT,
    USER_AGENT,
)
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.parsing import (
    parse_feed_date,
)

logger = logging.getLogger(__name__)

_DEFAULT_FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"

BBC_FEEDS: dict[str, str] = {
    "top": "https://feeds.bbci.co.uk/news/rss.xml",
    "world": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "business": (
        "https://feeds.bbci.co.uk/news/business/rss.xml"
    ),
    "technology": (
        "https://feeds.bbci.co.uk/news/technology/rss.xml"
    ),
    "science": (
        "https://feeds.bbci.co.uk/news/science_and_environment"
        "/rss.xml"
    ),
    "politics": (
        "https://feeds.bbci.co.uk/news/politics/rss.xml"
    ),
    "health": (
        "https://feeds.bbci.co.uk/news/health/rss.xml"
    ),
    "education": (
        "https://feeds.bbci.co.uk/news/education/rss.xml"
    ),
    "entertainment": (
        "https://feeds.bbci.co.uk/news/entertainment_and_arts"
        "/rss.xml"
    ),
    "uk": "https://feeds.bbci.co.uk/news/uk/rss.xml",
    "asia": (
        "https://feeds.bbci.co.uk/news/world/asia/rss.xml"
    ),
    "europe": (
        "https://feeds.bbci.co.uk/news/world/europe/rss.xml"
    ),
    "africa": (
        "https://feeds.bbci.co.uk/news/world/africa/rss.xml"
    ),
    "latin_america": (
        "https://feeds.bbci.co.uk/news/world/latin_america"
        "/rss.xml"
    ),
    "middle_east": (
        "https://feeds.bbci.co.uk/news/world/middle_east"
        "/rss.xml"
    ),
    "us_canada": (
        "https://feeds.bbci.co.uk/news/world/us_and_canada"
        "/rss.xml"
    ),
}

class BBCScraper(Scraper):
    """Scraper that fetches articles from BBC News RSS.

    Parses one or more RSS feeds for article metadata, then
    optionally fetches each article page for the full text.

    :param feed_urls: RSS feed URLs. Pass a single string or
        a list. Defaults to BBC News top stories only. Use
        ``BBC_FEEDS.values()`` for all feeds.
    :param fetch_full_text: Whether to fetch and parse the
        full article HTML. When ``False``, only the RSS
        summary is used.
    :param timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        feed_urls: str | list[str] = _DEFAULT_FEED_URL,
        fetch_full_text: bool = True,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(
            feed_urls=feed_urls, timeout=timeout
        )
        self._fetch_full_text = fetch_full_text

    @property
    def source(self) -> str:
        """Return ``"bbc"``."""
        return "bbc"

    def _parse_feed(self, xml: str) -> list[Article]:
        """Parse RSS XML into articles.

        :param xml: Raw RSS XML string.
        :return: Parsed articles.
        """
        feed = feedparser.parse(xml)
        articles: list[Article] = []
        for entry in feed.entries:
            url = entry.get("link", "")
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            published = parse_feed_date(entry)

            if self._fetch_full_text and url:
                body = self._extract_body(url)
                if not body:
                    body = summary
            else:
                body = summary

            articles.append(
                Article(
                    title=title,
                    body=body,
                    url=url,
                    source=self.source,
                    published=published,
                )
            )
        return articles

    def _extract_body(self, url: str) -> str:
        """Fetch an article page and extract body text.

        :param url: Article URL.
        :return: Extracted text, or empty string on failure.
        """
        try:
            resp = httpx.get(
                url,
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": USER_AGENT},
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            logger.warning("Failed to fetch %s", url)
            return ""

        soup = BeautifulSoup(resp.text, "html.parser")
        article = soup.find("article")
        if article is None:
            return ""

        paragraphs = article.find_all("p")
        return "\n\n".join(
            p.get_text(strip=True)
            for p in paragraphs
            if p.get_text(strip=True)
        )
