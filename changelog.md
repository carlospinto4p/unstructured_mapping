## Changelog

### v0.60.11 - 2nd May 2026

- Rotated changelog: archived 21 entries to , keeping 30.



### v0.60.10 - 30th April 2026

- Added to Feed page (`frontend/src/routes/feed/+page.svelte`):
  - Model selector: text input with datalist suggestions below the provider dropdown; defaults to `claude-haiku-4-5-20251001` for Claude and `llama3.1:8b` for Ollama, resets automatically on provider change; wired into the ingest API call.
  - LLM/no-LLM badges on each step card header (Steps 0 and 1 show "No LLM"; Step 2 shows "Uses LLM").
  - Pipeline stage breakdown inside Step 2: four labelled rows (Entity detection, Alias resolution, Entity resolution, Relationship extraction) each showing an LLM or no-LLM badge and a description; adapts to cold-start mode; "view prompt" links open the prompts modal directly on the relevant tab.
  - Prompts modal: overlay showing the exact system prompts and user prompt structure for pass 1 (entity resolution) and pass 2 (relationship extraction), with metadata explaining JSON mode differences between Claude and Ollama.


### v0.60.9 - 30th April 2026

- Added workflow guide to `frontend/src/routes/feed/+page.svelte`: collapsible panel covering first-time setup (seed → cold-start → steady-state), ongoing operation cycle, and quality maintenance (alias audit, Wikidata refresh); auto-opens when the KG is empty; includes the Reuters body-text limitation note and links to the graph.
- Added Reuters body extraction gap to `backlog.md`.


### v0.60.8 - 30th April 2026

- Improved frontend clarity across all four pages (`frontend/src/routes/`):
  - `+page.svelte` (Dashboard): added intro paragraph explaining entities/relationships/articles; added per-card hint text; added section hints for the entity-type and article-source tables; expanded "Latest run" row labels with context.
  - `feed/+page.svelte` (Feed): expanded all three step descriptions; replaced cold-start `title` tooltip with a visible inline note that toggles with the checkbox; added KG Maintenance section intro; expanded alias-collision audit description; added column legend above the collision table; added panel hints to the scraped-articles and pipeline-runs tables.
  - `graph/+page.svelte` (KG Graph): added usage instructions in the search sidebar; added empty-canvas state with guidance; added a type colour legend at the bottom of the sidebar; labelled relationship direction arrows; added "click to add to graph" hint in the detail panel; added overflow hint when >10 relationships.
  - `entities/[id]/+page.svelte` (Entity detail): added tab-level hint paragraphs explaining relationships and mentions; added direction legend (→ out / ← in) and confidence explanation in the relationships tab; highlighted low-confidence rows; added `title` tooltips on direction cells and entity-ID links; expanded empty-state messages.


### v0.60.7 - 30th April 2026

- Optimised `knowledge_graph/_relationship_mixin.py` `save_relationships`:
  - Replaced N per-row `SELECT 1` existence checks with a single bulk `SELECT` filtered by source IDs, then Python-set filtering.
  - Replaced N individual `_log_relationship` calls with a single `executemany` batch insert into `relationship_history`.
- Optimised `pipeline/llm/budget.py`:
  - `_count_alias_matches`: parameter renamed `lower_text`; callers now pass pre-lowercased text so `chunk_text.lower()` is called once per `fit_candidates` invocation instead of once per candidate.
  - `fit_candidates`: replaced O(N²) `build_kg_context_block([*fitted, entity])` loop with incremental char-count tracking via new `_entity_block_chars` helper (fast path for the default `estimate_tokens` case; falls back to the original approach when a custom tokenizer is provided).
- Optimised `knowledge_graph/_provenance_mixin.py` `find_mentions_with_entities`: deduplicate entity IDs before `load_aliases_batch` using `dict.fromkeys` to avoid inflating the batch query with duplicates.


### v0.60.6 - 30th April 2026

