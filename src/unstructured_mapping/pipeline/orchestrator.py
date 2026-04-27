"""Pipeline orchestration — article batch to KG records.

Wires the detection, resolution, extraction, and
persistence stages into a single callable
:class:`Pipeline`. Manages ingestion runs, batch
bookkeeping, and cross-run resumption; per-article
processing is delegated to
:class:`~pipeline._article_processor.ArticleProcessor`.

Design notes
------------

- **Single-chunk articles.** News articles are short and
  not segmented, so each article becomes one ``Chunk``
  with ``chunk_index=0``. Long-form documents will need
  a chunker upstream (see ``docs/pipeline/09_chunking.md``)
  before reaching this orchestrator.
- **Per-article isolation.** If one article raises during
  detection/resolution/persist, the error is logged, the
  article is skipped, and the run continues. A run only
  ends in :attr:`RunStatus.FAILED` for pipeline-level
  errors (e.g. the store going away). This matches the
  policy in ``docs/pipeline/01_design.md``.
- **Provenance-based idempotency.** Articles whose
  ``document_id`` already has provenance in the KG are
  skipped. Callers that need reprocessing must delete
  the existing provenance first -- an explicit,
  auditable action.
- **Constructor injection.** The detector, resolver, and
  store are injected, so the caller owns lifecycle and
  tests can swap in fakes without monkey-patching.
- **Cold-start mode.** When a
  :class:`ColdStartEntityDiscoverer` is injected via
  ``cold_start_discoverer``, the orchestrator bypasses
  detection, resolution, and relationship extraction and
  asks the LLM to propose entities directly from the
  article body. See ``docs/pipeline/13_cold_start.md``.
"""

import logging
import time
from dataclasses import dataclass

from unstructured_mapping.knowledge_graph.models import (
    IngestionRun,
    RunStatus,
)
from unstructured_mapping.knowledge_graph.storage import (
    KnowledgeStore,
)
from unstructured_mapping.pipeline._article_processor import (
    ArticleProcessor,
    ArticleResult,
    _MetricsAccumulator,
)
from unstructured_mapping.pipeline.cold_start import (
    ColdStartEntityDiscoverer,
)
from unstructured_mapping.pipeline.detection import (
    EntityDetector,
)
from unstructured_mapping.pipeline.extraction import (
    RelationshipExtractor,
)
from unstructured_mapping.pipeline.resolution import (
    EntityResolver,
    LLMEntityResolver,
)
from unstructured_mapping.pipeline.segmentation import (
    DocumentSegmenter,
)
from unstructured_mapping.web_scraping.models import Article

logger = logging.getLogger(__name__)


