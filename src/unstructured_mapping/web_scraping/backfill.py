"""Historical backfill via Google News date-ranged search.

Google News RSS accepts ``after:YYYY-MM-DD`` and
``before:YYYY-MM-DD`` operators combined with ``site:domain``.
This lets us recover articles missed by the live scrapers during
outages, without maintaining per-source archive parsers.

All URLs returned by the search are Google News redirects, so the
backfill path always decodes them with :mod:`googlenewsdecoder` and
extracts body text with :mod:`trafilatura`. This uniform path works
regardless of the source domain, which is why backfill uses it for
BBC too — BBC's live ``<article>``-tag parser cannot consume Google
News redirects.

Google News decoding + text extraction helpers live in
:mod:`._gnews` and are shared with :class:`~.ap.APScraper`.
The two scrapers have different error-handling contracts around the
optional ``scraping`` extra — AP degrades gracefully when deps are
missing, backfill fails fast — so the dep check is called from each
init path rather than the shared module.
"""

import logging
from datetime import date, timedelta

from unstructured_mapping.web_scraping._gnews import (
    _extract_text,
    _has_scraping_deps,
    _resolve_gnews_url,
)
from unstructured_mapping.web_scraping.base import Scraper
from unstructured_mapping.web_scraping.config import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_TIMEOUT,
)
from unstructured_mapping.web_scraping.models import (
    Article,
    ExtractionResult,
)

logger = logging.getLogger(__name__)


#: Short source label → site domain used in the ``site:`` filter.
#: Must stay in sync with the live scrapers' ``source`` class var
#: so backfilled rows share provenance with live rows.
ARCHIVE_SOURCES: dict[str, str] = {
    "ap": "apnews.com",
    "bbc": "bbc.com",
    "reuters": "reuters.com",
}


def build_archive_query_url(domain: str, day: date) -> str:
    """Build a Google News RSS URL for a single-day site-filtered query.

    Uses a one-day window (``after:day before:day+1``) because Google
    News caps each RSS query at ~100 results. For multi-day backfill,
    call :func:`fetch_range`, which iterates day by day and merges.

    :param domain: Site filter, e.g. ``"apnews.com"``.
    :param day: Target publication day (interpreted in UTC).
    :return: Fully-formed Google News RSS URL.
    """
    start = day.isoformat()
    end = (day + timedelta(days=1)).isoformat()
    q = f"site:{domain}+after:{start}+before:{end}"
    return (
        f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    )


class ArchiveScraper(Scraper):
    """Backfill scraper for a single historical day, one source.

    Feeds a one-day Google News search (``site:domain`` +
    ``after``/``before``) through the shared :class:`Scraper`
    pipeline, then post-filters by ``pubDate`` to drop the
    occasional article from the day after — Google News' ``before:``
    bound is inclusive-ish and sometimes leaks one day.

    :param domain: Site filter, e.g. ``"apnews.com"``.
    :param source: Short label for the ``source`` column in the
        articles DB. Must match the live scraper's ``source``
        value (``"ap"``, ``"bbc"``, ``"reuters"``) so backfilled
        rows share provenance with live rows.
    :param day: Target publication day.
    :param timeout: HTTP request timeout in seconds.
    :param max_workers: Thread pool size for full-text extraction.
    :raises RuntimeError: If the ``scraping`` extra is not installed.
    """

    # Placeholder to satisfy ``Scraper.__init_subclass__``. Overridden
    # at instance level in ``__init__`` so one class handles every
    # source domain.
    source = "archive"
    default_fetch_full_text = True

    def __init__(
        self,
        domain: str,
        source: str,
        day: date,
        timeout: float = DEFAULT_TIMEOUT,
        max_workers: int = DEFAULT_MAX_WORKERS,
    ) -> None:
        if not _has_scraping_deps():
            raise RuntimeError(
                "Backfill requires the 'scraping' extra "
                "(googlenewsdecoder + trafilatura). "
                "Install with: uv sync --all-extras"
            )
        feed_url = build_archive_query_url(domain, day)
        super().__init__(
            feed_urls=feed_url,
            timeout=timeout,
            max_workers=max_workers,
        )
        self.source = source
        self._target_day = day

    def _extract_body(self, gnews_url: str) -> ExtractionResult:
        """Decode gnews URL and extract text (AP-style)."""
        real_url = _resolve_gnews_url(gnews_url)
        if not real_url:
            return ExtractionResult()
        text = _extract_text(real_url)
        return ExtractionResult(body=text, url=real_url)

    def fetch(self) -> list[Article]:
        """Fetch articles for the target day, filtered by ``pubDate``.

        Google News' ``before:`` bound sometimes returns articles from
        the day after; this post-filter drops them so the backfill
        matches the intended day exactly. Articles without a
        ``published`` field are dropped (can't verify the day).

        :return: Articles published on ``self._target_day``.
        """
        articles = super().fetch()
        return [
            a
            for a in articles
            if a.published is not None
            and a.published.date() == self._target_day
        ]


def fetch_range(
    source: str,
    from_date: date,
    until_date: date,
    timeout: float = DEFAULT_TIMEOUT,
    max_workers: int = DEFAULT_MAX_WORKERS,
) -> list[Article]:
    """Backfill one source across a closed day range.

    Runs one :class:`ArchiveScraper` per day to stay within Google
    News' ~100-results-per-query cap, then deduplicates by URL.

    :param source: Key from :data:`ARCHIVE_SOURCES`.
    :param from_date: First day to fetch (inclusive, UTC).
    :param until_date: Last day to fetch (inclusive, UTC).
    :param timeout: HTTP request timeout in seconds.
    :param max_workers: Thread pool size for full-text extraction.
    :return: Deduplicated list of articles.
    :raises KeyError: If ``source`` is not in :data:`ARCHIVE_SOURCES`.
    """
    domain = ARCHIVE_SOURCES[source]
    all_articles: dict[str, Article] = {}
    day = from_date
    while day <= until_date:
        logger.info("Backfilling %s for %s...", source, day)
        with ArchiveScraper(
            domain=domain,
            source=source,
            day=day,
            timeout=timeout,
            max_workers=max_workers,
        ) as scraper:
            for a in scraper.fetch():
                all_articles.setdefault(a.url, a)
        day += timedelta(days=1)
    return list(all_articles.values())
