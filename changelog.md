## Changelog

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
