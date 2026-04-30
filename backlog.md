## Backlog

### 2026 April 30th (optimization review)

- [x] **HIGH** — Batch relationship existence checks in `save_relationships` (`_relationship_mixin.py:128–145`): currently runs one `SELECT 1 FROM relationships WHERE ...` per candidate before bulk insert — N queries for N relationships; fix by fetching all existing composite keys in a single query and filtering in Python
- [x] **HIGH** — Batch relationship history inserts in `save_relationships` (`_relationship_mixin.py:175–176`): `_log_relationship` issues one `INSERT INTO relationship_history` per new row; replace with a single `executemany` call for the whole batch
- [x] **MEDIUM** — Eliminate quadratic context rebuilding in `fit_candidates` (`budget.py:227–233`): each loop iteration calls `build_kg_context_block([*fitted, entity])` which rebuilds the entire block from scratch — O(N²) string work; fix by tracking a running token count and the incremental cost of each new entity
- [x] **MEDIUM** — Cache lowercased chunk text in `_count_alias_matches` (`budget.py:158`): called once per candidate inside `sorted()`'s key function, but lowercases the chunk text from scratch each call; move `chunk_text.lower()` outside the sort and pass it as a pre-lowercased argument
- [x] **LOW** — Deduplicate entity IDs before `load_aliases_batch` in `find_mentions_with_entities` (`_provenance_mixin.py:264`): `eids` can contain duplicate entity IDs (one per provenance row), inflating the batch query unnecessarily; fix with `list(dict.fromkeys(r["entity_id"] for r in rows))`

### 2026 April 30th (refactor review)

- [x] **HIGH** — Move `_fetch_mapped` and `_write_snapshot` from `cli/wikidata_seed.py` to `wikidata/` — `api/kg.py` imports these private CLI functions with `# noqa: PLC2701` suppression, violating layer boundaries (API → CLI coupling); promote them to the `wikidata` module where they logically belong
- [x] **MEDIUM** — Extract token-usage accumulation helper in `pipeline/_article_processor.py` — the `getattr(stage, "last_token_usage", None)` + `metrics.input/output_tokens +=` pattern is duplicated 3× (lines 482–489, 513–520, 597–604); a private `_accumulate_usage(stage, metrics)` function removes all three copies
- [x] **MEDIUM** — Add `provider` property to LLM-using pipeline stages (`LLMEntityResolver`, `LLMRelationshipExtractor`, `ColdStartEntityDiscoverer`) — `ArticleProcessor.provider_name` / `model_name` reach into `stage._provider` (private attribute) via `getattr`; a public `.provider` property makes the contract explicit and eliminates fragile private-attr reflection
- [x] **LOW** — Remove redundant outer `transaction()` in `ArticleProcessor.process_article` (line 315) — `_persist_aggregated` already wraps its writes in `with self._store.transaction()`; the outer wrapper is a no-op (reentrant depth counter), but its presence implies ownership it does not have and conflicts with the method's own docstring
- [x] **LOW** — Fix `supports_json_mode` ABC vs class-attribute inconsistency in `pipeline/llm/provider.py` — `LLMProvider` declares it `@property @abstractmethod` but `ClaudeProvider` / `OllamaProvider` satisfy it via class-level constants; either change the ABC to a concrete `@property` returning `False` (override-friendly) or document the class-attr pattern explicitly

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
