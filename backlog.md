## Backlog

### 2026 March 30th

#### Pipeline foundation (detection → resolution → extraction)

- [x] **HIGH** — Entity detection module: `EntityDetector` ABC + `RuleBasedDetector` using alias trie matching — baseline detector that finds entity mentions in text by matching against KG aliases
- [x] **HIGH** — Entity resolution module: `EntityResolver` ABC + `AliasResolver` for exact alias lookup — resolves detected mentions to KG entities; baseline before LLM-based resolution
- [ ] **HIGH** — Pipeline orchestration: `Pipeline` class wiring detection → resolution → provenance creation — process an article and produce entity mentions linked to KG
- [ ] **MEDIUM** — LLM-based entity resolver using Claude API — reads entity descriptions + context snippets to disambiguate when alias lookup returns multiple candidates
- [ ] **MEDIUM** — Relationship extraction module: `RelationshipExtractor` ABC + `LLMExtractor` — extract relationships between resolved entities from article text
- [ ] **MEDIUM** — KG validation: temporal consistency (valid_until >= valid_from), alias collision detection across entities, entity-type relationship constraints

#### Pipeline deferred decisions

- [x] Add `run_id` FK to provenance and relationships — explicit link to the ingestion run that created each record, replacing timestamp-based correlation

#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