- Refactored `pipeline/_article_processor.py`:
  - Added `_accumulate_usage(stage, metrics)` helper; replaced three inline `getattr / if usage is not None` blocks with calls to it.
  - Updated `provider_name` / `model_name` properties to read `stage.provider` (public) instead of `stage._provider` (private attribute reflection).
  - Removed redundant outer `with self._store.transaction()` wrapping `_persist_aggregated` — the method already owns its transaction.
- Added `provider` property to `LLMEntityResolver`, `LLMRelationshipExtractor`, and `ColdStartEntityDiscoverer` — exposes the backing `LLMProvider` without requiring callers to reach into `_provider`.
- Refactored `pipeline/llm/provider.py`: changed `supports_json_mode` from `@abstractmethod` to a concrete property returning `False`; subclasses may override via class attribute or property.
- Updated `tests/unit/test_pipeline.py`: updated `StubLLMResolver` to expose `provider` as a public attribute.


### v0.60.5 - 30th April 2026

- Refactored `wikidata/`:
  - Added `fetch.py` with public `fetch_mapped()` and `write_snapshot()`, promoted from private helpers in `cli/wikidata_seed.py`.
  - Exported both from `wikidata/__init__.py`.
- Updated `api/kg.py`: replaced private CLI imports (`_fetch_mapped`, `_write_snapshot`) with `wikidata.fetch_mapped` and `wikidata.write_snapshot`; removed `# noqa: PLC2701` suppressions.
- Updated `cli/wikidata_seed.py`: removed duplicated function bodies and imported from `wikidata` instead.
- Updated `tests/unit/test_wikidata_seed.py`: updated `write_snapshot` call to use `wikidata.write_snapshot`.


### v0.60.4 - 30th April 2026

- Updated `api/kg.py`:
  - Added `POST /api/kg/wikidata-refresh` — re-fetches all (or selected) entity types from Wikidata SPARQL, overwrites local snapshots, and imports new rows into the KG. Accepts `types` (list, defaults to all) and `limit` (per type, default 100).
  - Added `GET /api/kg/alias-audit` — runs `find_alias_collisions` + `score_collisions`, returns collisions ranked by mention prevalence with merge-target suggestions for same-type duplicates.
- Updated `frontend/src/lib/api.ts`: added `WikidataRefreshType`, `WikidataRefreshResponse`, `AliasEntity`, `AliasCollision`, `AliasAuditResponse` types and `api.kg.wikidataRefresh()` / `api.kg.aliasAudit()` client methods.
- Updated `frontend/src/routes/feed/+page.svelte`: added collapsible "KG Maintenance" section with Wikidata refresh button + alias audit button and inline collision table.


### v0.60.3 - 29th April 2026

- Updated `api/runs.py`: added `_check_provider()` — verifies `ANTHROPIC_API_KEY` is set (Claude) or the Ollama daemon is reachable (Ollama) before spawning the ingest thread; returns HTTP 400 with a clear message instead of silently failing.
- Updated `frontend/src/routes/feed/+page.svelte`:
  - Added "Cold start" checkbox to the Step 2 ingest form with a tooltip explaining the mode.
  - Passes `cold_start` to `api.runs.ingest()`.


### v0.60.2 - 29th April 2026

- Added `api/kg.py`: `POST /api/kg/populate` endpoint — runs curated seed + Wikidata snapshots in a thread, returns per-stage summary (created/skipped counts).
- Updated `api/__init__.py`:
  - Registered `/api/kg` router.
  - Added `SEED_DIR` env var to lifespan (`app.state.seed_dir`, defaults to `data/seed`).
- Updated `api/_deps.py`: added `get_seed_dir()` dependency.
- Updated `frontend/src/lib/api.ts`: added `PopulateStage`, `PopulateResponse` types and `api.kg.populate()` client method.
- Updated `frontend/src/routes/feed/+page.svelte`:
  - Added Step 0 "Seed entities" card with live entity count, warning banner when KG is empty, and populate button.
  - Updated subtitle to reflect three-step pipeline.


### v0.60.1 - 29th April 2026

- Added Docker support:
  - `frontend/Dockerfile`: multi-stage Node 22 build using `@sveltejs/adapter-node`; runs `node build` on port 3000.
  - `nginx.conf`: reverse proxy — routes `/api/` to FastAPI (`api:8000`) and `/` to SvelteKit (`frontend:3000`); SSE buffering disabled.
  - Updated `docker-compose.yml`: added `api` (FastAPI), `frontend` (SvelteKit), and `nginx` (port 80) services alongside the existing `scraper`.
  - Updated `Dockerfile`: added `--extra api` so the Python image installs FastAPI + uvicorn.
  - `frontend/svelte.config.js`: switched from `adapter-auto` to `adapter-node`.


### v0.60.0 - 29th April 2026

- Added `frontend/` SvelteKit application:
  - `src/lib/api.ts`: typed fetch client for all API endpoints (entities, relationships, runs, scrape, health).
  - `src/routes/+layout.svelte`: dark nav sidebar with links to Dashboard, KG Graph, and Feed.
  - `src/routes/+page.svelte`: Dashboard — entity/relationship/article counts, entities by type, articles by source, latest run.
  - `src/routes/graph/+page.svelte`: KG graph view — entity search sidebar, Svelte Flow canvas (nodes colour-coded by entity type, relationship edges), entity detail panel with relationship list.
  - `src/routes/feed/+page.svelte`: Feed — recent articles table with source filter, scrape trigger, ingest trigger with provider/limit controls, live run polling, recent runs table.
  - `src/routes/entities/[id]/+page.svelte`: Entity detail — header with type badge, aliases, meta counts; Relationships tab (direction, entity link, confidence, valid_from); Mentions tab (source, mention text, context snippet).
- `vite.config.ts`: proxy `/api` to `http://localhost:8000` in dev mode.
- `@xyflow/svelte` added as a frontend dependency.


### v0.59.0 - 29th April 2026

- Added `src/unstructured_mapping/api/`:
  - `__init__.py`: FastAPI app factory with CORS and lifespan; reads `KNOWLEDGE_DB`, `ARTICLES_DB`, `ALLOWED_ORIGINS` from env.
  - `_deps.py`: per-request `KnowledgeStore` and `ArticleStore` dependency providers.
  - `_serializers.py`: `asdict()`-based JSON serialisers for `Entity`, `Relationship`, `Provenance`, `IngestionRun`, and `Article`.
  - `entities.py`: `GET /api/entities`, `GET /api/entities/{id}`, `GET /api/entities/{id}/relationships`, `GET /api/entities/{id}/provenance`.
  - `relationships.py`: `GET /api/relationships` with `entity_id`, `source_id`, `target_id`, `type`, and `min_confidence` filters.
  - `runs.py`: `GET /api/runs`, `GET /api/runs/{id}`, `POST /api/runs/ingest` (fire-and-forget background thread), `GET /api/runs/{id}/stream` (SSE status stream).
  - `scrape.py`: `POST /api/scrape` (background scrape), `GET /api/scrape/articles`.
  - `health.py`: `GET /api/health` with entity counts by type, relationship count, article counts by source, and latest run.
- Added `cli/serve.py`: uvicorn entry point (`uv run python -m unstructured_mapping.cli.serve`).
- Added `pyproject.toml` `api` optional extra: `fastapi>=0.115.0`, `uvicorn[standard]>=0.30.0`.
- Added `knowledge_graph/_run_mixin.py`: `find_recent_runs(limit)`.
- Added `knowledge_graph/_relationship_mixin.py`: `count_relationships()`.


### v0.58.11 - 29th April 2026

- Fixed `cli/ingest._summarise()`: `skipped (idempotent)` count could go negative when articles failed. Now computed directly from `ArticleResult.skipped` flags so `submitted = processed + skipped + failed` always balances.
- Added `tests/unit/test_ingest.py`: 5 tests covering all combinations of processed, skipped, and failed articles.


