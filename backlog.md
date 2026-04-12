## Backlog

### 2026.04.12 (v0.31.1 refactor review)

- [ ] **HIGH / Small** — Consolidate test fixture factories. `make_entity`/`make_chunk` are redefined in `tests/unit/test_detection.py:24-60`, `tests/unit/test_extraction.py:33-70` (as `_make_entity`, `_make_chunk`), and `tests/unit/test_pipeline.py:61-71` alongside the canonical versions in `tests/unit/conftest.py`. Move all to conftest and update callers — shrinks three files and prevents drift.
- [ ] **MEDIUM / Medium** — Define a `KnowledgeStoreProtocol` (or internal Protocol) in `knowledge_graph/_helpers.py` so mixins can type their host-class dependencies. Eliminates ~8 `# type: ignore[attr-defined]` in `_entity_mixin.py:371,372,394,402,518` and `_provenance_mixin.py:212`.
- [ ] **MEDIUM / Medium** — Collapse `EntitySearchMixin` query builders (`_entity_mixin.py:175-305`): `find_entities_by_type`, `find_entities_by_subtype`, `find_entities_by_status`, `find_by_name_prefix`, `find_entities_since`, and `count_entities_by_type` all follow the same `ENTITY_SELECT + WHERE + LIMIT` pattern. Extract a single private helper that takes a WHERE clause + params + optional limit.
- [ ] **LOW / Small** — Extract shared optional-import helper for LLM providers. `llm_claude.py:23-27` and `llm_ollama.py:27-31` duplicate the `try: import ... except ImportError: _pkg = None  # type: ignore[assignment]` pattern, and their constructors repeat the same ImportError message shape. A small `_optional_import(name, extras_name)` helper in `pipeline/_llm_retry.py` or a sibling module centralises it.
- [ ] **LOW / Small** — Tighten scraper subclass `__init__` duplication. `web_scraping/bbc.py:108-120` and `web_scraping/ap.py:54-67` have near-identical pass-through constructors whose only real job is overriding the default `feed_urls`. Use a class attribute (`default_feed_urls`) on `Scraper` or `__init_subclass__` so subclasses only declare what actually differs.
- [ ] **LOW / Small** — Drop stale in-code backlog reference. `pipeline/resolution.py:220-222` says "handled by a separate retry wrapper (backlog item 2e)" — the wrapper (`_llm_retry.py`) has shipped; replace the backlog pointer with a direct reference to `retry_llm_call`.
- [ ] **LOW / Small** — Remove stray `src/unstructured_mapping/pipeline/prompts.py.tmp.45896.1775925597518` (gitignored but clutters the working tree) and add the `*.tmp.*` pattern to `.gitignore` if not already there.

### 2026 March 30th

#### KG population (bootstrap + growth)

- [x] **HIGH** — Curated seed file: JSON file with ~50-100 key financial entities (central banks, top companies, indices, policymakers, core metrics) with aliases — version-controlled for reproducible KG bootstrap
- [x] **HIGH** — Seed loader script: reads the curated seed file, persists entities to the KG with `reason="seed"`, reports counts by type
- [x] **MEDIUM** — Cold-start LLM mode: pipeline mode that sends raw article text directly to the LLM for full entity extraction (bypasses detection), useful for initial population from an empty KG
- [ ] **LOW** — Wikidata seed pipeline: query Wikidata SPARQL for financial entities, map to KG schema, bulk-import — heavy but provides broad coverage and external IDs when needed

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
