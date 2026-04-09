## Changelog

### v0.20.0 - 9th April 2026

- Added `pipeline/llm_provider.py`:
  - `LLMProvider` ABC: `generate()`, `model_name`,
    `provider_name`, `context_window`,
    `supports_json_mode`. Contract matches
    `docs/pipeline/llm_interface.md`.
  - Exception hierarchy: `LLMProviderError`,
    `LLMConnectionError`, `LLMTimeoutError`,
    `LLMEmptyResponseError`.
- Added `pipeline/llm_ollama.py`:
  - `OllamaProvider`: Ollama-first concrete
    implementation. Uses the `ollama` Python package,
    wraps `httpx.ConnectError`/`ConnectTimeout` as
    `LLMConnectionError`, `httpx.TimeoutException` as
    `LLMTimeoutError`, and empty responses as
    `LLMEmptyResponseError`. Auto-detects
    `context_window` via `/api/show` with a 4096-token
    fallback; explicit override skips the lookup.
    Optional import of `ollama` so the ABC module
    stays slim.
- Added `pyproject.toml`:
  - `llm` optional dependency group pinning
    `ollama>=0.4.0`. Added to `dev` too for tests.
- Added `tests/unit/test_llm_provider.py`: 18 tests
  covering the ABC contract, exception hierarchy,
  OllamaProvider happy path (dict and attribute
  response shapes), error translation
  (connection/timeout/empty/generic), and context
  window auto-detection.
- Updated `README.md`: new "LLM Providers" section
  with the OllamaProvider usage example.
- Updated `pipeline/__init__.py`: export
  `LLMProvider`, `OllamaProvider`, and the LLM
  exception hierarchy.
- Updated `backlog.md`: added `ClaudeProvider`
  follow-up item so a second concrete provider can be
  implemented once the baseline is exercised.


### v0.19.0 - 9th April 2026

- Added `pipeline/orchestrator.py`:
  - `Pipeline`: wires detection, resolution, and
    provenance persistence into a single callable.
    `run(articles)` opens an `IngestionRun`, processes
    each article in isolation (per-article failures
    are recorded, run continues), and finalizes the
    run with aggregated counts. `process_article()`
    exposed as a lower-level entry point for callers
    that don't need run tracking. `skip_processed`
    constructor flag controls idempotency.
  - `ArticleResult`: per-article outcome exposing the
    raw `ResolutionResult`, provenance count, skip
    flag, and error message.
  - `PipelineResult`: aggregate outcome with the run
    ID, per-article results, and totals.
- Added `knowledge_graph/_provenance_mixin.py`:
  - `KnowledgeStore.has_document_provenance()`: O(log
    n) point lookup backing pipeline idempotency.
- Added `tests/unit/`:
  - `test_pipeline.py`: 11 tests (happy path, skip,
    reprocess, per-article isolation, stub wiring).
  - `test_kg_provenance.py::test_has_document_provenance`
- Added `docs/pipeline/orchestration.md`: design notes
  for the orchestrator (single-chunk articles,
  per-article isolation, provenance-based idempotency,
  constructor injection, deferred extraction stage).
- Updated `README.md`: Quick Start and new
  "Pipeline Orchestration" section use the real API.


### v0.18.3 - 9th April 2026

- Updated `knowledge_graph/_entity_mixin.py`:
  `_log_entity()` now passes `entity.aliases` directly
  to `json.dumps()` instead of converting the tuple to
  a list first — `json.dumps()` accepts tuples, so the
  intermediate allocation was wasted on every entity
  save and history write.


### v0.18.2 - 9th April 2026

- Updated `web_scraping/`:
  - `base.py`: split parsing from enrichment.
    `Scraper._parse_feed()` now returns unenriched
    articles; `Scraper.fetch()` dedupes URLs across
    feeds first and calls `_enrich()` exactly once on
    the deduped list, so a URL appearing in multiple
    feeds triggers at most one full-text extraction.
  - `bbc.py`: `BBCScraper._parse_feed()` matches the
    new contract (drops `_SKIP_URL_RE` entries but no
    longer enriches).
- Added `tests/unit/test_web_scraping.py`:
  - `test_fetch_enriches_duplicate_url_once`


### v0.18.1 - 9th April 2026

- Updated `knowledge_graph/_entity_mixin.py`: added
  optional `limit` parameter to entity search methods:
  - `find_entities_by_type()`
  - `find_entities_by_subtype()`
  - `find_entities_by_status()`
  - `find_by_name_prefix()`
  - `find_entities_since()`