### v0.58.10 - 28th April 2026

- Updated `cli/backfill.py`: replaced inline `logging.basicConfig()` with shared `setup_logging()` from `cli/_logging.py` to match all other CLI modules.


### v0.58.9 - 28th April 2026

- Refactored module naming conventions (leading-underscore for internal concrete implementations):
  - `web_scraping/`: renamed `ap.py`, `bbc.py`, `reuters.py` → `_ap.py`, `_bbc.py`, `_reuters.py`; updated `web_scraping/__init__.py` and test patch paths.
  - `pipeline/segmentation/`: renamed `filing.py`, `news.py`, `research.py`, `transcript.py` → `_filing.py`, `_news.py`, `_research.py`, `_transcript.py`; updated `segmentation/__init__.py`.


### v0.58.8 - 28th April 2026

- Refactored `src/unstructured_mapping/pipeline/`:
  - Extracted `pipeline/llm/` subpackage — moved all LLM-related modules out of the flat `pipeline/` namespace:
    - `llm_provider.py` → `llm/provider.py`
    - `llm_claude.py` → `llm/claude.py`
    - `llm_ollama.py` → `llm/ollama.py`
    - `llm_fallback.py` → `llm/fallback.py`
    - `llm_parsers.py` → `llm/parsers.py`
    - `_llm_retry.py` → `llm/_retry.py`
    - `prompts.py` → `llm/prompts.py`
    - `budget.py` → `llm/budget.py`
    - `_optional_import.py` → `llm/_optional_import.py`
  - Updated all internal imports in `resolution.py`, `extraction.py`, `cold_start.py`, and `pipeline/__init__.py`.
  - Updated test imports in `tests/unit/` to reflect new module paths.
  - Fixed Python 2-style `except A, B:` syntax → `except (A, B):` in `llm/fallback.py`.


### v0.58.7 - 27th April 2026

- Refactored `tests/unit/`:
  - Moved `seed_file`, `seed_dir`, `articles_db`, and `kg_db` fixtures from inline test files into `tests/unit/conftest.py` so a new field on `Entity` only needs one update.
  - `log_import_summary` already shared across all seed loaders — no changes needed.
  - Fixed 81-char line in `cli/ingest.py`: wrapped log string literal to fit 78-char limit.


### v0.58.6 - 27th April 2026

- Refactored `pipeline/orchestrator.py`:
  - Added `pipeline/_article_processor.py`: `ArticleProcessor` class — carries all per-article stages (detection, resolution, extraction, persistence) and `_MetricsAccumulator`/`ArticleResult` dataclasses. Metrics are passed as a parameter so one accumulator spans a full batch.
  - Slimmed `Pipeline` to batch/run-bookkeeping only; delegates per-article work to `ArticleProcessor`. `ArticleResult` is re-exported from `orchestrator.py` for backward compatibility.
  - Updated `tests/unit/test_cli_ingest.py`: internal-wiring assertions now reach through `pipeline._processor`.
- Refactored `knowledge_graph/_entity_helpers.py`:
  - Converted `EntityHelpersMixin` to module-level functions taking a `conn` parameter: `rows_to_entities`, `find_entities_where`, `sync_aliases`, `log_entity`, `load_aliases`, `load_aliases_batch`, `redirect_entity_references`.
  - Removed the mixin inheritance pyramid; each sub-mixin (`_entity_crud_mixin`, `_entity_search_mixin`, `_entity_merge_mixin`, `_entity_history_mixin`, `_provenance_mixin`) now calls the helpers directly with `self._conn`.
  - `TYPE_CHECKING` stubs for cross-mixin calls (`get_entity`, `save_entity`) moved to the mixins that actually need them.


### v0.58.5 - 27th April 2026

- Added `cli/_runner.py`: `run_cli_with_kg()` — shared startup helper that
  centralises `setup_logging`, arg parsing, optional arg validation, and the
  `open_kg_store` context manager so CLI `main()` functions stop repeating
  the same three lines.
