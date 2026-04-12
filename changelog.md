## Changelog

### v0.30.0 - 12th April 2026

- Added KG bootstrap seed:
  - `data/seed/financial_entities.json`: curated seed of
    ~90 core financial/market-moving entities (central
    banks, regulators, exchanges, top companies,
    policymakers, indices, currencies, commodities,
    macro metrics).
  - `cli/seed.py`: idempotent loader that reads the seed
    JSON, skips existing entities (case-insensitive match
    on canonical name + type), and tags new rows with
    `reason="seed"` in the entity history. Supports
    `--seed`, `--db`, and `--dry-run` flags.
- Added unit tests:
  - `tests/unit/test_cli_seed.py`: 14 tests covering
    parsing, idempotency, dry-run, history tagging, and
    curated file validity.


### v0.29.0 - 12th April 2026

- `pipeline/orchestrator.py`:
  - Wired `RelationshipExtractor` into the `Pipeline`:
    optional `extractor` parameter runs pass 2 after
    resolution, converts `ExtractedRelationship` to
    `Relationship`, and persists via
    `save_relationships()`.
  - Added `relationships_saved` field to `ArticleResult`
    and `PipelineResult`.
  - Updated `_compute_run_stats()`: now returns 4-tuple
    including relationship count.
  - Updated `finish_run()` calls: `relationship_count`
    is now populated in `IngestionRun`.
  - Updated run completion log: includes
    `"%d relationships"`.
  - Removed "intentionally out of scope" note from
    module docstring.
- `docs/pipeline/`:
  - Rewrote `10_orchestration.md`: documents all 4
    stages (detection, resolution, extraction,
    persistence), field mapping table, updated diagrams
    and interface docs.
- `tests/unit/`:
  - Added 5 tests to `test_pipeline.py`: extraction
    integration, no-extractor default, error isolation,
    run relationship_count, extractor receives resolved
    entities.


### v0.28.3 - 12th April 2026

- `pipeline/orchestrator.py`:
  - Added `proposals_saved` field to `PipelineResult`:
    aggregates new entities created from LLM proposals
    across all articles.
  - Updated `_compute_run_stats()`: now returns
    `(doc_count, prov_count, proposal_count)` tuple.
  - Updated run completion log: now includes
    `"%d new entities"` alongside provenances.
- `knowledge_graph/`:
  - Updated `IngestionRun.entity_count` docstring:
    clarified it tracks provenance records (entity
    mention count), not distinct entities created.
  - Updated `finish_run()` docstring: same clarification.


### v0.28.2 - 12th April 2026

- `docs/pipeline/`:
  - Added `12_kg_population.md`: KG population strategy
    covering the bootstrap problem, two-phase approach
    (curated seed + organic LLM growth), seed
    implementation guide, cold-start LLM mode (future),
    Wikidata as alternative seed source, and operational
    considerations.


### v0.28.1 - 12th April 2026

- `pipeline/`:
  - Added `_llm_retry.py`: shared `retry_llm_call()`
    helper and `append_error()` function, extracted from
    duplicate implementations in `resolution.py` and
    `extraction.py`.
  - Refactored `resolution.py`: replaced inline retry
    loop and `_append_error` static method with shared
    `retry_llm_call()`.
  - Refactored `extraction.py`: replaced inline retry
    loop and `_append_error` function with shared
    `retry_llm_call()`.
  - Refactored `llm_parsers.py`: unified `_parse_json()`
    and `_parse_json_pass2()` into a single function
    parameterized by exception class.
  - Refactored `__init__.py`: sorted `__all__` and
    imports fully alphabetically.
- `tests/unit/`:
  - Added `FakeProvider` to `conftest.py`: shared fake
    LLM provider replacing 3 duplicate implementations.
  - Refactored `test_extraction.py`,
    `test_resolution.py`, `test_llm_provider.py`:
    replaced local `_FakeProvider` with shared
    `FakeProvider`.


### v0.28.0 - 11th April 2026

