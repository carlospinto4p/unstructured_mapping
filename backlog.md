## Backlog

### 2026 March 30th

#### Web scraping — unstructured corpus

- [x] Create `web_scraping` module with base scraper interface
- [x] Implement Reuters scraper (first source)
- [x] Implement AP News scraper
- [x] Implement BBC News scraper

#### Refactoring (v0.4.0 review)

- [x] Extract shared `_parse_date()` into `web_scraping/parsing.py` — duplicated in `bbc.py` and `reuters.py`
- [x] Align scraper interfaces: rename `ReutersScraper.feed_url` → `feed_urls` (str | list), add `fetch_full_text` flag
- [x] Move shared feed-fetching logic into `Scraper` base class (template method)
- [x] Add `__enter__`/`__exit__` to `ArticleStore` for context manager support
- [x] Add `logging` to `BBCScraper._extract_body()` and `ArticleStore.save()` instead of silent exception swallowing
- [x] Move `_USER_AGENT` and `DEFAULT_TIMEOUT` into shared `web_scraping/config.py`

#### Performance (v0.4.2 review)

- [x] **HIGH** — Use `httpx.Client` with connection pooling in `Scraper` base class instead of per-request `httpx.get()`
- [x] **HIGH** — Parallelize full-text extraction in `BBCScraper` with async or threading (sequential HTTP is the main bottleneck)
- [x] **HIGH** — Use `executemany()` in `ArticleStore.save()` instead of row-by-row inserts
- [ ] **MEDIUM** — Add `limit`/`offset` pagination to `ArticleStore.load()` to avoid loading all rows into memory
- [ ] **MEDIUM** — Simplify date parsing in `parsing.py`: use `datetime(*parsed[:6])` instead of `mktime` roundtrip
- [ ] **LOW** — Add SQLite indexes on `source` and `scraped_at` columns
- [ ] **LOW** — Pass `resp.content` (bytes) to BeautifulSoup instead of `resp.text` to skip redundant decode

#### Knowledge graph — entity store

- [ ] Define KG data model:
    - Unique identifiers for entities
    - Entity types (person, org, location, event, concept, ...)
    - Descriptions and hints
    - Temporal dimension: datetime range the entity existed / was valid (point-in-time KG)
    - Relationships (graph structure)
    - Provenance: source/origin of the entity, traces to all texts where it appears
    - Embeddings per entity (for similarity / resolution)
- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Design storage layer for the KG (graph DB or equivalent)
