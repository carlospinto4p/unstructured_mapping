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

- [x] **HIGH** — Fix N+1 query in `find_co_mentioned()` — each co-mentioned entity triggers a separate `get_entity()` call; JOIN entities in the SQL or batch-fetch
- [x] **HIGH** — Batch alias fetches in bulk entity queries — `find_by_name`, `find_entities_by_type`, etc. call `_load_aliases()` per row; fetch all aliases in one IN query
- [x] **HIGH** — Fix unreliable `total_changes` check in `save_relationship()` — cumulative counter doesn't detect whether *this specific* INSERT succeeded; use pre-check or row count delta
- [x] **MEDIUM** — Add `save_provenances()` bulk method — current single-record `save_provenance()` causes N queries when saving multiple mentions
- [x] **MEDIUM** — Eliminate duplicate COUNT query in `db_health._run_report()` — total is queried in `_section_overall()` then again in the orchestrator
- [x] **LOW** — Use `lxml` parser in `BBCScraper._parse_article()` for 3-5x speedup over `html.parser` — add `lxml` as optional dependency

#### KG design review (v0.11.21)

- [x] **MEDIUM** — Add `rating` RELATION_KIND to relationships.md — aliases: rated_by, downgraded_by, upgraded_by; covers credit rating changes (S&P, Moody's, Fitch)
- [x] **LOW** — Add `find_relationships_by_type(relation_type)` query method — filter relationships by raw string before RELATION_KIND normalization
- [x] **LOW** — Fix "other six" → "other eight" in design.md ROLE/RELATION_KIND section (line 93)

#### KG design review (v0.11.25)

- [x] **MEDIUM** — Add corporate structure, location, and membership relationship patterns to `relationships.md` — `subsidiary_of`/`parent_of`, `headquartered_in`, `member_of` with corresponding RELATION_KIND entries
- [x] **LOW** — Add `KnowledgeStore.find_entities_by_status()` query method — filter by `EntityStatus` (e.g. all ACTIVE entities)

#### KG design review (v0.11.27)

- [x] **MEDIUM** — Add missing RELATION_KINDs: governance, market_structure, policy, classification, causality, partnership — covers 11 previously unmapped relation_types
- [x] **LOW** — Add PLACE/city subtype in `subtypes.md` — financial hubs (Tokyo, Frankfurt, Hong Kong) are distinct from markets and regions
- [x] **LOW** — Update design.md query section with methods added in v0.11.23–v0.11.25: `find_relationships_by_type`, `find_entities_by_status`

#### KG design review (v0.11.29)

- [x] **HIGH** — Fix NULL valid_from in relationship PK — SQLite NULL != NULL allows silent duplicate unbounded relationships; use sentinel empty string
- [x] **MEDIUM** — Add analyst coverage and sector_event relationship patterns to `relationships.md` — `PERSON/analyst → covers → ASSET/equity`, `TOPIC/sector_event → triggers → METRIC`, add `analyst_coverage` and `event_trigger` RELATION_KINDs
- [x] **LOW** — Add `KnowledgeStore.get_relationships_between(source_id, target_id)` query method — direct two-entity relationship lookup

#### KG design review (v0.11.31)

- [x] **HIGH** — Fix sentinel inconsistency in `_log_relationship()` — use `""` sentinel for valid_from in relationship_history matching relationships table
- [x] **MEDIUM** — Fix RELATION_KIND semantic groupings: move `belongs_to` to `classification`; move `spun_off`/`merged_with`/`founded` to `corporate_structure`; keep `causality` for macro patterns only
- [x] **LOW** — Update `schema.md` valid_from column with `""` sentinel note for NULL-safe PK dedup

#### Pipeline foundation (detection → resolution → extraction)

- [ ] **HIGH** — Entity detection module: `EntityDetector` ABC + `RuleBasedDetector` using alias trie matching — baseline detector that finds entity mentions in text by matching against KG aliases
- [ ] **HIGH** — Entity resolution module: `EntityResolver` ABC + `AliasResolver` for exact alias lookup — resolves detected mentions to KG entities; baseline before LLM-based resolution
- [ ] **HIGH** — Pipeline orchestration: `Pipeline` class wiring detection → resolution → provenance creation — process an article and produce entity mentions linked to KG
- [ ] **MEDIUM** — LLM-based entity resolver using Claude API — reads entity descriptions + context snippets to disambiguate when alias lookup returns multiple candidates
- [ ] **MEDIUM** — Relationship extraction module: `RelationshipExtractor` ABC + `LLMExtractor` — extract relationships between resolved entities from article text
- [ ] **MEDIUM** — KG validation: temporal consistency (valid_until >= valid_from), alias collision detection across entities, entity-type relationship constraints
- [x] **LOW** — Custom exceptions module (`exceptions.py`) — `EntityNotFound`, `ResolutionAmbiguous`, `ValidationError` replacing generic `ValueError`
#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance
