## Backlog

### 2026 March 30th

#### Pipeline foundation (detection → resolution → extraction)

- [ ] **HIGH** — Pipeline orchestration: `Pipeline` class wiring detection → resolution → provenance creation — process an article and produce entity mentions linked to KG
- [ ] **MEDIUM** — LLM-based entity resolver using Claude API — reads entity descriptions + context snippets to disambiguate when alias lookup returns multiple candidates
- [ ] **MEDIUM** — Relationship extraction module: `RelationshipExtractor` ABC + `LLMExtractor` — extract relationships between resolved entities from article text
- [ ] **MEDIUM** — KG validation: temporal consistency (valid_until >= valid_from), alias collision detection across entities, entity-type relationship constraints

#### Post-population (after KG is defined and populated)

- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources

### 2026 April 8th (v0.17.2 refactor review)

- [ ] **MEDIUM** — Replace fragile tuple-index row converters in `knowledge_graph/_helpers.py` with `sqlite3.Row`-based access — 6 converter functions use positional indexing that breaks silently if SELECT column order changes
- [ ] **LOW** — Simplify nested comprehension in `Scraper._enrich()` (`web_scraping/base.py:133-143`) — the `for ex in (result,)` single-element tuple idiom is hard to read; replace with a plain loop or walrus operator
- [ ] **LOW** — Narrow exception handling in `cli/scheduler.py:77` — `ValueError` is too broad alongside `OSError`/`httpx.HTTPError`; replace with the specific errors that can actually occur during a scrape cycle
