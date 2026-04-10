## Backlog

### 2026 March 30th

#### Pipeline foundation (detection → resolution → extraction)

- [x] **HIGH** — `LLMProvider` ABC + `OllamaProvider` — pluggable LLM backend (ABC contract from `docs/pipeline/llm_interface.md`), Ollama-first per design.md, `llm` optional extras dependency group. Prerequisite for the LLM resolver and relationship extractor.
- [x] **HIGH** — LLM pass 1 (2a): prompt builder — `pipeline/prompts.py` with system prompt for pass 1, `build_kg_context_block(candidates)` producing the numbered text format from `llm_interface.md` § "KG context block format", and `build_pass1_user_prompt(kg_block, chunk_text, prev_entities)`. Pure string construction, no LLM call.
- [ ] **HIGH** — LLM pass 1 (2b): token budget + KG context truncation — `pipeline/budget.py` with char-based token estimator, budget region calculator reading `LLMProvider.context_window`, and candidate truncation ranked by alias match count per `llm_interface.md` § "Token budget".
- [ ] **HIGH** — LLM pass 1 (2c): response parser + validator — `pipeline/llm_parsers.py` applying the 5 validation rules from `llm_interface.md` (array shape, exactly-one-of `entity_id`/`new_entity`, valid `EntityType`, candidate-ID membership check). Adds `ProposedEntity` data class to `pipeline/models.py`.
- [ ] **HIGH** — LLM pass 1 (2d): `LLMEntityResolver` happy path — concrete `EntityResolver` in `pipeline/resolution.py` composing 2a + 2b + 2c: alias pre-scan → budget → build prompt → `LLMProvider.generate` → validate → emit `ResolvedMention`s + `ProposedEntity`s. Tests use a fake `LLMProvider`. No retry yet.
- [ ] **HIGH** — LLM pass 1 (2e): retry with error feedback — `LLMEntityResolver` appends the validation error to the user prompt and retries once per `llm_interface.md` § "Retry and error feedback". After two failures, raise `LLMProviderError` so orchestrator skips the chunk.
- [ ] **HIGH** — LLM pass 1 (2f): orchestrator integration + `ProposedEntity` persistence — wire `LLMEntityResolver` into `Pipeline` as a cascade after `AliasResolver`, and route `ProposedEntity`s through `KnowledgeStore` entity creation with provenance linked to the run.
- [ ] **MEDIUM** — `ClaudeProvider` (`anthropic` SDK) — second concrete `LLMProvider` implementation; enables quality/cost benchmarking against the Ollama baseline
- [ ] **MEDIUM** — Relationship extraction module: `RelationshipExtractor` ABC + `LLMExtractor` — extract relationships between resolved entities from article text
- [ ] **MEDIUM** — KG validation: temporal consistency (valid_until >= valid_from), alias collision detection across entities, entity-type relationship constraints

#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