- `knowledge_graph/`:
  - Added `validation.py`:
    - `validate_temporal()`: enforced at save time,
      raises `ValidationError` if `valid_until <
      valid_from`.
    - `find_alias_collisions()`: advisory audit for
      aliases shared across entities.
    - `AliasCollision` dataclass for structured results.
    - `check_relationship_constraints()`: check a
      relationship against canonical patterns from
      `relationships.md`.
    - `audit_relationship_constraints()`: scan all KG
      relationships for constraint warnings.
    - `ConstraintWarning` dataclass for audit results.
    - `RELATIONSHIP_CONSTRAINTS` dict with 22 canonical
      entity-type pair patterns.
  - Updated `_entity_mixin.py`: `save_entity()` calls
    `validate_temporal()` before INSERT.
  - Updated `_relationship_mixin.py`:
    `save_relationship()` and `save_relationships()`
    call `validate_temporal()`.
  - Updated `__init__.py`: exports all new public names.
- `docs/knowledge_graph/`:
  - Added `validation.md`: design rationale for
    save-time vs advisory validation, temporal checks,
    alias collisions, relationship constraints.
- `tests/unit/`:
  - Added `test_kg_validation.py`: 22 tests covering
    temporal consistency (entity + relationship), alias
    collision detection, relationship constraint
    checking, and save-time integration.


### v0.27.1 - 11th April 2026

- `docs/pipeline/`:
  - Added `11_extraction.md`: extraction stage design
    doc covering architecture, extract flow, validation
    strategy (hard vs soft), name resolution, date
    parsing, and design decisions.
  - Updated `02_models.md`: `ExtractedRelationship`
    fields now match implementation (`_id` not `_ref`,
    `datetime` not strings), added `ExtractionResult`.
  - Updated `06_prompts.md`: added Pass 2 prompt
    documentation (`PASS2_SYSTEM_PROMPT`,
    `build_entity_list_block()`,
    `build_pass2_user_prompt()`).
  - Updated `08_llm_parsers.md`: added Pass 2 parser
    documentation (hard/soft validation split, entity
    reference resolution, date parsing, qualifier
    handling).


### v0.27.0 - 11th April 2026

- `pipeline/`:
  - Added `extraction.py`:
    - `RelationshipExtractor` ABC with `extract()` method.
    - `LLMRelationshipExtractor`: LLM-based pass 2
      implementation with retry logic, name-to-ID
      resolution, and proposal entity support.
  - Added `models.py`:
    - `ExtractedRelationship`: intermediate model for
      LLM-extracted relationships (before KG persistence).
    - `ExtractionResult`: extraction stage output.
  - Added `prompts.py`:
    - `PASS2_SYSTEM_PROMPT`: system prompt for
      relationship extraction.
    - `build_entity_list_block()`: formats "ENTITIES IN
      THIS TEXT" block for pass 2.
    - `build_pass2_user_prompt()`: assembles pass 2
      user prompt.
  - Added `llm_parsers.py`:
    - `Pass2ValidationError`: structural validation
      errors for retry.
    - `parse_pass2_response()`: validates pass 2 rules
      with soft drops for unresolvable refs, bad dates,
      and self-refs.
  - Updated `__init__.py`: exports all new public names.
- `tests/unit/`:
  - Added `test_extraction.py`: 18 tests covering ABC
    contract, happy path, name resolution, self-ref
    drops, retry logic, proposals, qualifier handling.
  - Updated `test_llm_parsers.py`: 25 tests for pass 2
    parsing, date handling, soft drops, structural
    errors, qualifier resolution.
  - Updated `test_prompts.py`: 11 tests for pass 2
    system prompt, entity list block, user prompt.


### v0.26.0 - 11th April 2026

- `pipeline/`:
  - Added `ClaudeProvider`: Anthropic Messages API
    provider for quality/cost benchmarking against the
    Ollama baseline.
  - Added `llm_claude.py`: guarded `anthropic` import,
    error translation
    (`APITimeoutError` -> `LLMTimeoutError`,
    `APIConnectionError` -> `LLMConnectionError`),
    configurable `max_tokens` and `context_window`.
  - Updated `llm_provider.py`: docstring lists
    `llm_claude` as a concrete provider.
  - Updated `__init__.py`: exports `ClaudeProvider`.
