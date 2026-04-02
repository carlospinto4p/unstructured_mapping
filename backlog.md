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

- [x] Define KG data model:
    - Unique identifiers for entities
    - Entity types (person, org, location, event, concept, ...)
    - Descriptions and hints
    - Temporal dimension: datetime range the entity existed / was valid (point-in-time KG)
    - Relationships (graph structure)
    - Provenance: source/origin of the entity, traces to all texts where it appears
    - Embeddings per entity (for similarity / resolution)
- [x] Build Wikipedia/Wikidata seed pipeline to populate the KG — moved to post-population

### 2026 April 2nd

#### Subtype taxonomy refinement (v0.10.0 follow-up)

- [x] Define canonical subtype conventions per entity type — document recommended values (e.g. ORGANIZATION subtypes: company, central_bank, regulator, exchange, fund, multilateral) so LLM ingestion produces consistent values
- [x] Consider whether TOPIC subtypes are useful for financial focus (e.g. sector, macro_theme, geopolitical) or if TOPIC remains broad by design
- [x] Evaluate whether ASSET needs a `ticker` or `identifier` field beyond aliases — resolved: aliases suffice for detection; `external_ids` table (post-population) handles structured joins
- [x] Explore METRIC metadata: release schedule (monthly, quarterly), issuing body (BLS, Fed), and expected-vs-actual framing — resolved: issuing body as relationship, schedule and expected-vs-actual out of KG scope
- [x] Consider cross-type relationship patterns for financial analysis: ORGANIZATION/central_bank → METRIC/monetary_policy, PERSON/policymaker → LEGISLATION/regulation — document common patterns as examples in docs
- [x] Design storage layer for the KG (graph DB or equivalent)

#### KG design review (v0.10.2)

- [x] Add co-mention query: `find_co_mentioned(entity_id, since)` with `(document_id, entity_id)` index on provenance — core query for event-driven strategies
- [x] Add optional `sentiment` field to Provenance — resolved: sentiment is analysis output, not provenance; belongs in a future signal/analysis layer, not the KG
- [x] Add ASSET/etf and METRIC/earnings subtypes — ETFs and earnings data are the most common quant query targets currently missing
- [x] Document VIX dual-nature in subtypes.md — guidance for entities that are both tradeable and indicators, with cross-reference relationship pattern
- [x] Split ORGANIZATION/fund into fund_manager vs fund vehicle — quants tracking ETF flows need to distinguish BlackRock (manager) from iShares ETF (product)
- [x] Add temporal provenance query with `(entity_id, detected_at)` index — "mentions in the last 24h" must be fast
- [x] Plan relationship attributes — resolved: quantitative values (ownership %, ratings, price targets) are out of KG scope; external tables joined via entity_id
- [x] Add `updated_at` field to Entity for freshness tracking and cache invalidation

#### Refactoring (v0.11.15 review)

- [x] **HIGH** — Extract `_ENTITY_SELECT` constant in `storage.py` — same 11-column SELECT list repeated 4 times across `get_entity`, `find_by_name`, `find_entities_by_type`, `find_entities_by_subtype`
- [x] **HIGH** — Unify `find_co_mentioned()` query branches — two near-identical SQL blocks differ only by an optional WHERE clause; build query conditionally
- [x] **MEDIUM** — Split `db_health._run_report()` (142 lines) into per-section helpers — one function per report section for testability
- [x] **MEDIUM** — Split `ArticleStore._migrate()` (102 lines) into per-step helpers — one function per migration step
- [x] **MEDIUM** — Extract `_sync_aliases()` helper from `save_entity()` — alias delete+insert logic is a distinct responsibility
- [x] **LOW** — Rename `_row_to_rel_rev` → `_row_to_relationship_rev` for consistency with other `_row_to_*` helpers
- [x] **LOW** — Extract `_redirect_entity_references()` helper from `merge_entities()` — five repetitive UPDATE statements

#### Performance (v0.11.18 review)

- [ ] **HIGH** — Fix N+1 query in `find_co_mentioned()` — each co-mentioned entity triggers a separate `get_entity()` call; JOIN entities in the SQL or batch-fetch
- [ ] **HIGH** — Batch alias fetches in bulk entity queries — `find_by_name`, `find_entities_by_type`, etc. call `_load_aliases()` per row; fetch all aliases in one IN query
- [ ] **HIGH** — Fix unreliable `total_changes` check in `save_relationship()` — cumulative counter doesn't detect whether *this specific* INSERT succeeded; use pre-check or row count delta
- [ ] **MEDIUM** — Add `save_provenances()` bulk method — current single-record `save_provenance()` causes N queries when saving multiple mentions
- [ ] **MEDIUM** — Eliminate duplicate COUNT query in `db_health._run_report()` — total is queried in `_section_overall()` then again in the orchestrator
- [ ] **LOW** — Use `lxml` parser in `BBCScraper._parse_article()` for 3-5x speedup over `html.parser` — add `lxml` as optional dependency

#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance
