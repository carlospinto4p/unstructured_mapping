## Backlog

### 2026 March 30th

#### Pipeline foundation (detection → resolution → extraction)

- [x] **HIGH** — LLM pass 1 (2d): `LLMEntityResolver` happy path — concrete `EntityResolver` in `pipeline/resolution.py` composing 2a + 2b + 2c: alias pre-scan → budget → build prompt → `LLMProvider.generate` → validate → emit `ResolvedMention`s + `ProposedEntity`s. Tests use a fake `LLMProvider`. No retry yet.
- [ ] **HIGH** — LLM pass 1 (2e): retry with error feedback — `LLMEntityResolver` appends the validation error to the user prompt and retries once per `llm_interface.md` § "Retry and error feedback". After two failures, raise `LLMProviderError` so orchestrator skips the chunk.
- [ ] **HIGH** — LLM pass 1 (2f): orchestrator integration + `ProposedEntity` persistence — wire `LLMEntityResolver` into `Pipeline` as a cascade after `AliasResolver`, and route `ProposedEntity`s through `KnowledgeStore` entity creation with provenance linked to the run.
- [ ] **MEDIUM** — `ClaudeProvider` (`anthropic` SDK) — second concrete `LLMProvider` implementation; enables quality/cost benchmarking against the Ollama baseline
- [ ] **MEDIUM** — Relationship extraction module: `RelationshipExtractor` ABC + `LLMExtractor` — extract relationships between resolved entities from article text
- [ ] **MEDIUM** — KG validation: temporal consistency (valid_until >= valid_from), alias collision detection across entities, entity-type relationship constraints

#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Refactoring (2026 April 10th review)

- [x] **MEDIUM** — Decompose `_find_num_ctx()` in `llm_ollama.py` — high cyclomatic complexity; extract `_ctx_from_model_info()` and `_ctx_from_parameters()` sub-functions
- [x] **MEDIUM, Large effort** — Split `EntityMixin` (616 lines) into focused mixins: CRUD, search/filter, merge, and audit/history
- [x] **LOW** — Standardize test helper naming — inconsistent `_make_entity` vs `_entity` vs `_org`; adopt `make_*` convention and move shared helpers to `conftest.py`

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
