"""Pipeline orchestration — article to provenance.

Wires the detection, resolution, and persistence stages
into a single callable :class:`Pipeline`. Given an
``Article`` (from :mod:`web_scraping`), the pipeline
produces ``Provenance`` records in the
:class:`KnowledgeStore` and tracks the execution in an
``IngestionRun``.

Relationship extraction is intentionally out of scope
for this class -- that stage has its own ABC and will
be added once an ``LLMExtractor`` exists. The pipeline
is designed to slot it in without rewriting the
orchestrator.

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
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph.models import (
    IngestionRun,
    Provenance,
    RunStatus,
)
from unstructured_mapping.knowledge_graph.storage import (
    KnowledgeStore,
)
from unstructured_mapping.pipeline.detection import (
    EntityDetector,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    ResolutionResult,
)
from unstructured_mapping.pipeline.resolution import (
    EntityResolver,
)
from unstructured_mapping.web_scraping.models import Article

logger = logging.getLogger(__name__)


def _compute_run_stats(
    results: list["ArticleResult"],
) -> tuple[int, int]:
    """Return ``(document_count, provenance_count)``."""
    processed = [r for r in results if not r.skipped]
    return len(processed), sum(
        r.provenances_saved for r in results
    )


@dataclass(frozen=True, slots=True)
class ArticleResult:
    """Outcome of processing a single article.

    :param document_id: The article's ``document_id`` as
        a string (matches the FK stored in provenance).
    :param resolution: Raw resolution result from the
        resolver, exposing both resolved and unresolved
        mentions so callers can inspect ambiguity.
    :param provenances_saved: Number of provenance rows
        inserted by this article. Duplicates already in
        the store are counted as zero, matching
        :meth:`KnowledgeStore.save_provenances`.
    :param skipped: ``True`` when the article was skipped
        because it already had provenance in the store.
    :param error: Error message if processing failed for
        this specific article; ``None`` on success or
        skip.
    """

    document_id: str
    resolution: ResolutionResult = field(
        default_factory=ResolutionResult
    )
    provenances_saved: int = 0
    skipped: bool = False
    error: str | None = None


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
    """

    run_id: str
    results: tuple[ArticleResult, ...]
    documents_processed: int
    provenances_saved: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Pipeline:
    """Orchestrates detection -> resolution -> provenance.

    :param detector: Implementation of
        :class:`EntityDetector`. Typically a
        :class:`RuleBasedDetector` built from the active
        KG entities.
    :param resolver: Implementation of
        :class:`EntityResolver`. The default
        :class:`AliasResolver` handles unambiguous
        single-candidate mentions; an LLM-based resolver
        can be plugged in later for the ambiguous
        remainder.
    :param store: The :class:`KnowledgeStore` receiving
        provenance rows and tracking ingestion runs.
    :param skip_processed: When ``True`` (the default),
        articles whose ``document_id`` already has any
        provenance row are skipped. Set ``False`` to
        force reprocessing -- callers that need a clean
        slate should delete existing provenance first.

    Example::

        from unstructured_mapping.pipeline import (
            AliasResolver,
            Pipeline,
            RuleBasedDetector,
        )
        detector = RuleBasedDetector(
            store.find_entities_by_status(
                EntityStatus.ACTIVE
            )
        )
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
        )
        result = pipeline.run(articles)
        print(result.provenances_saved)
    """

    def __init__(
        self,
        detector: EntityDetector,
        resolver: EntityResolver,
        store: KnowledgeStore,
        *,
        skip_processed: bool = True,
    ) -> None:
        self._detector = detector
        self._resolver = resolver
        self._store = store
        self._skip_processed = skip_processed

    # -- Public API -----------------------------------------

    def run(
        self, articles: list[Article]
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
        :return: Aggregate result for the run.
        """
        run = IngestionRun()
        self._store.save_run(run)
        logger.info(
            "Pipeline run %s started (%d articles)",
            run.run_id,
            len(articles),
        )
        results: list[ArticleResult] = []
        try:
            for article in articles:
                results.append(
                    self._process_article(
                        article, run.run_id
                    )
                )
        except Exception as exc:  # noqa: BLE001
            doc_count, prov_count = _compute_run_stats(
                results
            )
            self._store.finish_run(
                run.run_id,
                status=RunStatus.FAILED,
                document_count=doc_count,
                entity_count=prov_count,
                error_message=str(exc),
            )
            logger.exception(
                "Pipeline run %s failed", run.run_id
            )
            raise

        doc_count, prov_count = _compute_run_stats(results)
        self._store.finish_run(
            run.run_id,
            status=RunStatus.COMPLETED,
            document_count=doc_count,
            entity_count=prov_count,
        )
        logger.info(
            "Pipeline run %s completed: %d processed, "
            "%d skipped, %d provenances",
            run.run_id,
            doc_count,
            len(results) - doc_count,
            prov_count,
        )
        return PipelineResult(
            run_id=run.run_id,
            results=tuple(results),
            documents_processed=doc_count,
            provenances_saved=prov_count,
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
        return self._process_article(article, run_id)

    # -- Internal helpers -----------------------------------

    def _process_article(
        self,
        article: Article,
        run_id: str | None,
    ) -> ArticleResult:
        doc_id = article.document_id.hex
        if (
            self._skip_processed
            and self._store.has_document_provenance(
                doc_id
            )
        ):
            logger.debug(
                "Skipping already-processed article %s",
                doc_id,
            )
            return ArticleResult(
                document_id=doc_id, skipped=True
            )
        try:
            chunk = Chunk(
                document_id=doc_id,
                chunk_index=0,
                text=article.body,
                section_name=None,
            )
            mentions = self._detector.detect(chunk)
            resolution = self._resolver.resolve(
                chunk, mentions
            )
            detected_at = _utcnow()
            provenances = [
                Provenance(
                    entity_id=rm.entity_id,
                    document_id=doc_id,
                    source=article.source,
                    mention_text=rm.surface_form,
                    context_snippet=rm.context_snippet,
                    detected_at=detected_at,
                    run_id=run_id,
                )
                for rm in resolution.resolved
            ]
            inserted = self._store.save_provenances(
                provenances
            )
            return ArticleResult(
                document_id=doc_id,
                resolution=resolution,
                provenances_saved=inserted,
            )
        except Exception as exc:  # noqa: BLE001
            # Per-article isolation: log and carry on.
            # Pipeline-level errors should be raised by
            # the store directly and propagate out of
            # :meth:`run`.
            logger.exception(
                "Failed to process article %s", doc_id
            )
            return ArticleResult(
                document_id=doc_id,
                error=str(exc),
            )
