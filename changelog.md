## Changelog

### v0.4.3 - 31st March 2026

- Optimized `Scraper` base class:
    - Persistent `httpx.Client` with connection pooling
    - Added `close()` and context manager support
- Optimized `BBCScraper` full-text extraction:
    - Parallel fetching with `ThreadPoolExecutor` (8 workers)
    - ~7x speedup (21s vs ~150s for 400 articles)
- Optimized `ArticleStore.save()`:
    - Bulk `INSERT OR IGNORE` with `executemany()`
    - 506 articles saved in 47ms


### v0.4.2 - 31st March 2026

- Added context manager support to `ArticleStore`
- Added `logging` to `BBCScraper._extract_body()` and
  `ArticleStore.save()` replacing silent exceptions
- Added `web_scraping/config.py` with shared `USER_AGENT`
  and `DEFAULT_TIMEOUT` constants


### v0.4.1 - 30th March 2026

- Refactored scraper architecture:
    - Extracted `parse_feed_date()` into `web_scraping/parsing.py`
    - Moved `fetch()` with dedup logic into `Scraper` base class
      (template method pattern)
    - Aligned `ReutersScraper` to use `feed_urls` (str | list)
      matching `BBCScraper` interface
    - Removed duplicated date parsing and feed-fetching code


### v0.4.0 - 30th March 2026

- Added multi-feed support to `BBCScraper`:
    - `feed_urls` parameter accepts a string or list
    - `BBC_FEEDS` dict with 16 topic feeds
    - In-memory deduplication across feeds
- Added `cli.scrape` CLI script with argparse:
    - `--sources`, `--feeds`, `--db`, `--no-full-text`,
      `--stats`, `--timeout` options
    - Run via `uv run python -m unstructured_mapping.cli.scrape`


### v0.3.0 - 30th March 2026

- Added `BBCScraper` with full-text extraction via
  BeautifulSoup
- Added `ArticleStore` for SQLite-backed article persistence
- Added `beautifulsoup4` dependency


### v0.2.1 - 30th March 2026

- Fixed `ReutersScraper` to follow HTTP redirects
- Updated default feed URL to Google News RSS (Reuters
  discontinued their public RSS feeds)


### v0.2.0 - 30th March 2026

- Added `web_scraping` module:
    - `Article` dataclass for scraped content
    - `Scraper` ABC as base interface
    - `ReutersScraper` for fetching articles via RSS
- Added `httpx` and `feedparser` dependencies
- Added unit tests for web scraping module


### v0.1.0 - 30th March 2026

- Initial project skeleton
- Added `pyproject.toml`, `CLAUDE.md`, `README.md`
- Added `.claude/` rules, commands, and settings
- Created `src/unstructured_mapping/` package with empty modules
- Created `tests/unit/` structure with `conftest.py`