- Updated `knowledge_graph/_provenance_mixin.py`: added
  optional `limit` parameter to `find_co_mentioned()`.
  Caps the result set before alias batch-loading,
  avoiding unbounded memory use on large KGs.
- Added `tests/unit/`:
  - `test_kg_entities.py::test_entity_search_limit`
  - `test_kg_provenance.py::test_find_co_mentioned_limit`


### v0.18.0 - 9th April 2026

- Added `knowledge_graph/_relationship_mixin.py`:
  - `RelationshipMixin.save_relationships()`: bulk insert
    method mirroring `save_provenances()`. Dedupes input
    against itself and the existing rows (by PK
    `source_id, target_id, relation_type, valid_from`),
    then uses `executemany` for a single batched INSERT
    and logs only newly inserted rows to
    `relationship_history`.
- Added `tests/unit/test_kg_relationships.py`:
  - `test_save_relationships_bulk_insert`
  - `test_save_relationships_skips_duplicates`
  - `test_save_relationships_empty`


### v0.17.5 - 8th April 2026

- Refactored `knowledge_graph/_helpers.py`:
  - Replaced 6 fragile tuple-index row converters with `sqlite3.Row`-based named column access
  - Set `row_factory = sqlite3.Row` in `storage_base.py` for all stores
  - Fixed `find_co_mentioned()` row slicing to use named access
- Refactored `web_scraping/base.py`:
  - Simplified nested comprehension in `Scraper._enrich()` to a plain loop
- Fixed `cli/scheduler.py`:
  - Narrowed exception handling from `ValueError` to `sqlite3.Error`


### v0.17.4 - 8th April 2026

- Refactored `knowledge_graph/storage.py` (1482 lines) into domain-focused mixins:
  - `_helpers.py`: shared SQL fragments, datetime utilities, row converters
  - `_entity_mixin.py`: entity CRUD, search, merge, audit history
  - `_provenance_mixin.py`: provenance CRUD, co-mention queries
  - `_relationship_mixin.py`: relationship CRUD, qualifiers, history
  - `_run_mixin.py`: ingestion run tracking
  - `storage.py`: DDL, migrations, and `KnowledgeStore` class composing all mixins


### v0.17.3 - 8th April 2026

- Refactored `tests/unit/`:
  - Split `test_knowledge_graph.py` (1796 lines) into 4 focused modules:
    - `test_kg_models.py`: data model and enum tests
    - `test_kg_entities.py`: entity CRUD, search, merge, subtypes, history
    - `test_kg_provenance.py`: provenance, co-mentions, ingestion runs, migration
    - `test_kg_relationships.py`: relationship CRUD, qualifiers, history
  - Moved shared `_make_entity()` helper to `conftest.py`


### v0.17.2 - 7th April 2026

- Updated `docs/pipeline/`: replaced ASCII art diagrams with
  Mermaid across all pipeline documentation:
  - `chunking.md`: pipeline flow diagram.
  - `detection.md`: pipeline position diagram.
  - `llm_interface.md`: token budget allocation diagram.
  - `models.md`: data flow summary diagram.
  - `resolution.md`: pipeline position and resolution
    decision flow diagrams.


### v0.17.1 - 7th April 2026

- Added `docs/pipeline/resolution.md`: two-tier resolution
  strategy, AliasResolver decision logic, context snippet
  extraction algorithm, data flow diagram, design decisions
  (conservative resolution, section_name propagation,
  configurable context window), and future extensions.


### v0.17.0 - 7th April 2026

- Added `pipeline/resolution.py`:
  - `EntityResolver` ABC with `resolve(chunk, mentions)`
    interface.
  - `AliasResolver`: baseline resolver that resolves
    single-candidate mentions directly and leaves
    zero/multi-candidate mentions for LLM disambiguation.
  - `_extract_snippet()`: context window extraction with
    word-boundary trimming and ellipsis indicators.
- Added `pipeline/models.py`:
  - `ResolvedMention`: mention matched to a KG entity.
  - `ResolutionResult`: separates resolved from unresolved
    mentions.
- Added `tests/unit/test_resolution.py`: 24 tests covering
  models, snippet extraction, and resolver logic.


### v0.16.1 - 7th April 2026

