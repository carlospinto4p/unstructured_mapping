## Changelog

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


### v0.11.26 - 3rd April 2026

- `.claude/`:
  - Updated hooks to v2: read stdin JSON instead of
    broken `$CLAUDE_TOOL_INPUT`/`$CLAUDE_FILE` env vars.
  - Added script files in `.claude/hooks/`.


### v0.11.25 - 3rd April 2026

- Added relationship pattern sections in
  `docs/knowledge_graph/relationships.md`:
  - Corporate structure: `subsidiary_of`, `parent_of`
  - Location: `headquartered_in`, `located_in`
  - Membership: `member_of` for blocs and cartels
- Added three RELATION_KIND entries:
  `corporate_structure`, `location`, `membership`
- Added `KnowledgeStore.find_entities_by_status()` —
  filters entities by `EntityStatus` (ACTIVE, MERGED,
  DEPRECATED)


### v0.11.24 - 3rd April 2026

- Added `knowledge_graph/exceptions.py` with domain-specific
  exceptions:
  - `KnowledgeGraphError` — base exception
  - `EntityNotFound` — replaces `ValueError` in
    `merge_entities()`
  - `RevisionNotFound` — replaces `ValueError` in
    `revert_entity()`
  - `ResolutionAmbiguous` — for future pipeline use
  - `ValidationError` — for future KG validation
- Removed example scripts backlog item


### v0.11.23 - 3rd April 2026

- Added `KnowledgeStore.find_relationships_by_type()` —
  filters relationships by raw `relation_type` string
  before RELATION_KIND normalization
- Added `relation_type` index on `relationships` table
- Fixed "other six" → "other eight" in
  `docs/knowledge_graph/design.md` ROLE/RELATION_KIND
  section
- Updated `docs/knowledge_graph/schema.md` with new index


### v0.11.22 - 3rd April 2026

- Added `rating` RELATION_KIND to
  `docs/knowledge_graph/relationships.md` — aliases: rated,
  upgraded, downgraded, affirmed; covers credit rating
  actions by S&P, Moody's, Fitch
- Added credit ratings relationship patterns section with
  five canonical patterns (agency → entity)
- Added `rating_agency` ORGANIZATION subtype in
  `docs/knowledge_graph/subtypes.md`


### v0.11.21 - 2nd April 2026

- Eliminated duplicate COUNT query in
  `db_health._run_report()` — `_section_overall()` now
  returns `(lines, total)` tuple, orchestrator reuses it
- `BBCScraper._parse_article()` now uses `lxml` parser
  when available (3-5x faster), falls back to
  `html.parser`. Added `lxml` to `scraping` optional deps


### v0.11.20 - 2nd April 2026

- Batch alias fetches in bulk entity queries — all four
  list methods (`find_by_name`, `find_by_alias`,
  `find_entities_by_type`, `find_entities_by_subtype`)
  now use `_rows_to_entities()` with a single IN query
  via `_load_aliases_batch()` instead of per-row fetches
- Added `KnowledgeStore.save_provenances()` — bulk insert
  via `executemany()`, returns count of newly inserted
  records


### v0.11.19 - 2nd April 2026

- Fixed N+1 query in `find_co_mentioned()` — entities
  and counts now fetched in a single JOIN query;
  aliases batch-loaded via new `_load_aliases_batch()`
  helper. Reduces N+1 queries to 2 (one join + one
  alias batch).
- Fixed unreliable duplicate detection in
  `save_relationship()` — uses `total_changes` delta
  instead of cumulative counter to detect whether
  the INSERT succeeded


### v0.11.18 - 2nd April 2026

- Refactored `KnowledgeStore` in `storage.py`:
  - Extracted `_sync_aliases()` from `save_entity()`
  - Extracted `_redirect_entity_references()` from
    `merge_entities()` — five repetitive UPDATE
    statements replaced with a loop
  - Renamed `_row_to_rel_rev` → `_row_to_relationship_rev`
    for consistency with other `_row_to_*` helpers


### v0.11.17 - 2nd April 2026

