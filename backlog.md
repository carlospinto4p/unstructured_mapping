## Backlog

### 2026.04.23 (refactor review v0.49.6)

- [x] **HIGH / Small** — Extract shared Google News helpers into new `web_scraping/_gnews.py`: `_has_scraping_deps()` is duplicated in `web_scraping/ap.py:25` and `web_scraping/backfill.py:58`; `ap.py::APScraper._resolve_url/_fetch_page` (static methods) mirror `backfill.py::_resolve_gnews_url/_extract_text`; the `_DECODE_ERRORS`/`_EXTRACT_ERRORS` tuples in `backfill.py:54` belong alongside. `backfill.py`'s module docstring already flags the duplication as a "simpler trade-off" pending a third caller — now there's value in consolidating.
- [ ] **HIGH / Small** — Deduplicate `_CHARS_PER_TOKEN: int = 4` defined in both `knowledge_graph/_audit_mixin.py:31` and `pipeline/budget.py:44`. Both copies already reference each other in comments. Move to a small shared module (e.g. `tokens.py` at `src/unstructured_mapping/`) and import from both sites — eliminates the drift risk the audit-mixin docstring flags.
- [ ] **MEDIUM / Small** — Normalize `_fetch_page()` return-type conventions across scrapers: `ap.py:126` returns `str` (extracted text, empty on failure); `bbc.py:162` returns `bytes | None` (raw HTML, None on failure). Pick one shape in the base `Scraper` class (likely "raw HTML bytes, empty on failure") and let subclasses call a shared fetch helper, so new scrapers inherit a predictable contract.
- [ ] **MEDIUM / Small** — Fold the conditional `--kg-db` validation in `cli/preview.py::main` (argparse can't express "required unless --cold-start") into `cli/_argparse_helpers.py` as a `require_db_unless(flag_name)` helper. The current docstring at the top of `_argparse_helpers.py` explicitly calls out preview's manual validation as the only exception — turning it into a shared helper removes the footnote and makes future cold-start-style CLIs cheaper.
- [ ] **LOW / Medium** — Split `tests/unit/test_kg_provenance.py` (794 lines) by concern: the file covers provenance CRUD, recent-mentions queries, co-mention queries, ingestion runs, and history/migration. Candidate cut: `test_kg_provenance.py` (CRUD + queries) and `test_kg_runs_and_history.py` (runs, finish_run, migrations, count helpers).
- [ ] **LOW / Large** — Split `knowledge_graph/_entity_mixin.py` (639 lines) along its four internal mixin classes (`EntityCRUDMixin`, `EntitySearchMixin`, `EntityMergeMixin`, `EntityHistoryMixin`) into one file per mixin. The module docstring already documents them as four distinct concerns; the file size has crossed the point where navigating them in one file is friction.


### 2026.04.14 (Wikidata import follow-ups)

- [ ] **LOW / Small** — Residual exchange noise after v0.37.1: Deutsche Bank ATS/Off Exchange/Super X, FXCM, Convergex, KCG Americas still slip through. Verify Wikidata QIDs for foreign-exchange broker, alternative trading system, and market maker, then extend the `MINUS` list in `EXCHANGES_QUERY`. Alternatively, maintain a small curated blocklist of QIDs if class-based exclusion keeps missing.
- [ ] **LOW / Small** — Expand curated seed coverage for thin categories surfaced by the overlap review: regulators (SEC, CFTC, ECB-as-regulator, CSRC, BaFin, MAS), top-15 currencies beyond EUR/CHF/GBP, top-15 indices beyond Dow/FTSE 100/Hang Seng/Nasdaq. Curated entries get hand-tuned LLM descriptions, so they beat Wikidata's generic text for resolution quality.

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