- Added `docs/pipeline/detection.md`: Aho-Corasick algorithm
  explanation, complexity analysis, design decisions
  (case-insensitive matching, word-boundary enforcement,
  canonical name indexing, output ordering), and future
  extensions.


### v0.16.0 - 7th April 2026

- Added `pipeline` package:
  - `models.py`: `Chunk` and `Mention` dataclasses for
    pipeline stage communication.
  - `detection.py`: `EntityDetector` ABC and
    `RuleBasedDetector` using Aho-Corasick trie for
    O(n) alias matching with word-boundary enforcement.
- Added `tests/unit/test_detection.py`: 33 tests covering
  models, trie construction, scanning, word boundaries,
  and detector integration.


### v0.15.0 - 6th April 2026

- `knowledge_graph/models.py`:
  - Added `IngestionRun` dataclass with `RunStatus` enum for tracking pipeline executions
  - Added `run_id` field to `Provenance` and `Relationship` dataclasses
- `knowledge_graph/storage.py`:
  - Added `ingestion_runs` table with status, counters, and error tracking
  - Added `run_id` column to `provenance` and `relationships` tables (nullable, with migration for existing DBs)
  - Added `save_run()`, `finish_run()`, `get_run()` methods to `KnowledgeStore`
  - Added `run_id` indexes on `provenance` and `relationships`
- `knowledge_graph/__init__.py`:
  - Exported `IngestionRun` and `RunStatus`
- `docs/knowledge_graph/schema.md`:
  - Documented `ingestion_runs` table and `run_id` columns
- `tests/unit/test_knowledge_graph.py`:
  - Added 10 tests: model defaults, CRUD operations, run_id round-trips, migration


### v0.14.9 - 6th April 2026

- `web_scraping/bbc.py`:
  - Added `_SKIP_URL_RE` filter to skip non-article URLs (BBC Sounds podcasts) during feed parsing, before full-text enrichment
  - Overrode `_parse_feed()` to apply URL filtering
- `tests/unit/test_web_scraping.py`:
  - Added `test_bbc_skips_podcast_urls` test
- `backlog.md`:
  - Added podcast transcription pipeline as future enhancement


### v0.14.8 - 5th April 2026

- `.claude/rules/`:
  - Updated `versioning.md`: added changelog
    rotation section (30-version limit, yearly
    archives in `changelog/YYYY.md`).


### v0.14.7 - 5th April 2026

- `.claude/rules/`:
  - Updated `versioning.md`: added changelog
    rotation section (30-version limit, yearly
    archives in `changelog/YYYY.md`).


### v0.14.6 - 5th April 2026

- Rotated changelog: archived 62 old
  entries to `changelog/` yearly files.


### v0.14.5 - 5th April 2026

- `.claude/`:
  - Updated `backlog` skill (v1.4.0): tables now
    always include Priority and Effort columns.


### v0.14.4 - 5th April 2026

- `.claude/hooks/`:
  - Fixed stdin consumption: all hooks now
    capture stdin before piping to python.


### v0.14.3 - 5th April 2026

- `.claude/`:
  - Updated `backlog` skill (v1.3.0): auto-cleans
    completed items before display, shows per-section
    tables when backlog has multiple sections.
  - Updated `backlog` rule: added auto-cleanup
    section.


### v0.14.2 - 5th April 2026

- `.claude/`:
  - Updated `backlog` skill (v1.1.0): auto-cleans
    completed items when 5+ accumulate.
  - Updated `backlog` rule: added auto-cleanup
    section.


### v0.14.1 - 4th April 2026

- `.claude/`:
  - Added `hooks/block-raw-python.sh`: enforces `uv run python` over bare `python`.


### v0.14.0 - 4th April 2026

- `docs/pipeline/`:
  - Added `models.md`: pipeline data models design — stage
    contracts for `IngestionRun`, `Chunk`, `Mention`,
    `EntityProposal`, `ResolvedMention`,
    `ExtractedRelationship`, `ChunkResult`, and
    `DocumentResult`, plus ingestion run table schema.
  - Added `llm_interface.md`: LLM interface design — JSON
    response schemas for entity resolution (pass 1) and
    relationship extraction (pass 2), prompt architecture,
    token budget allocation, retry strategy, and
    `LLMProvider` ABC contract.
  - Updated `design.md`: added cross-references to
    `models.md` and `llm_interface.md`.