- `pyproject.toml`:
  - Added `anthropic>=0.42.0` to `llm` and `dev` extras.
- `tests/unit/`:
  - Added `test_llm_claude.py`: 12 tests covering happy
    path, error translation, metadata, json_mode guard,
    dependency guard, and edge cases.


### v0.25.1 - 11th April 2026

- `.claude/rules/`:
  - Decoupled `/refactor` rule: canonical
    `refactoring.md` is now procedural only.
  - Added `refactoring-areas.md` with
    project-specific code smells to watch.
- `.claude/skills/refactor/`:
  - Updated `SKILL.md` to read both canonical
    procedure and per-project areas.


### v0.25.0 - 11th April 2026

- Updated `pipeline/orchestrator.py`:
  - `Pipeline` accepts optional `llm_resolver` parameter for LLM cascade after the primary resolver
  - Unresolved mentions from the alias resolver are automatically passed to the LLM resolver
  - Added `_save_proposals()`: persists `EntityProposal`s as new `Entity` objects (status=ACTIVE) with provenance linked to the run
  - `ArticleResult` gains `proposals_saved` field tracking new entities created per article
- Added 5 unit tests for LLM cascade:
  - Ambiguous mentions resolved by LLM cascade
  - LLM proposals persisted as new entities in KG
  - Proposal provenance linked to ingestion run
  - No-LLM fallback leaves unresolved mentions
  - LLM resolver skipped when all mentions already resolved


### v0.24.2 - 11th April 2026

- `.claude/rules/`:
  - Decoupled `/optimize` rule: canonical
    `optimization.md` is now procedural only.
  - Added `optimization-areas.md` with
    project-specific performance areas.
- `.claude/skills/optimize/`:
  - Updated `SKILL.md` to read both canonical
    procedure and per-project areas.


### v0.24.1 - 11th April 2026

- Updated `pipeline/resolution.py`:
  - `LLMEntityResolver.resolve()`: added retry with error feedback per `03_llm_interface.md` § "Retry and error feedback"
  - On `Pass1ValidationError`, appends error message to user prompt and retries once (max 2 attempts)
  - After two failures, raises `LLMProviderError` so the orchestrator can skip the chunk
  - Added `_append_error()` static method for retry prompt formatting
  - Added `MAX_ATTEMPTS` class constant
- Added 3 unit tests for retry behavior:
  - Two failures raise `LLMProviderError` with 2 LLM calls
  - Retry succeeds on second attempt
  - Retry prompt contains error feedback text


### v0.24.0 - 10th April 2026

- Added `pipeline/resolution.py`:
  - `LLMEntityResolver`: LLM-based entity resolver composing prompt builder, token budget manager, and response parser into a single `resolve()` call
  - Accepts injectable `entity_lookup` callable to decouple from storage layer
  - Supports `prev_entities` for running entity header across multi-chunk documents
  - Exposes `proposals` property for new entity proposals from the LLM
- Added 12 unit tests for `LLMEntityResolver`:
  - Resolved entities, new entity proposals, mixed responses
  - Candidate deduplication, missing candidate handling
  - Validation error propagation, section name propagation
  - Previous entities in prompt, proposals reset between calls
- Exported `LLMEntityResolver` from `pipeline/__init__.py`


### v0.23.4 - 10th April 2026

- Refactored `pipeline/llm_ollama.py`:
  - Extracted `_ctx_from_model_info()` and `_ctx_from_parameters()` from `_find_num_ctx()` to reduce cyclomatic complexity
- Refactored `knowledge_graph/_entity_mixin.py`:
  - Split 616-line `EntityMixin` into four focused sub-mixins:
    - `EntityCRUDMixin`: save, get, find by name/alias
    - `EntitySearchMixin`: filtered queries and aggregate counts
    - `EntityMergeMixin`: merge with FK redirection
    - `EntityHistoryMixin`: revision history, point-in-time, revert
  - Extracted shared helpers into `_entity_helpers.py`
  - `EntityMixin` now composes all four via multiple inheritance
