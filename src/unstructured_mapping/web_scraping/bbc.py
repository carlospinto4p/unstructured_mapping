"""BBC News RSS scraper with full-text extraction."""

from datetime import datetime, timezone
from time import mktime

import feedparser
import httpx
from bs4 import BeautifulSoup

from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.models import Article

_DEFAULT_FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class BBCScraper(Scraper):
    """Scraper that fetches articles from BBC News RSS.

    Parses the RSS feed for article metadata, then fetches
    each article page to extract the full text.

    :param feed_url: RSS feed URL. Defaults to BBC News
        top stories.
    :param fetch_full_text: Whether to fetch and parse the
        full article HTML. When ``False``, only the RSS
        summary is used.
    :param timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        feed_url: str = _DEFAULT_FEED_URL,
        fetch_full_text: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self._feed_url = feed_url
        self._fetch_full_text = fetch_full_text
        self._timeout = timeout

    @property
    def source(self) -> str:
        """Return ``"bbc"``."""
        return "bbc"

    def fetch(self) -> list[Article]:
        """Fetch articles from the BBC News RSS feed.

        :return: List of articles with full text when
            `fetch_full_text` is enabled.
        :raises httpx.HTTPStatusError: If any HTTP request
            fails.
        """
        response = httpx.get(
            self._feed_url,
            timeout=self._timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        return self._parse_feed(response.text)

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
            published = self._parse_date(entry)

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
                headers={"User-Agent": _USER_AGENT},
            )
            resp.raise_for_status()
        except httpx.HTTPError:
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

    @staticmethod
    def _parse_date(
        entry: feedparser.FeedParserDict,
    ) -> datetime | None:
        """Extract publication date from a feed entry.

        :param entry: A single RSS feed entry.
        :return: Parsed datetime or ``None``.
        """
        parsed = entry.get("published_parsed")
        if parsed is None:
            return None
        return datetime.fromtimestamp(
            mktime(parsed), tz=timezone.utc
        )