- `docs/knowledge_graph/`:
  - Updated `schema.md`: added `section_name` column to
    `provenance` and `relationships` tables for
    section-level queries on long-form documents.


### v0.13.0 - 4th April 2026

- `docs/pipeline/`:
  - Added `chunking.md`: document chunking design covering
    segmentation strategies, cross-chunk entity tracking,
    aggregation, provenance granularity, and cost
    mitigations for long-form documents (research reports,
    earnings transcripts, regulatory filings).
  - Updated `design.md`:
    - Replaced truncation-only "Long articles" section
      with "Long documents" referencing chunking design.
    - Added `segmentation` and `aggregation` to module
      structure.
    - Added chunking to "What this design does NOT cover"
      with cross-reference.


### v0.12.5 - 4th April 2026

- `.claude/rules/`:
  - Normalized `versioning.md` to enhanced canonical
    with detailed sub-bullet guidance.


### v0.12.4 - 4th April 2026

- `.claude/rules/`:
  - Normalized `versioning.md` to canonical template.


### v0.12.3 - 3rd April 2026

- `.claude/rules/`:
  - Normalized `committing.md` to canonical template.


### v0.12.2 - 3rd April 2026

- Removed dead `Null document_ids` check from `db_health`
  — `document_id` has a NOT NULL constraint after
  migration, so the check always returns 0


### v0.12.1 - 3rd April 2026

- Fixed `Null document_ids` showing `None` instead of `0`
  in `db_health` — `SUM(CASE)` returns NULL over empty
  result sets; split into separate `COUNT(*)` queries


### v0.12.0 - 3rd April 2026

- Added `docs/pipeline/design.md` — ingestion pipeline
  design covering architecture, design decisions, and
  trade-offs for each major concern:
  - Two-pass extraction (entities → relationships)
  - Ingestion run tracking with metadata
  - LLM provider abstraction (Ollama first)
  - Auto-create entity policy with quality controls
  - Relevant-entity windowing for context budget
  - Structured output with validation and retry
  - Provenance-based idempotency
  - Per-article error isolation
  - Module structure and dependencies


### v0.11.43 - 3rd April 2026

- `CLAUDE.md`:
  - Normalized to canonical template: added missing
    shared sections, removed low-value sections.


### v0.11.42 - 3rd April 2026

- Added `KnowledgeStore.find_entities_since()` — returns
  entities created after a given datetime, newest first;
  indexed on `created_at` for fast new-entity alerting
- Updated `schema.md` intro to reference `SQLiteStore`
  base class instead of stale `ArticleStore` pattern
- Updated `design.md` with `find_entities_since`
  documentation


### v0.11.41 - 3rd April 2026

- `docs/knowledge_graph/relationships.md`:
  - Added index composition pattern: `ASSET/equity →
    component_of → ASSET/index` with temporal bounds
  - Added delisting pattern: `ORGANIZATION/company →
    delisted_from → ORGANIZATION/exchange`
  - Added `component_of`, `delisted_from` to
    `market_structure` RELATION_KIND
  - Added `runs_on` to `product` RELATION_KIND
- Added `KnowledgeStore.find_by_name_prefix()` — case-
  insensitive prefix search with `canonical_name` index
- Added `KnowledgeStore.count_entities_by_type()` — single
  `GROUP BY` query for dashboard stats
- Updated `design.md` and `schema.md` with new query
  methods and index


### v0.11.40 - 3rd April 2026

- Performance pass (v0.11.39 review):
  - Combined data quality checks in `db_health.py` into
    a single `SUM(CASE)` query — 6 full-table scans → 1
  - Eliminated redundant `get_entity()` call in
    `merge_entities()` — constructs merged entity
    in-memory with `dataclasses.replace` instead of
    re-fetching from DB
  - Cached `results.get()` lookup in `Scraper._enrich()`
    — removed duplicate dict access per article


### v0.11.39 - 3rd April 2026

- Refactoring pass (v0.11.37 review):
  - Extracted `SQLiteStore` base class in `storage_base.py`
    — both `ArticleStore` and `KnowledgeStore` now inherit
    shared init/lifecycle logic (mkdir, connect, DDL,
    migrate, indexes, commit, close, context manager)
  - Extracted `_data_quality_count()` helper and
    `_QUALITY_CHECKS` table in `db_health.py` — five
    near-identical COUNT queries replaced with a loop
  - Replaced `source` property boilerplate in scrapers
    with class variable + `__init_subclass__` validation


