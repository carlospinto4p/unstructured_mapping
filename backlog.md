## Backlog

### 2026.04.12 (v0.31.1 refactor review)

- [ ] **MEDIUM / Medium** — Collapse `EntitySearchMixin` query builders (`_entity_mixin.py:175-305`): `find_entities_by_type`, `find_entities_by_subtype`, `find_entities_by_status`, `find_by_name_prefix`, `find_entities_since`, and `count_entities_by_type` all follow the same `ENTITY_SELECT + WHERE + LIMIT` pattern. Extract a single private helper that takes a WHERE clause + params + optional limit.
- [ ] **LOW / Small** — Extract shared optional-import helper for LLM providers. `llm_claude.py:23-27` and `llm_ollama.py:27-31` duplicate the `try: import ... except ImportError: _pkg = None  # type: ignore[assignment]` pattern, and their constructors repeat the same ImportError message shape. A small `_optional_import(name, extras_name)` helper in `pipeline/_llm_retry.py` or a sibling module centralises it.
- [ ] **LOW / Small** — Tighten scraper subclass `__init__` duplication. `web_scraping/bbc.py:108-120` and `web_scraping/ap.py:54-67` have near-identical pass-through constructors whose only real job is overriding the default `feed_urls`. Use a class attribute (`default_feed_urls`) on `Scraper` or `__init_subclass__` so subclasses only declare what actually differs.
- [ ] **LOW / Small** — Drop stale in-code backlog reference. `pipeline/resolution.py:220-222` says "handled by a separate retry wrapper (backlog item 2e)" — the wrapper (`_llm_retry.py`) has shipped; replace the backlog pointer with a direct reference to `retry_llm_call`.
- [ ] **LOW / Small** — Remove stray `src/unstructured_mapping/pipeline/prompts.py.tmp.45896.1775925597518` (gitignored but clutters the working tree) and add the `*.tmp.*` pattern to `.gitignore` if not already there.

### 2026 March 30th

#### KG population (bootstrap + growth)

- [ ] **LOW** — Wikidata seed pipeline: query Wikidata SPARQL for financial entities, map to KG schema, bulk-import — heavy but provides broad coverage and external IDs when needed

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
