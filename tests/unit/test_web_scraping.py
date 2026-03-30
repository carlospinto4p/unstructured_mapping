"""Tests for the web_scraping module."""

from datetime import timezone
from unittest.mock import patch

import pytest

from unstructured_mapping.web_scraping import (
    Article,
    ReutersScraper,
    Scraper,
)

SAMPLE_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Reuters News</title>
    <item>
      <title>Test headline</title>
      <link>https://example.com/article</link>
      <description>Article body text.</description>
      <pubDate>Mon, 30 Mar 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second headline</title>
      <link>https://example.com/article2</link>
      <description>Second body.</description>
    </item>
  </channel>
</rss>
"""


# -- Article model --


def test_article_fields():
    article = Article(
        title="T",
        body="B",
        url="https://x.com",
        source="test",
    )
    assert article.title == "T"
    assert article.body == "B"
    assert article.source == "test"
    assert article.published is None


def test_article_is_frozen():
    article = Article(
        title="T", body="B", url="u", source="s"
    )
    with pytest.raises(AttributeError):
        article.title = "new"  # type: ignore[misc]


# -- Scraper ABC --


def test_scraper_cannot_be_instantiated():
    with pytest.raises(TypeError):
        Scraper()  # type: ignore[abstract]


# -- ReutersScraper --


def _mock_response(text: str):
    """Create a mock httpx response."""

    class _Resp:
        def __init__(self):
            self.text = text
            self.status_code = 200

        def raise_for_status(self):
            pass

    return _Resp()


def test_reuters_source():
    scraper = ReutersScraper()
    assert scraper.source == "reuters"


@patch("unstructured_mapping.web_scraping.reuters.httpx.get")
def test_reuters_fetch_parses_rss(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_RSS)
    scraper = ReutersScraper(
        feed_url="https://fake.feed/rss"
    )
    articles = scraper.fetch()

    assert len(articles) == 2
    assert articles[0].title == "Test headline"
    assert articles[0].body == "Article body text."
    assert articles[0].url == "https://example.com/article"
    assert articles[0].source == "reuters"


@patch("unstructured_mapping.web_scraping.reuters.httpx.get")
def test_reuters_fetch_parses_date(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_RSS)
    scraper = ReutersScraper(
        feed_url="https://fake.feed/rss"
    )
    articles = scraper.fetch()

    assert articles[0].published is not None
    assert articles[0].published.year == 2026
    assert articles[0].published.month == 3
    assert articles[0].published.tzinfo == timezone.utc


@patch("unstructured_mapping.web_scraping.reuters.httpx.get")
def test_reuters_fetch_missing_date(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_RSS)
    scraper = ReutersScraper(
        feed_url="https://fake.feed/rss"
    )
    articles = scraper.fetch()

    assert articles[1].published is None