- Added `cli/_json_output.py`:
  - `emit_json()`: serialises a payload as indented JSON to stdout or a file
    (`datetime`/`UUID`/`Path` coerced via `default=str`).
  - `emit_jsonl()`: serialises rows as newline-delimited JSON to stdout or a
    file; returns row count.
- Migrated to `run_cli_with_kg()`:
  - `cli/run_report.py`
  - `cli/run_diff.py`
  - `cli/audit_provenance.py`
  - `cli/audit_aliases.py`
  - `cli/subgraph.py`
  - `cli/validate_snapshot.py`
  - `cli/export.py`
- Migrated to `emit_json()` / `emit_jsonl()`:
  - `cli/subgraph.py`: replaced inline `json.dumps` + stdout/file write.
  - `cli/preview.py`: replaced inline `json.dumps` + stdout/file write.
  - `cli/export.py`: replaced private `_write_jsonl()` with `emit_jsonl()`.


### v0.58.4 - 26th April 2026

- Updated `.claude/rules/committing.md`: remove SKIP workaround, ruff now runs via `uv run ruff` in all projects.



### v0.58.3 - 26th April 2026

- Updated `.claude/rules/committing.md`: add Windows `SKIP=ruff-format,ruff-fix` pattern for pre-commit hook failures when ruff is not in PATH.



### v0.58.2 - 25th April 2026

- Refactored `cli/validate_snapshot.py` (501 lines) by lifting KG-quality primitives into a new `knowledge_graph/snapshot.py`:
  - Moved: `Snapshot`, `CollisionSummary`, `CheckResult`, `capture_snapshot`, `compare_snapshots`, `load_snapshot`, `write_snapshot`, `DEFAULT_TOP_K_COLLISIONS`, `SCHEMA_VERSION`, plus the small private helpers `_count_by_type_subtype`, `_scalar_count`, `_format_counts_diff`.
  - Why: snapshot capture and comparison are KG-domain concerns. Hosting them in a CLI module forced future tooling (drift checks between two live KGs, dashboards, LLM context blocks) to depend on a CLI surface; they now live next to `validation.py` and `storage.py`.
  - CLI shrank from 501 → 184 lines and only owns argparse plumbing + dispatch.
- Preserved back-compat: `cli/validate_snapshot.py` re-exports every public name so callers and tests importing from it keep working unchanged.


### v0.58.1 - 25th April 2026

- Refactored `KnowledgeStore` lookup naming to a single rule — `get_*` returns at most one record (or a dict keyed by exact id), `find_*` returns a filtered list/set. Added the convention to `KnowledgeStore`'s docstring.
  - Renamed methods (canonical names → old names kept as class-level aliases):
    - `find_relationships_for_entity` ← `get_relationships`.
    - `find_relationships_between` ← `get_relationships_between`.
    - `find_relationship_history` ← `get_relationship_history`.
    - `find_provenance_for_entity` ← `get_provenance`.
    - `find_entity_history` ← `get_entity_history`.
    - `find_entities_touched_by_run` ← `get_entities_touched_by_run`.
    - `find_failed_document_ids` ← `get_failed_document_ids`.
    - `find_relationship_keys_for_run` ← `get_relationship_keys_for_run`.
- Migrated internal callers to the canonical names:
  - `cli/export.py`, `cli/ingest.py`, `cli/run_diff.py`, `cli/run_report.py`, `cli/subgraph.py`, `pipeline/orchestrator.py`, plus `:meth:` references in `_provenance_mixin`, `_relationship_mixin`, and `_run_mixin` docstrings.
- Added `tests/unit/test_kg_runs_and_history.py::test_back_compat_aliases_resolve_to_find_methods`: pins each legacy `get_*` to its canonical `find_*` so future refactors can't accidentally diverge their behaviour.


### v0.58.0 - 25th April 2026

