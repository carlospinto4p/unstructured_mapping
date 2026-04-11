# Pipeline Orchestration

The orchestrator wires detection, resolution, extraction,
and persistence into a single callable `Pipeline` class.
Given an `Article` (from `web_scraping`), it produces
`Provenance` and `Relationship` records in the
`KnowledgeStore` and tracks the execution in an
`IngestionRun`.


## Role in the pipeline

```mermaid
flowchart LR
    A[Article] --> B[Detection]
    B --> C[Resolution]
    C --> D[Extraction]
    D --> E[Persistence]
    E --> F[IngestionRun]

    style B fill:#bbf,stroke:#333
    style C fill:#f9f,stroke:#333
    style D fill:#fbf,stroke:#333
    style E fill:#bfb,stroke:#333
```


## Public interface

```python
class Pipeline:
    def __init__(
        self,
        detector: EntityDetector,
        resolver: EntityResolver,
        store: KnowledgeStore,
        *,
        llm_resolver: LLMEntityResolver | None = None,
        extractor: RelationshipExtractor | None = None,
        skip_processed: bool = True,
    ) -> None: ...

    def run(
        self, articles: list[Article]
    ) -> PipelineResult: ...

    def process_article(
        self,
        article: Article,
        *,
        run_id: str | None = None,
    ) -> ArticleResult: ...
```

Two result types — both frozen dataclasses:

- **`ArticleResult`** — per-article outcome. Exposes the
  raw `ResolutionResult` (so callers can inspect
  ambiguous mentions), counts for provenance rows,
  new entities (proposals), and relationships saved,
  a `skipped` flag, and an `error` message when
  article-level processing failed.
- **`PipelineResult`** — aggregate outcome of a run.
  Carries the `run_id`, a tuple of per-article results,
  and totals for documents processed, provenance rows,
  new entities, and relationships saved.


## Processing stages

### 1. Detection

The `RuleBasedDetector` scans the article text for
entity mentions matching known aliases (Aho-Corasick
trie). Returns `Mention` objects with candidate IDs.

### 2. Resolution (pass 1)

Two tiers:

1. `AliasResolver` resolves unambiguous single-candidate
   mentions directly.
2. `LLMEntityResolver` (optional) cascades after the
   alias resolver to handle ambiguous and unknown
   mentions. Proposes new entities via `EntityProposal`.

Proposals are persisted as new `Entity` records with
provenance linking to the source article.

### 3. Extraction (pass 2)

The `RelationshipExtractor` (optional) receives all
resolved entities and the chunk text. It calls the LLM
to extract directed relationships between them.

`ExtractedRelationship` objects are converted to
`Relationship` records by the orchestrator, which adds
persistence metadata:

| From extractor | Added by orchestrator |
|---|---|
| `source_id`, `target_id` | `document_id` |
| `relation_type` | `discovered_at` |
| `qualifier_id` | `run_id` |
| `valid_from`, `valid_until` | |
| `context_snippet` → `description` | |

### 4. Persistence

- Provenance rows are bulk-inserted via
  `save_provenances()`.
- Relationships are bulk-inserted via
  `save_relationships()`.
- The `IngestionRun` is finalized with aggregate counts.


## Design decisions

### Single-chunk articles

News articles are short (500-3000 words) and not
segmented into semantic sections. Each article becomes
one `Chunk` with `chunk_index=0` and
`section_name=None`. Long-form documents (research
reports, earnings call transcripts) need a chunker
upstream — see [`09_chunking.md`](09_chunking.md) — before
reaching the orchestrator. The orchestrator itself does
not chunk.

### Per-article isolation

An exception raised inside detection, resolution,
extraction, or persistence for one article is caught,
logged, and recorded in `ArticleResult.error`. The run
continues with the next article. A run only ends in
`RunStatus.FAILED` when an exception escapes the
per-article handler — e.g. the store itself going
away mid-run. This matches the policy in
[`01_design.md`](01_design.md#error-handling).

### Provenance-based idempotency

The orchestrator queries
`KnowledgeStore.has_document_provenance(doc_id)` before
processing. Articles whose document ID already has any
provenance row are marked `skipped=True` without
running the detector. Callers that need to reprocess
(e.g. after deleting bad provenance) either delete the
rows first or construct the pipeline with
`skip_processed=False`.

The check hits the existing `idx_prov_document` index,
so per-article cost is a single O(log n) point lookup —
fine for batches of a few hundred articles. If we later
process tens of thousands of articles per run, a
pre-loaded `set[str]` of seen document IDs would be
faster.

### Constructor injection

The detector, resolver, extractor, and store are all
injected by the caller. Lifecycle (opening and closing
the store, loading entities into the detector) is the
caller's responsibility. This keeps the orchestrator
itself stateless apart from the injected dependencies,
which in turn:

- lets tests inject stub detectors, resolvers, and
  extractors without monkey-patching,
- lets callers swap implementations without touching
  orchestrator code,
- makes the lifetime of the `KnowledgeStore`
  transaction explicit.

### Run bookkeeping

`Pipeline.run()` opens an `IngestionRun` before the
first article, updates it with aggregated counts at the
end, and finalizes the status. `process_article()` is
exposed as a lower-level entry point for callers that
don't need run tracking — notebooks, debug scripts,
one-off ad-hoc processing.

`entity_count` on the run row holds the total number of
provenance rows inserted, not the number of distinct
entities mentioned. The field name is slightly loose,
but changing it would be a KG migration — the docstring
clarifies the semantics.


## Deferred

- **Parallel article processing.** Articles are
  processed sequentially. At current scale there's no
  benefit; parallelism would complicate error isolation
  and the run counters.
- **Streaming input.** The pipeline processes a list,
  not an iterator. Streaming can be added later if news
  ingestion moves to a push model.
- **Per-chunk orchestration.** Once the chunker lands,
  the inner loop will iterate over chunks per article,
  aggregating the resolutions before writing provenance.
  Not required for single-chunk news articles.
