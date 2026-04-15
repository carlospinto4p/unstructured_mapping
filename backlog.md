## Backlog

### 2026.04.16 (refactor review v0.48.1)

- [ ] **HIGH / Small** — Extract provenance mention-count queries into `ProvenanceMixin`. Four CLIs (`audit_aliases.py`, `audit_provenance.py`, `preview.py`, `benchmark_cold_start.py`) execute `SELECT COUNT(*) FROM provenance WHERE entity_id = ?` or multi-table joins directly on `store._conn` with `# noqa: SLF001`. Add `count_mentions_for_entity(entity_id)` and `find_mentions_with_entities(document_id)` to the mixin so CLIs stop reaching into private state.
- [ ] **HIGH / Medium** — Move audit finding queries into a `AuditMixin` on `KnowledgeStore`. `cli/audit_provenance.py` owns `find_short_snippets` / `find_thin_mentions` / `find_narrow_spread` with direct SQL; move the three functions and their dataclasses into `knowledge_graph/_audit_mixin.py` so CLIs become thin presentation layers.
- [ ] **MEDIUM / Small** — Consolidate CLI argparse boilerplate into `cli/_argparse_helpers.py` with `add_db_argument`, `add_csv_output_argument`, etc. Some CLIs use `required=True`, others validate manually in `main()` — pick one idiom and apply it across every CLI.
- [ ] **MEDIUM / Small** — Move the `preview._collect_preview` joins into a store method (`get_mentions_for_document(document_id)` on `EntityMixin` or a new reporting mixin). Removes 2× `# noqa: SLF001` from `preview.py`.
- [ ] **MEDIUM / Small** — Consolidate test helpers. `test_cli_audit_provenance.py::_mention` and `test_cli_audit_aliases.py::_add_mentions` each rebuild provenance fixtures; promote both to `tests/unit/conftest.py` as `make_provenance(...)` and `add_mentions_to_store(...)`.
- [ ] **LOW / Small** — Extract DB-open helper. `cli/db_health.py` validates DB existence before opening; other CLIs let `KnowledgeStore` fail. Add `cli/_db_helpers.py::open_kg_store(path, *, create_if_missing=False)` for a single failure mode.
- [ ] **LOW / Small** — Drop the unused `ConstraintWarning` re-export from `knowledge_graph/__init__.py`. No production module imports it; keep it internal to `validation.py`.

### 2026.04.14 (improvements review v0.38.2)

- [x] **MEDIUM / Medium** — Temporal + confidence qualifiers on relationships. Done in v0.45.0: `Relationship.confidence` + `relationships.confidence` column (nullable REAL); Pass 2 prompt + parser capture an optional 0–1 score (clamped, non-numeric → None); new `store.find_relationships(entity_id, *, at=date, min_confidence=N)` combines an at-date window with a confidence floor. `valid_from` / `valid_until` inference continues via the existing Pass 2 prompt fields.
- [x] **MEDIUM / Small** — Pipeline dry-run / preview mode. Done in v0.46.0: new `cli/preview.py` runs one article against a throwaway copy of the KG and emits mentions / proposals / relationships / token usage as JSON. Supports `--article-file`, `--text`, `--cold-start`, and `--no-llm`. Source KG is never mutated.
- [x] **MEDIUM / Small** — Alias-collision CLI. Done in v0.47.0: `cli/audit_aliases.py` ranks collisions by total mention count, proposes same-type merges with an interactive `[y/N]` confirm, and leaves cross-type collisions for human review. `--auto-confirm` is a scripted escape hatch gated on `--apply`.
- [x] **LOW / Small** — Provenance quality audit CLI. Done in v0.48.0: `cli/audit_provenance.py` flags short snippets, thin mentions (including zero-mention orphans), and narrow temporal spreads; text report or combined CSV via `--csv`.
- [x] **LOW / Small** — Query cookbook. Done in v0.48.1: `docs/examples/queries.sql` ships ten labelled queries; a smoke test (`tests/unit/test_docs_queries.py`) executes each against a fresh KG so schema drift breaks the docs fast.

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
