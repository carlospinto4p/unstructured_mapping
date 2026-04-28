## Backlog

### 2026 April 28th (v0.58.8 refactor review)

- [ ] **LOW** — Standardise leading-underscore convention in `web_scraping/`: rename `ap.py`, `bbc.py`, `reuters.py` → `_ap.py`, `_bbc.py`, `_reuters.py` to match `_gnews.py`; update `__init__.py` imports
- [ ] **LOW** — Standardise leading-underscore convention in `pipeline/segmentation/`: rename `filing.py`, `news.py`, `research.py`, `transcript.py` to use `_` prefix to match `_sub_chunk.py`; update imports in `segmentation/__init__.py`

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
