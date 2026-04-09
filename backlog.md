## Backlog

### 2026 March 30th

#### Pipeline foundation (detection → resolution → extraction)

- [x] **HIGH** — Pipeline orchestration: `Pipeline` class wiring detection → resolution → provenance creation — process an article and produce entity mentions linked to KG
- [ ] **MEDIUM** — LLM-based entity resolver using Claude API — reads entity descriptions + context snippets to disambiguate when alias lookup returns multiple candidates
- [ ] **MEDIUM** — Relationship extraction module: `RelationshipExtractor` ABC + `LLMExtractor` — extract relationships between resolved entities from article text
- [ ] **MEDIUM** — KG validation: temporal consistency (valid_until >= valid_from), alias collision detection across entities, entity-type relationship constraints

#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources

### 2026 April 8th (v0.17.5 optimization review)

- [x] **HIGH** — Add `save_relationships()` batch method to `RelationshipMixin` — mirrors `save_provenances()`, avoids per-record commits when saving multiple relationships in a loop
- [x] **MEDIUM** — Add `limit` parameter to `find_co_mentioned()` and entity search methods (`find_entities_by_type`, `find_entities_by_status`, etc.) — prevents unbounded result sets and unnecessary alias loading for large KGs
- [x] **MEDIUM** — Deduplicate articles by URL before enrichment in `Scraper` — currently `_enrich()` runs per-feed inside `_parse_feed()`, so duplicate URLs across feeds trigger redundant full-text extractions
- [x] **LOW** — Remove unnecessary `list()` conversion in `_log_entity()` alias serialization (`_entity_mixin.py:497`) — `json.dumps()` accepts tuples directly, avoiding an intermediate list allocation

