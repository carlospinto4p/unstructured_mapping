"""Tests for the historical backfill module."""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest

from unstructured_mapping.web_scraping.backfill import (
    ARCHIVE_SOURCES,
    ArchiveScraper,
    build_archive_query_url,
    fetch_range,
)
from unstructured_mapping.web_scraping.models import Article


def test_build_archive_query_url_uses_one_day_window():
    """One-day window keeps each query under the ~100-result cap."""
    url = build_archive_query_url("apnews.com", date(2026, 4, 17))
    assert "site:apnews.com" in url
    assert "after:2026-04-17" in url
    assert "before:2026-04-18" in url


def test_build_archive_query_url_escapes_domain_literally():
    """Domain is inserted as-is — callers supply the exact string."""
    url = build_archive_query_url("bbc.com", date(2026, 4, 18))
    assert "site:bbc.com" in url


@pytest.fixture
def skip_deps_check():
    """Bypass the 'scraping' extra deps check for unit tests."""
    with patch(
        "unstructured_mapping.web_scraping.backfill._has_scraping_deps",
        return_value=True,
    ):
        yield


def _article(url: str, day: date | None) -> Article:
    pub = (
        datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
        if day is not None
        else None
    )
    return Article(
        title="t",
        body="b",
        url=url,
        source="ap",
        published=pub,
    )


def test_archive_scraper_post_filters_by_pubdate(skip_deps_check):
    """Articles outside the target day must be dropped.

    Google News ``before:`` is approximate; this filter is what
    keeps a backfill for day D from including day D+1 leakage.
    """
    target = date(2026, 4, 18)
    on_day = _article("u1", target)
    next_day = _article("u2", date(2026, 4, 19))
    no_date = _article("u3", None)

    with ArchiveScraper(
        domain="apnews.com",
        source="ap",
        day=target,
    ) as scraper:
        with patch.object(
            ArchiveScraper.__mro__[1],
            "fetch",
            return_value=[on_day, next_day, no_date],
        ):
            result = scraper.fetch()

    assert [a.url for a in result] == ["u1"]


def test_archive_scraper_overrides_source_label(skip_deps_check):
    """Backfilled articles must carry the live source label."""
    with ArchiveScraper(
        domain="bbc.com",
        source="bbc",
        day=date(2026, 4, 18),
    ) as scraper:
        assert scraper.source == "bbc"


def test_fetch_range_iterates_day_by_day_and_dedupes(skip_deps_check):
    """One query per day, results merged with URL dedup."""
    day1 = date(2026, 4, 17)
    day2 = date(2026, 4, 18)
    a_day1 = _article("u-shared", day1)
    b_day1 = _article("u-day1-only", day1)
    a_day2 = _article("u-shared", day2)  # dupe URL across days
    c_day2 = _article("u-day2-only", day2)

    calls: list[date] = []

    def fake_fetch(self):
        calls.append(self._target_day)
        if self._target_day == day1:
            return [a_day1, b_day1]
        return [a_day2, c_day2]

    with patch.object(ArchiveScraper, "fetch", fake_fetch):
        result = fetch_range("ap", day1, day2)

    assert calls == [day1, day2]
    urls = sorted(a.url for a in result)
    assert urls == ["u-day1-only", "u-day2-only", "u-shared"]


def test_fetch_range_rejects_unknown_source(skip_deps_check):
    """Unknown source maps to KeyError for explicit failure."""
    with pytest.raises(KeyError):
        fetch_range("cnn", date(2026, 4, 17), date(2026, 4, 17))


def test_archive_sources_map_covers_live_scrapers():
    """Every archive key must match a live ``source`` label."""
    assert set(ARCHIVE_SOURCES.keys()) == {"ap", "bbc", "reuters"}
