## Backlog

### 2026 March 30th

#### Refactoring (v0.5.7 review)

- [x] **HIGH** — Lift `_fetch_full_text`, `_max_workers`, and the `_enrich()` template into base `Scraper` — `APScraper` and `BBCScraper` duplicate identical init params and the same guard-then-parallel-map-then-replace pattern
- [x] **MEDIUM** — Replace magic tuple indices in `APScraper._enrich()` with a `NamedTuple` — `results.get(a.url, ("", ""))[0]`/`[1]` is unclear
- [x] **MEDIUM** — Extract shared `logging.basicConfig(...)` setup from `cli/scrape.py` and `cli/scheduler.py` into a `cli/_logging.py` helper
- [x] **LOW** — Extract Google News RSS URL builder — `ap.py` and `reuters.py` duplicate the same `news.google.com/rss/search?q=when:24h+allinurl:` pattern

#### Performance (v0.5.7 review)

- [x] **HIGH** — Use `cursor.rowcount` or `total_changes` in `ArticleStore.save()` instead of two `SELECT COUNT(*)` full-table scans to count inserted rows
- [x] **HIGH** — Parallelize RSS feed fetching in `Scraper.fetch()` — feeds are fetched sequentially, wasteful with 16 BBC feeds
- [x] **MEDIUM** — Single `GROUP BY source` query in `_show_stats()` instead of N+1 separate `COUNT(*)` calls
- [x] **MEDIUM** — Use walrus operator in `BBCScraper._parse_article()` to avoid calling `get_text(strip=True)` twice per paragraph
- [x] **LOW** — Add composite index `(source, scraped_at DESC)` to replace separate `idx_source` — covers filtered+ordered queries in `load()`

#### Refactoring (v0.5.8 review)

- [x] **MEDIUM** — Simplify `ArticleStore.count()` — two near-identical branches for filtered/unfiltered can be a single query path with conditional WHERE
- [x] **MEDIUM** — Rename `APScraper._fetch_text()` → `_fetch_page()` and `_decode_url()` → `_resolve_url()` for consistency with `BBCScraper` naming
- [x] **LOW** — Narrow bare `except Exception` in `scheduler.py` to specific types (`OSError`, `httpx.HTTPError`)

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