- Added `pipeline/llm_fallback.py`: two-provider fallback chain.
  - `FallbackLLMProvider(primary, secondary, ambiguity_threshold, ambiguity_fn)`: conforms to `LLMProvider`, escalates to the secondary on any `LLMProviderError` or when the scorer exceeds the threshold. Exposes `last_served_by` and `escalations` for per-run monitoring.
  - `default_ambiguity_score()`: scores a raw response on `[0, 1]` — malformed JSON / missing or empty `entities` → 1.0, otherwise the proposal-to-resolution ratio for pass-1 shapes; pass-2 responses score 0.0.
  - Metadata composition: `provider_name` and `model_name` are composite strings (so run scorecards distinguish fallback chains from bare providers), `context_window` is the min of the two sides, and `supports_json_mode` is the AND (safe because the secondary is called on escalation).
  - `last_token_usage` sums primary + secondary usage when escalation fires, so pipeline run totals capture the true cost.
- Exported `FallbackLLMProvider`, `default_ambiguity_score`, and `DEFAULT_AMBIGUITY_THRESHOLD` from `pipeline/__init__.py`.
- Added `tests/unit/test_llm_fallback.py`: 20 tests covering the scorer across every response shape, routing matrix (primary-succeeds / ambiguous / hard-failure), token summing, threshold-validation, composite metadata derivation, and the custom-scorer escape hatch.


### v0.57.0 - 24th April 2026

- Added content-hash deduplication in `web_scraping/storage.py`:
  - `compute_content_hash()`: SHA-256 over a normalised body (lower-cased, whitespace-collapsed) so minor formatting drift across newswire copies still collides.
  - `content_hash` column on `articles` plus `idx_content_hash` for O(log n) collision lookups.
  - Migration step `_migrate_add_content_hash()` adds the column and backfills hashes for every pre-existing row so the collision check has a populated baseline on legacy DBs.
  - `ArticleStore.save(skip_content_dupes=True)`: batched collision check that drops duplicates already in the DB and duplicates within the same batch, logging each at INFO. `skip_content_dupes=False` preserves every non-URL duplicate for archival runs.
- Updated `cli/scrape.py`: added `--no-dedup` flag that forwards `skip_content_dupes=False` to the store.
- Added tests in `tests/unit/test_web_scraping.py`:
  - `compute_content_hash` case/whitespace invariance and collision behaviour.
  - Cross-URL dedup, in-batch dedup, and the `--no-dedup` opt-out.
  - `content_hash` column persistence and migration backfill.


### v0.56.0 - 24th April 2026

- Added `cli/subgraph.py`: entity-centric k-hop subgraph extraction.
  - `build_subgraph()`: BFS from a root entity through `find_relationships` in both directions; emits root, entities, relationships, and the distinct document ids that justify each edge.
  - Root resolution via `--entity-id` or `--name` (ambiguous names fail fast with a candidate list).
  - `--min-confidence` threshold drops weak edges before the BFS expands through them, so unreliable relationships don't pull in distant neighbours.
  - `--hops 0` returns just the root; stable ordering (root first, entities by canonical name, edges by source/target/type/valid_from) so the payload diffs cleanly between runs.
- Added `tests/unit/test_cli_subgraph.py`: 13 tests covering hop depths (0/1/2), the min-confidence filter, name/id resolution, ambiguity + not-found errors, `main` stdout / file-output contracts, negative-hops guard, and payload determinism.


### v0.55.0 - 24th April 2026

