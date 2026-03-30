"""BBC News RSS scraper with full-text extraction."""

import logging
from concurrent.futures import ThreadPoolExecutor

import feedparser
import httpx
from bs4 import BeautifulSoup

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    DEFAULT_TIMEOUT,
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

_MAX_WORKERS = 8


class BBCScraper(Scraper):
    """Scraper that fetches articles from BBC News RSS.

    Parses one or more RSS feeds for article metadata, then
    optionally fetches each article page for the full text
    using parallel requests.

    :param feed_urls: RSS feed URLs. Pass a single string or
        a list. Defaults to BBC News top stories only. Use
        ``BBC_FEEDS.values()`` for all feeds.
    :param fetch_full_text: Whether to fetch and parse the
        full article HTML. When ``False``, only the RSS
        summary is used.
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
        self._fetch_full_text = fetch_full_text
        self._max_workers = max_workers

    @property
    def source(self) -> str:
        """Return ``"bbc"``."""
        return "bbc"

    def _parse_feed(self, xml: str) -> list[Article]:
        """Parse RSS XML into articles.

        When full-text extraction is enabled, article bodies
        are fetched in parallel using a thread pool.

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
            urls = [url for url, _, _, _ in entries]
            bodies = self._extract_bodies(urls)
        else:
            bodies = {}

        articles: list[Article] = []
        for url, title, summary, published in entries:
            body = bodies.get(url) or summary
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

    def _extract_bodies(
        self, urls: list[str]
    ) -> dict[str, str]:
        """Fetch multiple article pages in parallel.

        :param urls: Article URLs to fetch.
        :return: Mapping of URL to extracted body text.
        """
        results: dict[str, str] = {}
        urls_to_fetch = [u for u in urls if u]
        with ThreadPoolExecutor(
            max_workers=self._max_workers
        ) as pool:
            futures = {
                pool.submit(self._extract_body, url): url
                for url in urls_to_fetch
            }
            for future in futures:
                url = futures[future]
                results[url] = future.result()
        return results

    def _extract_body(self, url: str) -> str:
        """Fetch an article page and extract body text.

        :param url: Article URL.
        :return: Extracted text, or empty string on failure.
        """
        try:
            resp = self._client.get(url)
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
