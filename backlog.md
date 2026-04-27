## Backlog

### 2026.04.25 (refactor review v0.58.0)

- [ ] **HIGH / Large** — Split `pipeline/orchestrator.py` (1022 lines). Mixes the batch-level `Pipeline.run`/run-tracking concern with per-article processing (`_process_article`, `_process_chunk`, `_process_cold_start`, `_persist_aggregated`, `_persist_proposals`, `_persist_relationships`) and metrics (`_provider_name`, `_model_name`, `_MetricsAccumulator`). Pull the per-article path into `pipeline/_article_processor.py` and keep `Pipeline` as the batch / run-bookkeeping façade. Improves test surface area and lets the resume/retry path evolve without scrolling past unrelated methods.
- [ ] **HIGH / Small** — Flatten `knowledge_graph/_entity_helpers.py` from a "mixin" to a utility module. The file uses the mixin shape (class with `_conn` typed protocol) but is consumed by every other entity sub-mixin — `_entity_crud_mixin`, `_entity_history_mixin`, `_entity_merge_mixin`, `_entity_search_mixin` all inherit it just to call `_load_aliases` / `_sync_aliases`. Convert to module-level functions taking `conn` and remove the inheritance pyramid; the import chain `storage.py` → `_entity_mixin.py` → child mixins → `_entity_helpers.py` becomes one level shallower and the role of each file becomes obvious.
- [ ] **MEDIUM / Small** — Move duplicated CLI test fixtures into `tests/unit/conftest.py`. `test_cli_seed.py`, `test_cli_audit_aliases.py`, `test_cli_populate.py`, and `test_cli_ingest.py` each build small entity / store / scratch-DB fixtures inline. Pull the recurring pieces (e.g. populated KG factory, two-source articles DB) into shared fixtures so a new field on `Entity` only needs one update.
- [ ] **LOW / Small** — Extract import-summary formatter shared by seed loaders. `cli/_seed_helpers.py::log_import_summary` is invoked by `cli/seed.py` and `cli/populate.py`; `cli/wikidata_seed.py` re-implements similar text. Consolidate so all three loaders go through one formatter (covers stage name, created/skipped, top-N type counts).
- [ ] **LOW / Trivial** — Fix the one 81-char line in `cli/ingest.py:138` (log string literal). Ruff is permissive about string literals so this slipped past, but the project rule is 78 chars. Single-line wrap.


### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