- Added `cli/ingest.py`: user-facing batch-ingest CLI that runs the orchestrator over scraped articles. Supports `--source` / `--limit` filters, cold-start / no-LLM / full-pipeline modes, and both Ollama and Claude providers.
- Added `--resume-run <run_id>` to `cli/ingest.py`: loads the failed document ids from `article_failures`, fetches just those articles from the articles DB, and forwards the run id to `Pipeline.run` so the retry is filtered on both sides. Bridges the v0.54.0 plumbing to a real user entry point.
- Updated `ArticleStore.load()` in `web_scraping/storage.py`: added a `document_ids=` keyword filter that accepts both canonical UUID and 32-char hex forms. Needed because `Pipeline` stores failure ids as `UUID.hex` but the articles table uses `str(UUID)`.
- Added `tests/unit/test_cli_ingest.py`: 13 tests covering article loading (filter + resume), pipeline-assembly modes, alias-only ingestion, the resume workflow end-to-end, stdout contract, cold-start guardrails, and the new `document_ids=` filter on `ArticleStore.load`.


### v0.54.0 - 24th April 2026

- Added per-article failure tracking + `Pipeline.run()` resume support:
  - `article_failures` table in `knowledge_graph/storage.py`: `(run_id, document_id, error_message, failed_at)` with composite PK on `(run_id, document_id)` and FK to `ingestion_runs`.
  - Index `idx_article_failures_run` for fast per-run lookup.
  - `KnowledgeStore.save_article_failure()`: `INSERT OR REPLACE` upsert so a resumed article that fails again refreshes the prior row.
  - `KnowledgeStore.get_failed_document_ids()`: returns the failed set, sorted, for a given run_id.
- Updated `pipeline/orchestrator.py`:
  - `Pipeline._process_article()`: the per-article `except` now calls `save_article_failure` so a crashed batch leaves behind the exact re-queue list.
  - `Pipeline.run(articles, *, resume_run_id=None)`: when set, filters `articles` down to the failed ids from the prior run before allocating the new run_id.
- Added tests:
  - `tests/unit/test_kg_runs_and_history.py`: `save_article_failure` / `get_failed_document_ids` roundtrip, upsert semantics, per-run scoping, empty-run behaviour.
  - `tests/unit/test_pipeline.py`: orchestrator records a failure row, `resume_run_id` filters to failed docs, resuming a clean run is a no-op.
- Deferred: a user-facing `--resume-run` CLI flag. The backlog item specified it live on `cli/populate.py`, which is currently a seed loader (curated JSON + Wikidata snapshots) and does not drive the LLM pipeline; wiring the flag there would be inert. Left as a follow-up to land alongside a canonical batch-ingest CLI.


### v0.53.0 - 24th April 2026

- Added `cli/validate_snapshot.py`: golden-snapshot KG quality gate.
  - `--record PATH`: capture a structured KG summary (counts by type / subtype, top-K alias collisions, provenance density, totals) and persist as JSON.
  - `--check BASELINE`: capture the current KG, compare against a baseline, print the diff, and exit non-zero when thresholds are breached.
  - Thresholds: `--max-entity-drop-pct` (default 10) and `--max-collision-increase` (default 0).
  - Exports `Snapshot`, `CollisionSummary`, `CheckResult`, `capture_snapshot`, `compare_snapshots`, `load_snapshot`, `write_snapshot` for programmatic use.
- Added `tests/unit/test_cli_validate_snapshot.py`: 17 tests covering snapshot totals, per-type/subtype counts, collision capture, JSON roundtrip, schema-version guard, threshold gates (drop + collisions), and `main` record/check paths.


### v0.52.0 - 24th April 2026

- Added Parquet export to `cli/export.py`:
  - `SUPPORTED_FORMATS` now includes `parquet` alongside `jsonl` and `json-ld`.
  - `_write_parquet()`: uses `pyarrow.Table.from_pylist` + `pyarrow.parquet.write_table` so list columns (e.g. `aliases`) land as native Parquet `LIST` types.
  - Raises a clear `ImportError` pointing at `pip install 'unstructured-mapping[export]'` when `pyarrow` is missing.
- Added `export` optional extra in `pyproject.toml` (`pyarrow>=15`); mirrored into `dev` so developer envs keep full test coverage.
- Added tests in `tests/unit/test_cli_export.py`: parquet roundtrip, type filter, `main` parquet path, and missing-pyarrow error surface.