- Standardized test helper naming:
  - Adopted `make_*` convention across all test files
  - `conftest.py`: `_make_entity` → `make_entity`
  - File-local helpers: `_chunk` → `make_chunk`, `_mention` → `make_mention`, `_org` → `make_org`, etc.


### v0.23.3 - 10th April 2026

- `.claude/rules/`:
  - Decoupled `/improvements` rule: canonical
    `improvements.md` is now procedural only.
  - Added `improvement-areas.md` with
    project-specific areas to watch.
- `.claude/skills/improvements/`:
  - Updated `SKILL.md` to read both canonical
    procedure and per-project areas.


### v0.23.2 - 10th April 2026

- Refactored `pipeline/budget.py`:
  - Extracted `_count_occurrences()` helper to eliminate duplicated while-True substring-counting loops in `_count_alias_matches()`
- Refactored `pipeline/orchestrator.py`:
  - Extracted `_compute_run_stats()` helper to deduplicate result filtering in error and success paths
  - Added missing `# noqa: BLE001` on broad `except Exception` for consistency


### v0.23.1 - 10th April 2026

- Renamed `docs/pipeline/` files with numerical prefixes for reading order:
  - `design.md` → `01_design.md`
  - `models.md` → `02_models.md`
  - `llm_interface.md` → `03_llm_interface.md`
  - `detection.md` → `04_detection.md`
  - `resolution.md` → `05_resolution.md`
  - `prompts.md` → `06_prompts.md`
  - `budget.md` → `07_budget.md`
  - `llm_parsers.md` → `08_llm_parsers.md`
  - `chunking.md` → `09_chunking.md`
  - `orchestration.md` → `10_orchestration.md`
- Updated all cross-references in docs, source docstrings, and `README.md`.


### v0.23.0 - 10th April 2026

- Added `pipeline/llm_parsers.py`:
  - `Pass1ValidationError`: exception for schema validation failures, message suitable for retry prompts.
  - `parse_pass1_response()`: parse raw LLM JSON and validate against the 5 rules from `llm_interface.md`, returning `(ResolvedMention, ...), (EntityProposal, ...)`.
- Added `EntityProposal` dataclass to `pipeline/models.py`: intermediate representation for LLM-proposed new entities before persistence validation.
- Added `docs/pipeline/llm_parsers.md`: design decisions for parsing and validation.
- Added `tests/unit/test_llm_parsers.py`: 31 tests covering valid responses, all 5 validation rules, edge cases, and the `EntityProposal` model.


### v0.22.0 - 10th April 2026

- Added `pipeline/budget.py`:
  - `estimate_tokens()`: character-based token estimator (`ceil(chars / 4)`).
  - `PromptBudget`: frozen dataclass with budget breakdown (system, response headroom, flexible).
  - `compute_budget()`: compute flexible budget from context window, system prompt, and response headroom.
  - `fit_candidates()`: rank candidates by alias match count, truncate KG context to fit budget, truncate chunk text as last resort.
- Added `tests/unit/test_budget.py`: 27 tests covering token estimation, budget computation, alias ranking, candidate truncation, and paragraph-level text truncation.


### v0.21.1 - 10th April 2026

- Added `docs/pipeline/prompts.md`: design decisions for prompt construction (system prompt wording, KG context format, running entity header, deferred items).
- Updated `README.md`: added prompt construction usage example under LLM Providers.


### v0.21.0 - 10th April 2026

- Added `pipeline/prompts.py`:
  - `PASS1_SYSTEM_PROMPT`: system prompt for LLM entity resolution pass.
  - `build_kg_context_block()`: format candidate entities as numbered text blocks.
  - `build_pass1_user_prompt()`: assemble user prompt with KG context, running entity header, and chunk text.
- Added `tests/unit/test_prompts.py`: 20 tests covering system prompt, KG block, running entity header, and user prompt assembly.


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


