## Backlog

### 2026 April 28th (v0.58.9 refactor review)

- [x] **LOW** — `cli/backfill.py`: replace `logging.basicConfig()` call with shared `setup_logging()` from `cli/_logging.py` to match all other CLI modules
- [x] **LOW** — `cli/db_health.py:243`: replace `print()` with `logger.info()` — no change needed; `print()` is intentional (structured report output, log prefixes would break column alignment)

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
