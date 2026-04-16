## Backlog

### 2026.04.16 (refactor review v0.48.8)

- [ ] **MEDIUM / Small** — Consolidate the "N created, M skipped + counts" import summary logging duplicated in `cli/seed.py:154-160`, `cli/wikidata_seed.py:227-234`, and the per-stage helper in `cli/populate.py:167-194`. Extract a shared `log_import_summary(created, skipped, counts, *, prefix="", suffix="")` into `cli/_seed_helpers.py` (already home to `import_with_dedup`).
- [ ] **MEDIUM / Small** — Extract the throwaway-KG copy idiom used by `cli/preview.py:187-191` and `cli/benchmark_cold_start.py:351-366`. Add `cli/_db_helpers.py::prepare_throwaway_kg(workdir, name, *, source=None) -> Path` that handles the "unlink if exists; optionally copy from source" shape. Removes the two ad-hoc `shutil.copyfile` sites.
- [ ] **LOW / Small** — Hoist the duplicated `DEFAULT_TIMEOUT = 120.0` constant from `pipeline/llm_ollama.py:55` and `pipeline/llm_claude.py:49` into `pipeline/llm_provider.py` as a shared constant. Both providers already agree on the 120s policy from `docs/pipeline/01_design.md`; context-window defaults stay provider-specific (4K vs 200K).
- [ ] **LOW / Small** — Drop the backwards-compat `_TYPE_HANDLERS = TYPE_REGISTRY` alias in `cli/wikidata_seed.py:68`. Migrate `tests/unit/test_wikidata_seed.py:51,133` to import `TYPE_REGISTRY` directly from `unstructured_mapping.wikidata`, then remove the alias and its comment.


### 2026.04.16 (refactor review v0.48.1)

- [x] **MEDIUM / Small** — Consolidate CLI argparse boilerplate into `cli/_argparse_helpers.py` with `add_db_argument`, `add_csv_output_argument`, etc. Done in v0.48.4: helpers + migration across eight CLIs.
- [x] **MEDIUM / Small** — Move the `preview._collect_preview` joins into a store method. Done in v0.48.5: `find_relationships_by_document` added to `RelationshipMixin`; last `# noqa: SLF001` dropped from `preview.py`.
- [x] **MEDIUM / Small** — Consolidate test helpers. Done in v0.48.6: `make_provenance` and `add_mentions_to_store` live in `conftest.py`; both CLIs migrated.
- [x] **LOW / Small** — Extract DB-open helper. Done in v0.48.7: `open_kg_store(path, *, create_if_missing=False)` landed; audit CLIs migrated.
- [x] **LOW / Small** — Drop the unused `ConstraintWarning` re-export. Done in v0.48.8.

### 2026.04.14 (Wikidata import follow-ups)

- [ ] **MEDIUM / Small** — `company` SPARQL query leaks central banks. "Bank of Japan" and "Swiss National Bank" show up in `company.json` because they hold P414 listing entries. Fix: add a `MINUS { ?item wdt:P31/wdt:P279* wd:Q66344 }` clause (central bank) analogous to the exchange/bank fix.
- [ ] **MEDIUM / Medium** — Deduplicate within-snapshot rows. The index query produces "Stoxx Europe 600 Index" × 289 (of 601 rows); currency has "euro" × 27; company has "Shell" × 18. The v0.35.2 subquery-LIMIT idiom deduplicates item QIDs but the OPTIONAL joins (ticker/exchange/MIC etc.) still fan out. Options: (a) tighten the SPARQL with `SAMPLE()` / `GROUP_CONCAT` over OPTIONALs, or (b) deduplicate by QID in `mapper.py` before writing the snapshot. Impact: ~40% smaller snapshot files and cleaner diffs on refresh.
- [ ] **LOW / Small** — Residual exchange noise after v0.37.1: Deutsche Bank ATS/Off Exchange/Super X, FXCM, Convergex, KCG Americas still slip through. Verify Wikidata QIDs for foreign-exchange broker, alternative trading system, and market maker, then extend the `MINUS` list in `EXCHANGES_QUERY`. Alternatively, maintain a small curated blocklist of QIDs if class-based exclusion keeps missing.
- [ ] **LOW / Small** — Expand curated seed coverage for thin categories surfaced by the overlap review: regulators (SEC, CFTC, ECB-as-regulator, CSRC, BaFin, MAS), top-15 currencies beyond EUR/CHF/GBP, top-15 indices beyond Dow/FTSE 100/Hang Seng/Nasdaq. Curated entries get hand-tuned LLM descriptions, so they beat Wikidata's generic text for resolution quality.

### 2026 March 30th

#### Post-population (after KG is populated)

- [ ] Add `external_ids` table for tickers, ISIN, FIGI, Wikidata QIDs — enables joining KG entities with price feeds and external data sources
- [ ] Build sentiment/signal analysis layer — classify article stance toward entities (positive/negative/neutral), separate from KG provenance

#### Scraping enhancements

- [ ] **LOW** — Podcast transcription pipeline: download BBC Sounds audio and run speech-to-text (e.g. Whisper) to extract text content from podcast episodes — significant effort, but would expand coverage to audio sources