- Refactored `db_health._run_report()` — split 142-line
  monolith into 7 per-section helpers (`_section_overall`,
  `_section_by_source`, `_section_last_scrape`,
  `_section_recent_batches`, `_section_daily_coverage`,
  `_section_data_quality`, `_section_db_size`)
- Refactored `ArticleStore._migrate()` — split 102-line
  method into 4 per-step helpers
  (`_migrate_add_document_id`,
  `_migrate_enforce_constraints`,
  `_migrate_normalize_uuids`,
  `_migrate_drop_stale_indexes`)


### v0.11.16 - 2nd April 2026

- Refactored `KnowledgeStore` in `storage.py`:
  - Extracted `_ENTITY_SELECT` and `_ENTITY_SELECT_ALIASED`
    constants — eliminated 4 duplicated 11-column SELECT
    lists
  - Unified `find_co_mentioned()` — replaced two
    near-identical SQL branches with conditional query
    builder


### v0.11.15 - 2nd April 2026

- Fixed scope drift in `docs/knowledge_graph/design.md`:
  METRIC example no longer implies KG stores actual values
- Fixed scope drift in `docs/knowledge_graph/subtypes.md`:
  company sub-classification plan now uses relationships
  only, removing suggestion to add structured attributes
  to Entity


### v0.11.14 - 2nd April 2026

- Added `/review-kg-scope` skill — audits KG for scope
  violations: flags quantitative data, operational metadata,
  or analysis concerns that should live in external tables


### v0.11.13 - 2nd April 2026

- Documented relationship attributes boundary in
  `docs/knowledge_graph/design.md`: quantitative values
  (ownership %, ratings, price targets) are out of KG
  scope — external tables joined via `entity_id`


### v0.11.12 - 2nd April 2026

- Added `KnowledgeStore.find_recent_mentions()` — fetches
  provenance records after a given datetime, ordered most
  recent first
- Added composite index `(entity_id, detected_at)` on
  provenance table for fast temporal queries
- Updated `docs/knowledge_graph/design.md` and
  `docs/knowledge_graph/schema.md`


### v0.11.11 - 2nd April 2026

- `.claude/settings.json`:
  - Added PreToolUse hook to block compound git commands.


### v0.11.10 - 2nd April 2026

- Split ORGANIZATION/fund into `fund_manager` (BlackRock,
  Vanguard) and `fund` (non-ETF vehicles like PIMCO Total
  Return, CalPERS). ETF vehicles remain ASSET/etf.
- Updated `docs/knowledge_graph/relationships.md` with
  fund_manager patterns and ETF managed_by relationship


### v0.11.9 - 2nd April 2026

- Added "Dual-nature entities" section in
  `docs/knowledge_graph/subtypes.md` — guidance for when
  to create separate entities for the same real-world thing
  (e.g. VIX Index as METRIC vs VIX Futures as ASSET),
  with split-vs-keep decision criteria and five canonical
  examples with relationship patterns


### v0.11.8 - 2nd April 2026

- `CLAUDE.md`:
  - Added Shell Commands, Project Configuration, Versioning / Release,
    and Testing sections.


### v0.11.7 - 2nd April 2026

- Added ASSET/etf subtype — exchange-traded funds, distinct
  from equity (not individual stocks) and index (tradeable)
- Added METRIC/earnings subtype — company-level financial
  metrics (EPS, revenue, guidance, margins)


### v0.11.6 - 2nd April 2026

- Added `KnowledgeStore.find_co_mentioned()` — finds
  entities mentioned in the same articles as a given
  entity, returns `(Entity, count)` tuples sorted by
  co-occurrence count descending. Supports optional
  `since` parameter for time-windowed queries.
- Added composite index `(document_id, entity_id)` on
  provenance table for fast co-mention joins
- Updated `docs/knowledge_graph/design.md` and
  `docs/knowledge_graph/schema.md` with co-mention
  query rationale and index


### v0.11.5 - 2nd April 2026

- Updated `/review-kg` skill (v1.1.0):
  - Added `relationships.md` to required inputs
  - Added relationship pattern coverage and RELATION_KIND
    completeness checks
  - Expanded consistency checks across all four KG docs


### v0.11.4 - 2nd April 2026