### v0.11.38 - 3rd April 2026

- `.claude/`:
  - Migrated `/db-health` from command to skill (v1.0.0)
    for version tracking.


### v0.11.37 - 3rd April 2026

- Removed duplicate `spun_off` pattern from Corporate
  structure section in `relationships.md` — kept in
  Corporate actions, added cross-reference
- Added doc note for `measures` in `classification`
  RELATION_KIND explaining the semantic stretch


### v0.11.36 - 3rd April 2026

- Fixed `triggers` alias overlap — removed `triggered` from
  `causality` RELATION_KIND; `triggers` now only in
  `event_trigger`
- Added `KnowledgeStore.find_active_relationships()` — returns
  relationships where `valid_until` is unbounded or in the
  future, for current-state queries
- Updated `docs/knowledge_graph/design.md` with
  `find_active_relationships` documentation


### v0.11.35 - 3rd April 2026

- `.claude/`:
  - Migrated `/self-refinement` from command to skill
    (v1.0.0) for version tracking.


### v0.11.34 - 3rd April 2026

- Added PRODUCT relationship patterns to `relationships.md`:
  - `manufactured_by`, `approved`, `grounded`,
    `competes_with`, `runs_on`
  - New `product` RELATION_KIND with aliases
- Added IPO/listing event pattern:
  - `ORGANIZATION/company → ipo_on → ORGANIZATION/exchange`
  - Added `ipo_on` alias to `market_structure` RELATION_KIND
- Added KG design review backlog items (v0.11.33)


### v0.11.33 - 3rd April 2026

- Added scope warning to ownership/investment patterns in
  `relationships.md` — clarifies that stake sizes and
  percentages belong in external tables, not the KG


### v0.11.32 - 3rd April 2026

- `.claude/`:
  - Migrated `/improvements` from command to skill (v1.0.0)
    for version tracking.


### v0.11.31 - 3rd April 2026

- Fixed sentinel inconsistency in `_log_relationship()` —
  `valid_from` now uses `""` sentinel in
  `relationship_history` matching `relationships` table
- Fixed RELATION_KIND semantic groupings in
  `docs/knowledge_graph/relationships.md`:
  - Moved `belongs_to` from `membership` to
    `classification` (sector grouping ≠ membership)
  - Moved `spun_off`, `merged_with`, `founded` from
    `causality`/`governance` to `corporate_structure`
  - `causality` now only contains macro-signal patterns
    (`affects`, `triggered`)
  - `governance` now only contains active leadership
    (`leads`, `governs`)
- Updated `docs/knowledge_graph/schema.md` with `""`
  sentinel documentation on `valid_from` column


### v0.11.30 - 3rd April 2026

- `.claude/`:
  - Migrated `/optimize` from command to skill (v1.0.0)
    for version tracking.


### v0.11.29 - 3rd April 2026

- Fixed NULL `valid_from` in relationship PK — SQLite
  `NULL != NULL` allowed silent duplicate unbounded
  relationships. Now stores `""` sentinel instead of
  NULL; migration backfills existing rows
- Added `KnowledgeStore.get_relationships_between()` —
  fetches all relationships between two specific entities
  without Python-side filtering
- Added relationship pattern sections in
  `docs/knowledge_graph/relationships.md`:
  - Analyst coverage: `covers` pattern for
    PERSON/analyst → ASSET/equity
  - Sector events: `triggers`, `affects`, `hosts`
    patterns for TOPIC/sector_event
- Added `analyst_coverage` and `event_trigger`
  RELATION_KIND entries
- Updated `docs/knowledge_graph/design.md` with
  valid_from sentinel rationale


### v0.11.28 - 3rd April 2026

- `.claude/`:
  - Migrated `/refactor` from command to skill (v1.0.0)
    for version tracking.


### v0.11.27 - 3rd April 2026

- Added 6 RELATION_KIND entries in
  `docs/knowledge_graph/relationships.md`:
  governance, market_structure, policy, classification,
  causality, partnership — covers 11 previously unmapped
  relation_types across documented patterns
- Added PLACE/city subtype in
  `docs/knowledge_graph/subtypes.md` — financial hubs
  (Tokyo, Frankfurt, Hong Kong, Singapore) distinct from
  markets and regions
- Updated `docs/knowledge_graph/design.md` query section
  with `find_relationships_by_type` and
  `find_entities_by_status` (added in v0.11.23–v0.11.25)