def _compute_run_stats(
    results: list[ArticleResult],
) -> tuple[int, int, int, int]:
    """Aggregate counts from per-article results.

    :return: ``(doc_count, prov_count, proposal_count,
        rel_count)`` — documents processed, provenance
        rows, new entities from proposals, and
        relationships persisted.
    """
    processed = [r for r in results if not r.skipped]
    return (
        len(processed),
        sum(r.provenances_saved for r in results),
        sum(r.proposals_saved for r in results),
        sum(r.relationships_saved for r in results),
    )


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Aggregate outcome of a pipeline run.

    :param run_id: The ``IngestionRun.run_id`` tracking
        this invocation. Callers can use it to query the
        run metadata or locate the resulting provenance.
    :param results: One :class:`ArticleResult` per input
        article, in order.
    :param documents_processed: Number of articles that
        were actually processed (excludes skipped).
    :param provenances_saved: Total provenance rows
        inserted across all articles.
    :param proposals_saved: Total new entities created
        from LLM proposals across all articles.
    :param relationships_saved: Total relationship rows
        inserted across all articles.
    """

    run_id: str
    results: tuple[ArticleResult, ...]
    documents_processed: int
    provenances_saved: int
    proposals_saved: int = 0
    relationships_saved: int = 0


class Pipeline:
    """Orchestrates detection -> resolution -> extraction.

    :param detector: Implementation of
        :class:`EntityDetector`. Typically a
        :class:`RuleBasedDetector` built from the active
        KG entities.
    :param resolver: Implementation of
        :class:`EntityResolver`. The default
        :class:`AliasResolver` handles unambiguous
        single-candidate mentions.
    :param store: The :class:`KnowledgeStore` receiving
        provenance and relationship rows, and tracking
        ingestion runs.
    :param llm_resolver: Optional LLM-based resolver
        that cascades after the primary resolver.
        Unresolved mentions from ``resolver`` are
        passed to ``llm_resolver`` for a second pass.
        When ``None`` (the default), unresolved mentions
        are simply left unresolved.
    :param extractor: Optional relationship extractor
        (pass 2). When provided, resolved entities are
        passed to the extractor after resolution, and
        extracted relationships are persisted to the KG.
        When ``None`` (the default), no relationship
        extraction is performed.
    :param cold_start_discoverer: Optional
        :class:`ColdStartEntityDiscoverer`. When provided,
        the pipeline switches to cold-start mode: the
        detector, resolver, and ``llm_resolver`` are all
        bypassed, and the discoverer proposes entities
        directly from the raw article text. Use this only
        for initial KG population; for steady-state
        operation leave it ``None``. Mutually exclusive
        with detection-driven stages (they are ignored
        when a discoverer is set).
    :param skip_processed: When ``True`` (the default),
        articles whose ``document_id`` already has any
        provenance row are skipped. Set ``False`` to
        force reprocessing -- callers that need a clean
        slate should delete existing provenance first.

    Example::

        from unstructured_mapping.pipeline import (
            AliasResolver,
            LLMEntityResolver,
            LLMRelationshipExtractor,
            OllamaProvider,
            Pipeline,
            RuleBasedDetector,
        )
        provider = OllamaProvider(model="...")
        pipeline = Pipeline(
            detector=RuleBasedDetector(
                store.find_entities_by_status(
                    EntityStatus.ACTIVE,
                    limit=5000,
                )
            ),
            resolver=AliasResolver(),
            store=store,
            llm_resolver=LLMEntityResolver(
                provider=provider,
                entity_lookup=store.get_entity,
                entity_batch_lookup=store.get_entities,
            ),
            extractor=LLMRelationshipExtractor(
                provider=provider,
                entity_lookup=store.get_entity,
                name_lookup=store.find_by_name,
                entity_batch_lookup=store.get_entities,
            ),
        )
        result = pipeline.run(articles)
        print(result.relationships_saved)

    Cold-start (empty KG)::

        from unstructured_mapping.pipeline import (
            AliasResolver,
            ColdStartEntityDiscoverer,
            NoopDetector,
            Pipeline,
        )
        pipeline = Pipeline(
            detector=NoopDetector(),
            resolver=AliasResolver(),
            store=store,
            cold_start_discoverer=(
                ColdStartEntityDiscoverer(provider)
            ),
        )
        result = pipeline.run(articles)
        print(result.proposals_saved)
    """

    def __init__(
        self,
        detector: EntityDetector,
        resolver: EntityResolver,
        store: KnowledgeStore,
        *,
        llm_resolver: LLMEntityResolver | None = None,
        extractor: (RelationshipExtractor | None) = None,
        cold_start_discoverer: (ColdStartEntityDiscoverer | None) = None,
        segmenter: DocumentSegmenter | None = None,
        skip_processed: bool = True,
    ) -> None:
        self._store = store
        self._processor = ArticleProcessor(
            detector=detector,
            resolver=resolver,
            store=store,
            llm_resolver=llm_resolver,
            extractor=extractor,
            cold_start_discoverer=cold_start_discoverer,
            segmenter=segmenter,
            skip_processed=skip_processed,
        )
        #: Placeholder so ad-hoc :meth:`process_article`
        #: calls don't crash on the attribute — they just
        #: don't persist a scorecard.
        self._metrics = _MetricsAccumulator(
            run_id="",
            started_monotonic=time.monotonic(),
        )

    # -- Public API -----------------------------------------

    def run(
        self,
        articles: list[Article],
        *,
        resume_run_id: str | None = None,
    ) -> PipelineResult:
        """Process a batch of articles inside one run.

        A new :class:`IngestionRun` is created and saved
        before processing starts. Each article is
        processed in isolation; article-level failures
        are logged and recorded in the per-article
        result, but do not abort the run. The run is
        finalized with aggregated counts in all cases.
        Pipeline-level exceptions (e.g. the store
        failing mid-run) mark the run ``FAILED`` and
        re-raise.

        :param articles: Articles to process.
        :param resume_run_id: When set, filter
            ``articles`` down to just the ones recorded
            as failures in that prior run (see
            :meth:`KnowledgeStore.find_failed_document_ids`).
            Articles whose ``document_id.hex`` does not
            appear in the failed set are dropped before
            the loop starts — re-processing a successful
            article would burn LLM tokens for no new
            output. A fresh run_id is still allocated
            for the resumed batch so the two attempts
            remain separately auditable.
        :return: Aggregate result for the run.
        """
        if resume_run_id is not None:
            failed_ids = set(
                self._store.find_failed_document_ids(resume_run_id)
            )
            before = len(articles)
            articles = [
                a for a in articles if a.document_id.hex in failed_ids
            ]
            logger.info(
                "Resuming run %s: %d/%d articles match the failed set.",
                resume_run_id,
                len(articles),
                before,
            )
        run = IngestionRun()
        self._store.save_run(run)
        logger.info(
            "Pipeline run %s started (%d articles)",
            run.run_id,
            len(articles),
        )
        self._metrics = _MetricsAccumulator(
            run_id=run.run_id,
            started_monotonic=time.monotonic(),
            provider_name=self._processor.provider_name,
            model_name=self._processor.model_name,
        )
        # Prefetch the idempotency set once rather than
        # hitting SQLite per article: on a 1000-article
        # batch this replaces 1000 queries with one.
        already_processed: set[str] = set()
        if self._processor.skip_processed and articles:
            already_processed = self._store.documents_with_provenance(
                [a.document_id.hex for a in articles]
            )
        results: list[ArticleResult] = []
        try:
            for article in articles:
                results.append(
                    self._processor.process_article(
                        article,
                        run.run_id,
                        self._metrics,
                        already_processed=already_processed,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            stats = _compute_run_stats(results)
            self._store.finish_run(
                run.run_id,
                status=RunStatus.FAILED,
                document_count=stats[0],
                entity_count=stats[1],
                relationship_count=stats[3],
                error_message=str(exc),
            )
            self._store.save_run_metrics(self._metrics.finalize())
            logger.exception("Pipeline run %s failed", run.run_id)
            raise

        stats = _compute_run_stats(results)
        doc_count, prov_count, prop_count, rel_count = stats
        self._store.finish_run(
            run.run_id,
            status=RunStatus.COMPLETED,
            document_count=doc_count,
            entity_count=prov_count,
            relationship_count=rel_count,
        )
        self._store.save_run_metrics(self._metrics.finalize())
        logger.info(
            "Pipeline run %s completed: %d processed, "
            "%d skipped, %d provenances, "
            "%d new entities, %d relationships",
            run.run_id,
            doc_count,
            len(results) - doc_count,
            prov_count,
            prop_count,
            rel_count,
        )
        return PipelineResult(
            run_id=run.run_id,
            results=tuple(results),
            documents_processed=doc_count,
            provenances_saved=prov_count,
            proposals_saved=prop_count,
            relationships_saved=rel_count,
        )

    def process_article(
        self,
        article: Article,
        *,
        run_id: str | None = None,
    ) -> ArticleResult:
        """Process a single article without run tracking.

        Useful for ad-hoc calls (e.g. notebooks, debug
        scripts) where the caller does not need an
        ``IngestionRun``. Most production callers should
        use :meth:`run` instead, which handles run
        bookkeeping.

        :param article: The article to process.
        :param run_id: Optional run to attribute
            provenance to. When ``None`` the resulting
            provenance rows have no ``run_id``.
        :return: The per-article result.
        """
        metrics = _MetricsAccumulator(
            run_id=run_id or "",
            started_monotonic=time.monotonic(),
        )
        return self._processor.process_article(article, run_id, metrics)
