## Changelog

### v0.5.10 - 2nd April 2026

- Added `cli/db_health.py` — database health report CLI
  showing per-source counts, last scrape timestamps, recent
  batches, daily coverage gaps, and data quality checks
- Added `/db-health` skill in `.claude/commands/`


### v0.5.9 - 2nd April 2026

- Simplified `ArticleStore.count()` — merged two branches
  into single query path with conditional WHERE
- Renamed `APScraper._decode_url()` → `_resolve_url()` and
  `_fetch_text()` → `_fetch_page()` for consistency with
  `BBCScraper` naming
- Narrowed bare `except Exception` in `scheduler.py` to
  `OSError`, `httpx.HTTPError`, `ValueError`


### v0.5.8 - 1st April 2026

- Replaced two `SELECT COUNT(*)` scans in
  `ArticleStore.save()` with `total_changes` for O(1)
  insert counting
- Parallelized RSS feed fetching in `Scraper.fetch()`
  via `_parallel_map()`
- Added `ArticleStore.counts_by_source()` with single
  `GROUP BY` query, used in `_show_stats()`
- Fixed double `get_text()` call in
  `BBCScraper._parse_article()` with walrus operator
- Replaced `idx_source` with composite index
  `(source, scraped_at DESC)` for filtered+ordered queries


### v0.5.7 - 1st April 2026

- Lifted `_fetch_full_text`, `_max_workers`, and `_enrich()`
  template into base `Scraper` — subclasses now only override
  `_extract_body()`
- Added `ExtractionResult` NamedTuple in `models.py`,
  replacing magic tuple indices in `APScraper`
- Added `cli/_logging.py` with shared `setup_logging()`,
  replacing duplicate `logging.basicConfig()` in
  `cli/scrape.py` and `cli/scheduler.py`
- Added `google_news_rss()` builder in `config.py`,
  replacing duplicate URL patterns in `ap.py` and
  `reuters.py`


### v0.5.6 - 31st March 2026

- Added `Scraper._parallel_map()` helper, replacing
  duplicate `ThreadPoolExecutor` patterns in `BBCScraper`
  and `APScraper`
- Fixed scraper resource leak in CLI loop — now uses
  context managers
- Converted all test scraper usage to context managers
- Renamed `log` to `logger` in `scheduler.py` for
  consistency
- Added `exc_info=True` to `APScraper` warning logs for
  exception context


### v0.5.5 - 31st March 2026

- Replaced `print()` with `logging` in `cli/scrape.py`
- Replaced bare `except Exception` in `APScraper` with
  specific types (`ValueError`, `KeyError`, `OSError`)
- Split `BBCScraper._extract_body()` into `_fetch_page()`
  and `_parse_article()`
- Split `APScraper._extract_body()` into `_decode_url()`
  and `_fetch_text()`


### v0.5.4 - 31st March 2026

- Refactored `Scraper` base class:
    - Added default `_parse_feed()` with shared RSS parsing
    - Added `_enrich()` hook for subclass enrichment
- Simplified `ReutersScraper`: removed redundant
  `_parse_feed()` override (inherits from base)
- Refactored `BBCScraper` and `APScraper` to use
  `_enrich()` instead of duplicating `_parse_feed()`
- Refactored `cli/scrape.py`:
    - Replaced three duplicate blocks with `_build_scraper()`
      factory and source loop
    - Extracted `_SOURCES` constant
- Centralized `DEFAULT_MAX_WORKERS` in `config.py`


### v0.5.3 - 31st March 2026

- Added `limit`/`offset` pagination to `ArticleStore.load()`
- Added SQLite indexes on `source` and `scraped_at` columns
- Simplified `parse_feed_date()`: use `datetime(*parsed[:6])`
  instead of `mktime` roundtrip
- Changed `BBCScraper._extract_body()` to pass `resp.content`
  (bytes) to BeautifulSoup instead of `resp.text`


### v0.5.2 - 31st March 2026

- Added full-text extraction to `APScraper` using
  `trafilatura` and `googlenewsdecoder`
- Added `scraping` optional dependency group
  (`pip install unstructured-mapping[scraping]`)
- Parallel extraction with `ThreadPoolExecutor` (8 workers)
- Graceful fallback to RSS summary when extraction fails
  or optional deps not installed
- Docker image now installs `scraping` extra by default


### v0.5.1 - 31st March 2026

- Added `APScraper` in `web_scraping/ap.py` for AP News
  headlines via Google News RSS
- Updated CLI and Docker to include `ap` as a default source


### v0.5.0 - 31st March 2026

- Added Docker deployment for automated news scraping:
    - `Dockerfile` with Python 3.14-slim and `uv`
    - `docker-compose.yml` with `restart: unless-stopped`
    - `.dockerignore` for lean image builds
- Added `scheduler` CLI module with configurable interval
  via `SCRAPE_INTERVAL_HOURS` environment variable
- Volume-mounted `data/` directory persists SQLite database
  across container restarts


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