- Added `docs/knowledge_graph/relationships.md` — canonical
  cross-type relationship patterns for financial analysis:
  - Market structure (issued_by, listed_on, tracks)
  - People and roles (works_at with ROLE qualifier)
  - Regulation and policy (regulates, enforces, sets)
  - Economic indicators (issued_by, measures)
  - Corporate actions (acquired, appointed_at, departed_from)
  - Competitive and supply chain (competes_with, supplies)
  - Sector linkage (classified_as, affects)
  - Recommended RELATION_KIND entities for normalization


### v0.11.3 - 2nd April 2026

- Documented METRIC metadata boundaries in
  `docs/knowledge_graph/subtypes.md`: issuing body as
  relationship, release schedule and expected-vs-actual
  out of KG scope


### v0.11.2 - 2nd April 2026

- Documented ASSET ticker/identifier decision in
  `docs/knowledge_graph/subtypes.md`: aliases suffice for
  text detection; `external_ids` table is the planned
  approach for structured joins with price feeds


### v0.11.1 - 2nd April 2026

- Added TOPIC subtypes in `docs/knowledge_graph/subtypes.md`:
  `sector`, `macro_theme`, `geopolitical`, `sector_event`
- Added disambiguation guidance for TOPIC vs METRIC overlap


### v0.11.0 - 2nd April 2026

- Added audit log for KG time-travel and revert:
  - `entity_history` table — append-only snapshots of
    every entity create, update, merge, and revert
  - `relationship_history` table — snapshots of every
    relationship creation
  - `EntityRevision` and `RelationshipRevision` models
  - `KnowledgeStore.get_entity_history()` — full revision
    list for an entity
  - `KnowledgeStore.get_entity_at()` — entity state at a
    point in time
  - `KnowledgeStore.revert_entity()` — restore a prior
    revision
  - `KnowledgeStore.get_relationship_history()` — revision
    list for relationships involving an entity
  - Optional `reason` parameter on `save_entity()` and
    `save_relationship()` for audit context
- Updated `docs/knowledge_graph/design.md` and
  `docs/knowledge_graph/schema.md` with audit log
  rationale and table schemas


### v0.10.4 - 2nd April 2026

- Added `updated_at` field to `Entity` — tracks when a
  record was last modified for cache invalidation and
  freshness monitoring
- Added `updated_at` column to `entities` table with
  migration for existing databases
- Updated `docs/knowledge_graph/design.md` and
  `docs/knowledge_graph/schema.md`


### v0.10.3 - 2nd April 2026

- Fixed stale docstring references:
  - `storage.py` module docstring: `DESIGN.md` ->
    `docs/knowledge_graph/`
  - `Entity` class docstring: listed only 4 of 10 types
  - `EntityType` docstring: "PERSON through LEGISLATION"
    -> "PERSON through METRIC"
- Added 9 backlog items from `/review-kg` design review


### v0.10.2 - 2nd April 2026

- Added `/review-kg` skill — reviews KG architecture and
  design for gaps, inconsistencies, and improvements from
  the perspective of quant researchers and market analysts


### v0.10.1 - 2nd April 2026

- Split `docs/knowledge_graph.md` into `docs/knowledge_graph/`:
  - `design.md` — approach, entity types, fields, relationships
  - `subtypes.md` — canonical subtype conventions per entity
    type with examples and deferred sub-classification plan
  - `schema.md` — SQLite table schemas
- Updated references in source code, README, and rules
- Updated README entity type list to include all ten types


### v0.10.0 - 2nd April 2026

- Added `ASSET` and `METRIC` to `EntityType`:
  - `ASSET` — tradeable financial instruments and stores
    of value (equities, bonds, commodities, currencies,
    crypto, indices)
  - `METRIC` — quantitative market indicators (CPI,
    unemployment rate, GDP growth, VIX)
- Added `subtype` field to `Entity` — optional finer
  classification within entity types (e.g. `"company"`
  for ORGANIZATION, `"equity"` for ASSET):
  - `subtype` column on `entities` table with migration
    for existing databases
  - Compound index `(entity_type, subtype)` for filtered
    queries
  - `KnowledgeStore.find_entities_by_subtype()` query
    method
