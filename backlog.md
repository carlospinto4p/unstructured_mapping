## Backlog

### 2026 March 30th

#### KG population (bootstrap + growth)

- [x] **HIGH** — Curated seed file: JSON file with ~50-100 key financial entities (central banks, top companies, indices, policymakers, core metrics) with aliases — version-controlled for reproducible KG bootstrap
- [x] **HIGH** — Seed loader script: reads the curated seed file, persists entities to the KG with `reason="seed"`, reports counts by type
- [x] **MEDIUM** — Cold-start LLM mode: pipeline mode that sends raw article text directly to the LLM for full entity extraction (bypasses detection), useful for initial population from an empty KG
- [ ] **LOW** — Wikidata seed pipeline: query Wikidata SPARQL for financial entities, map to KG schema, bulk-import — heavy but provides broad coverage and external IDs when needed

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
