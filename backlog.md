## Backlog

### 2026.04.23 (optimization review v0.49.14)

- [x] **HIGH / Small** — N+1 entity lookups in `pipeline/extraction.py::_build_lookup_maps` (line 220): the loop calls `self._entity_lookup(rm.entity_id)` once per resolved mention, and every real caller wires `entity_lookup=store.get_entity`. For a 20-entity chunk this fires 20 separate SQLite queries right before the LLM call. Add an optional `entity_batch_lookup` parameter to `LLMRelationshipExtractor.__init__` (mirroring `LLMEntityResolver`), wire `store.get_entities` in the three instantiation sites (`orchestrator.py:292`, `cli/preview.py:210`, docstring at `extraction.py:118`), and do one IN-list query per chunk.
- [ ] **MEDIUM / Small** — `pipeline/orchestrator.py::_persist_aggregated` (line 782) fires up to 2N+2 SQLite COMMITs per article (one `save_entity` + one `save_provenances([1])` per proposal inside `_persist_proposals`, then `save_relationships`). Wrap the body in `with self._store.transaction():` so one article commits once. Same treatment for `_process_cold_start` (line 850) where every proposal gets its own commit pair.
- [ ] **MEDIUM / Small** — `pipeline/orchestrator.py::_persist_proposals` (line 893) calls `save_provenances([single_row])` inside the proposal loop. Accumulate provenances into one list and do a single `save_provenances(all_provs)` after the loop — fewer executemany round-trips and plays better with the transaction wrap above.
- [ ] **MEDIUM / Small** — `pipeline/resolution.py::_resolve_batch` (lines 427–431) falls back to per-entity `entity_lookup` in a dict comprehension when `entity_batch_lookup is None`. The orchestrator always wires the batch lookup, but tests and future callers silently get N queries per chunk. Drop the fallback and require `entity_batch_lookup` at construction time, or wrap the singleton path in a one-call batch helper.
- [ ] **LOW / Small** — `knowledge_graph/_entity_helpers.py::_load_aliases_batch` (line 179) uses `WHERE entity_id IN (?, ?, …)` with one placeholder per id. SQLite's default `SQLITE_MAX_VARIABLE_NUMBER` is 999 — large batches (e.g. `find_entities_by_status(limit=100_000)` on a populated KG) will raise `OperationalError: too many SQL variables`. Chunk the id list into ~500-id sub-queries and union the results before returning.
- [ ] **LOW / Small** — `wikidata/mapper.py::dedupe_mapped_by_qid` (line 112) rebuilds `seen = set(existing)` on every duplicate QID row. For a single QID that appears in 289 SPARQL bindings (STOXX Europe 600 per the docstring), the set is reconstructed 288 times. Track a parallel `dict[qid, set[str]]` alongside `merged_aliases` so the `seen` set is built once per QID and amended incrementally.


### 2026.04.23 (refactor review v0.49.6)

- [x] **LOW / Large** — Split `knowledge_graph/_entity_mixin.py` (639 lines) along its four internal mixin classes (`EntityCRUDMixin`, `EntitySearchMixin`, `EntityMergeMixin`, `EntityHistoryMixin`) into one file per mixin. The module docstring already documents them as four distinct concerns; the file size has crossed the point where navigating them in one file is friction.


### 2026.04.14 (Wikidata import follow-ups)

- [x] **LOW / Small** — Residual exchange noise after v0.37.1: Deutsche Bank ATS/Off Exchange/Super X, FXCM, Convergex, KCG Americas still slip through. Verify Wikidata QIDs for foreign-exchange broker, alternative trading system, and market maker, then extend the `MINUS` list in `EXCHANGES_QUERY`. Alternatively, maintain a small curated blocklist of QIDs if class-based exclusion keeps missing.
- [x] **LOW / Small** — Expand curated seed coverage for thin categories surfaced by the overlap review: regulators (SEC, CFTC, ECB-as-regulator, CSRC, BaFin, MAS), top-15 currencies beyond EUR/CHF/GBP, top-15 indices beyond Dow/FTSE 100/Hang Seng/Nasdaq. Curated entries get hand-tuned LLM descriptions, so they beat Wikidata's generic text for resolution quality.

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