- Updated `docs/knowledge_graph.md` with ASSET, METRIC,
  and subtype rationale


### v0.9.0 - 2nd April 2026

- Added `PRODUCT` to `EntityType` — named products,
  services, platforms (distinct from manufacturer ORG)
- Added `LEGISLATION` to `EntityType` — laws, regulations,
  treaties, legal instruments with temporal bounds and
  jurisdiction relationships
- Updated `docs/knowledge_graph.md` with rationale for
  PRODUCT and LEGISLATION types


### v0.8.2 - 2nd April 2026

- Updated `docs/knowledge_graph.md`: clarify KG as an
  index into the news, not a database of facts


### v0.8.1 - 2nd April 2026

- Added `/backlog` skill in `.claude/skills/backlog/`.


### v0.8.0 - 2nd April 2026

- Added `ROLE` and `RELATION_KIND` to `EntityType` —
  meta-types that reuse the entity/alias system for
  structured querying and synonym resolution
- Added `qualifier_id` to `Relationship` — optional FK
  to a ROLE entity, solving n-ary relationships
  (person + role + company)
- Added `relation_kind_id` to `Relationship` — optional
  FK to a RELATION_KIND entity for normalized lookup
  across synonym surface forms
- Added `KnowledgeStore` methods:
  - `find_by_qualifier()`: query by relationship qualifier
  - `find_by_relation_kind()`: query by canonical kind
  - `find_entities_by_type()`: query entities by type
- Added migration for existing databases in
  `KnowledgeStore.__init__()`
- Updated `docs/knowledge_graph.md` with ROLE,
  RELATION_KIND, qualifier, and relation kind rationale


### v0.7.4 - 2nd April 2026

- Updated `docs/knowledge_graph.md`: clarify KG as a runtime
  knowledge supplement for facts beyond LLM training cutoff
- Updated `backlog.md`: mark KG data model task as done


### v0.7.3 - 2nd April 2026

- Added full table schemas to `docs/knowledge_graph.md` —
  every column with type, constraints, and purpose


### v0.7.2 - 2nd April 2026

- Moved design docs from `knowledge_graph/DESIGN.md` to
  `docs/knowledge_graph.md`
- Cleaned up design docs to document decisions and reasons
  only, removing references to planning alternatives that
  were never implemented
- Updated all docstring references to new docs path


### v0.7.1 - 2nd April 2026

- Changed `Article.document_id` type from `str` to
  `uuid.UUID` for type safety and standard formatting
- Updated `ArticleStore` to serialize/deserialize `UUID`
- Added migration step to normalize existing hex-format
  IDs (32 chars) to canonical UUID format (8-4-4-4-12)


### v0.7.0 - 2nd April 2026

- Added `knowledge_graph` module with LLM-first data model:
  - `EntityType` enum: PERSON, ORGANIZATION, PLACE, TOPIC
  - `EntityStatus` enum: ACTIVE, MERGED, DEPRECATED
  - `Entity`, `Provenance`, `Relationship` frozen dataclasses
  - `KnowledgeStore` — SQLite storage with CRUD, alias
    lookup, and entity merge
- Added `knowledge_graph/DESIGN.md` documenting all design
  decisions, enum rationale, and deferred features
- Added `.claude/rules/documentation.md` — design decisions
  must be documented for cold readers


### v0.6.1 - 2nd April 2026

- Fixed `_migrate()` — rebuilds table after backfill to
  enforce `NOT NULL UNIQUE` constraint on `document_id`
  (SQLite `ALTER TABLE ADD COLUMN` cannot add constraints)
- Drops stale `idx_source` index from pre-v0.5.8 databases
- Added `document_id` integrity checks to `db_health.py`
  (null count, duplicate count, migration status)


### v0.6.0 - 2nd April 2026

- Added `document_id` field to `Article` — stable UUID
  identifier auto-generated on creation
- Added `document_id` column to `articles` table with
  `UNIQUE` constraint and index
- Added `ArticleStore._migrate()` — backfills `document_id`
  for existing rows in legacy databases


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
