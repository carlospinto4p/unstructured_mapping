## Backlog

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
