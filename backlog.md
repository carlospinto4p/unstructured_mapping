## Backlog

### 2026 March 30th

#### Pipeline foundation (detection → resolution → extraction)

- [ ] **HIGH** — `LLMProvider` ABC + `OllamaProvider` — pluggable LLM backend (ABC contract from `docs/pipeline/llm_interface.md`), Ollama-first per design.md, `llm` optional extras dependency group. Prerequisite for the LLM resolver and relationship extractor.
- [ ] **MEDIUM** — LLM-based entity resolver — reads entity descriptions + context snippets to disambiguate when alias lookup returns multiple candidates; uses `LLMProvider` so it's backend-agnostic
- [ ] **MEDIUM** — `ClaudeProvider` (`anthropic` SDK) — second concrete `LLMProvider` implementation; enables quality/cost benchmarking against the Ollama baseline
- [ ] **MEDIUM** — Relationship extraction module: `RelationshipExtractor` ABC + `LLMExtractor` — extract relationships between resolved entities from article text
- [ ] **MEDIUM** — KG validation: temporal consistency (valid_until >= valid_from), alias collision detection across entities, entity-type relationship constraints

#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
