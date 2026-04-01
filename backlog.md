## Backlog

### 2026 March 30th

#### Refactoring (v0.5.7 review)

- [x] **HIGH** — Lift `_fetch_full_text`, `_max_workers`, and the `_enrich()` template into base `Scraper` — `APScraper` and `BBCScraper` duplicate identical init params and the same guard-then-parallel-map-then-replace pattern
- [x] **MEDIUM** — Replace magic tuple indices in `APScraper._enrich()` with a `NamedTuple` — `results.get(a.url, ("", ""))[0]`/`[1]` is unclear
- [x] **MEDIUM** — Extract shared `logging.basicConfig(...)` setup from `cli/scrape.py` and `cli/scheduler.py` into a `cli/_logging.py` helper
- [x] **LOW** — Extract Google News RSS URL builder — `ap.py` and `reuters.py` duplicate the same `news.google.com/rss/search?q=when:24h+allinurl:` pattern

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
