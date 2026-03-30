"""Tests for the web_scraping module."""

from datetime import timezone
from unittest.mock import patch

import pytest

from unstructured_mapping.web_scraping import (
    Article,
    ArticleStore,
    BBCScraper,
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


@patch("unstructured_mapping.web_scraping.base.httpx.get")
def test_reuters_fetch_parses_rss(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_RSS)
    scraper = ReutersScraper(
        feed_urls="https://fake.feed/rss"
    )
    articles = scraper.fetch()

    assert len(articles) == 2
    assert articles[0].title == "Test headline"
    assert articles[0].body == "Article body text."
    assert articles[0].url == "https://example.com/article"
    assert articles[0].source == "reuters"


@patch("unstructured_mapping.web_scraping.base.httpx.get")
def test_reuters_fetch_parses_date(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_RSS)
    scraper = ReutersScraper(
        feed_urls="https://fake.feed/rss"
    )
    articles = scraper.fetch()

    assert articles[0].published is not None
    assert articles[0].published.year == 2026
    assert articles[0].published.month == 3
    assert articles[0].published.tzinfo == timezone.utc


@patch("unstructured_mapping.web_scraping.base.httpx.get")
def test_reuters_fetch_missing_date(mock_get):
    mock_get.return_value = _mock_response(SAMPLE_RSS)
    scraper = ReutersScraper(
        feed_urls="https://fake.feed/rss"
    )
    articles = scraper.fetch()

    assert articles[1].published is None


# -- BBCScraper --


BBC_RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>BBC News</title>
    <item>
      <title>BBC headline</title>
      <link>https://www.bbc.com/news/test-article</link>
      <description>BBC summary.</description>
      <pubDate>Mon, 30 Mar 2026 10:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

BBC_HTML = """\
<html><body>
<article>
  <p>First paragraph of the article.</p>
  <p>Second paragraph with more details.</p>
  <p></p>
  <p>Third paragraph conclusion.</p>
</article>
</body></html>
"""


def test_bbc_source():
    scraper = BBCScraper()
    assert scraper.source == "bbc"


@patch("httpx.get")
def test_bbc_fetch_full_text(mock_get):
    def side_effect(url, **kwargs):
        if "fake.feed" in url:
            return _mock_response(BBC_RSS)
        return _mock_response(BBC_HTML)

    mock_get.side_effect = side_effect
    scraper = BBCScraper(
        feed_urls="https://fake.feed/rss"
    )
    articles = scraper.fetch()

    assert len(articles) == 1
    assert articles[0].title == "BBC headline"
    assert "First paragraph" in articles[0].body
    assert "Second paragraph" in articles[0].body
    assert "Third paragraph" in articles[0].body
    assert articles[0].source == "bbc"


@patch("httpx.get")
def test_bbc_fetch_summary_only(mock_get):
    mock_get.return_value = _mock_response(BBC_RSS)
    scraper = BBCScraper(
        feed_urls="https://fake.feed/rss",
        fetch_full_text=False,
    )
    articles = scraper.fetch()

    assert articles[0].body == "BBC summary."


@patch("httpx.get")
def test_bbc_fallback_on_extraction_failure(mock_get):
    def side_effect(url, **kwargs):
        if "fake.feed" in url:
            return _mock_response(BBC_RSS)
        return _mock_response(
            "<html><body>No article</body></html>"
        )

    mock_get.side_effect = side_effect
    scraper = BBCScraper(
        feed_urls="https://fake.feed/rss"
    )
    articles = scraper.fetch()

    assert articles[0].body == "BBC summary."


# -- ArticleStore --


def _make_article(url="https://example.com/1", title="T"):
    return Article(
        title=title,
        body="Body text",
        url=url,
        source="test",
    )


def test_store_save_and_load(tmp_path):
    db = tmp_path / "test.db"
    store = ArticleStore(db_path=db)
    articles = [_make_article()]
    inserted = store.save(articles)

    assert inserted == 1
    loaded = store.load()
    assert len(loaded) == 1
    assert loaded[0].title == "T"
    assert loaded[0].body == "Body text"
    store.close()


def test_store_deduplication(tmp_path):
    db = tmp_path / "test.db"
    store = ArticleStore(db_path=db)
    articles = [_make_article()]
    store.save(articles)
    inserted = store.save(articles)

    assert inserted == 0
    assert store.count() == 1
    store.close()


def test_store_filter_by_source(tmp_path):
    db = tmp_path / "test.db"
    store = ArticleStore(db_path=db)
    a1 = Article(
        title="A", body="B", url="u1", source="bbc"
    )
    a2 = Article(
        title="C", body="D", url="u2", source="reuters"
    )
    store.save([a1, a2])

    assert store.count(source="bbc") == 1
    assert store.count(source="reuters") == 1
    assert store.count() == 2
    bbc_articles = store.load(source="bbc")
    assert len(bbc_articles) == 1
    assert bbc_articles[0].title == "A"
    store.close()


def test_store_count_empty(tmp_path):
    db = tmp_path / "test.db"
    store = ArticleStore(db_path=db)

    assert store.count() == 0
    store.close()
