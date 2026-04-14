"""Pipeline orchestration — article to KG records.

Wires the detection, resolution, extraction, and
persistence stages into a single callable
:class:`Pipeline`. Given an ``Article`` (from
:mod:`web_scraping`), the pipeline produces
``Provenance`` and ``Relationship`` records in the
:class:`KnowledgeStore` and tracks the execution in an
``IngestionRun``.

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
from dataclasses import dataclass, field
from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityStatus,
    IngestionRun,
    Provenance,
    Relationship,
    RunStatus,
)
from unstructured_mapping.knowledge_graph.storage import (
    KnowledgeStore,
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
from unstructured_mapping.pipeline.models import (
    Chunk,
    EntityProposal,
    ResolutionResult,
)
from unstructured_mapping.pipeline.resolution import (
    EntityResolver,
    LLMEntityResolver,
)
from unstructured_mapping.web_scraping.models import Article

logger = logging.getLogger(__name__)


def _compute_run_stats(
    results: list["ArticleResult"],
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
        sum(
            r.relationships_saved for r in results
        ),
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
        :meth:`KnowledgeStore.save_provenances`. In
        cold-start mode this mirrors ``proposals_saved``
        since each proposal writes one provenance row.
    :param proposals_saved: Number of new entities
        created from LLM proposals. Populated by the
        cascade LLM resolver in normal mode, and by the
        discoverer in cold-start mode. Zero when neither
        is configured.
    :param relationships_saved: Number of relationship
        rows inserted by relationship extraction. Zero
        when no extractor is configured.
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
    proposals_saved: int = 0
    relationships_saved: int = 0
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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
        extractor: (
            RelationshipExtractor | None
        ) = None,
        cold_start_discoverer: (
            ColdStartEntityDiscoverer | None
        ) = None,
        skip_processed: bool = True,
    ) -> None:
        self._detector = detector
        self._resolver = resolver
        self._store = store
        self._llm_resolver = llm_resolver
        self._extractor = extractor
        self._cold_start_discoverer = (
            cold_start_discoverer
        )
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
        # Prefetch the idempotency set once rather than
        # hitting SQLite per article: on a 1000-article
        # batch this replaces 1000 queries with one.
        already_processed: set[str] = set()
        if self._skip_processed and articles:
            already_processed = (
                self._store.documents_with_provenance(
                    [a.document_id.hex for a in articles]
                )
            )
        results: list[ArticleResult] = []
        try:
            for article in articles:
                results.append(
                    self._process_article(
                        article,
                        run.run_id,
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
            logger.exception(
                "Pipeline run %s failed", run.run_id
            )
            raise

        stats = _compute_run_stats(results)
        doc_count, prov_count, prop_count, rel_count = (
            stats
        )
        self._store.finish_run(
            run.run_id,
            status=RunStatus.COMPLETED,
            document_count=doc_count,
            entity_count=prov_count,
            relationship_count=rel_count,
        )
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
        return self._process_article(article, run_id)

    # -- Internal helpers -----------------------------------

    def _is_processed(
        self,
        doc_id: str,
        already_processed: set[str] | None,
    ) -> bool:
        """Resolve the idempotency check.

        When :meth:`run` pre-fetched a batch set, use it
        (O(1) lookup). For ad-hoc single-article calls via
        :meth:`process_article` there is no batch, so fall
        back to the per-row store query.
        """
        if already_processed is not None:
            return doc_id in already_processed
        return self._store.has_document_provenance(doc_id)

    def _process_article(
        self,
        article: Article,
        run_id: str | None,
        *,
        already_processed: set[str] | None = None,
    ) -> ArticleResult:
        doc_id = article.document_id.hex
        if self._skip_processed and self._is_processed(
            doc_id, already_processed
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
            if self._cold_start_discoverer is not None:
                return self._process_cold_start(
                    chunk, article, run_id
                )
            mentions = self._detector.detect(chunk)
            resolution = self._resolver.resolve(
                chunk, mentions
            )

            # Cascade: pass unresolved to the LLM.
            llm_resolved: tuple = ()
            proposals: tuple[EntityProposal, ...] = ()
            if (
                self._llm_resolver is not None
                and resolution.unresolved
            ):
                llm_result = self._llm_resolver.resolve(
                    chunk, resolution.unresolved
                )
                llm_resolved = llm_result.resolved
                proposals = self._llm_resolver.proposals
                resolution = ResolutionResult(
                    resolved=(
                        resolution.resolved
                        + llm_resolved
                    ),
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

            # Persist LLM entity proposals.
            saved_proposals = self._save_proposals(
                proposals, doc_id, article.source,
                detected_at, run_id,
            )

            # Pass 2: relationship extraction.
            saved_rels = self._extract_relationships(
                chunk,
                resolution.resolved,
                proposals,
                doc_id,
                detected_at,
                run_id,
            )

            return ArticleResult(
                document_id=doc_id,
                resolution=resolution,
                provenances_saved=inserted,
                proposals_saved=saved_proposals,
                relationships_saved=saved_rels,
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

    def _process_cold_start(
        self,
        chunk: Chunk,
        article: Article,
        run_id: str | None,
    ) -> ArticleResult:
        """Bootstrap entities from raw text via the LLM.

        Bypasses detection and resolution entirely. The
        configured :class:`ColdStartEntityDiscoverer`
        proposes entities directly from the article body;
        each proposal becomes a new entity plus a
        provenance row. Relationship extraction is
        skipped in cold-start mode — subsequent runs
        with the normal pipeline will detect the new
        entities and extract relationships from there.

        :return: Per-article result with
            ``proposals_saved`` reflecting new entities
            created. ``provenances_saved`` mirrors that
            count since one provenance row is created
            per proposal.
        """
        assert (
            self._cold_start_discoverer is not None
        )  # caller guarantees this
        proposals = (
            self._cold_start_discoverer.discover(chunk)
        )
        detected_at = _utcnow()
        saved = self._save_proposals(
            proposals,
            chunk.document_id,
            article.source,
            detected_at,
            run_id,
        )
        logger.info(
            "Cold-start discovered %d entities from %s",
            saved,
            chunk.document_id,
        )
        return ArticleResult(
            document_id=chunk.document_id,
            resolution=ResolutionResult(),
            provenances_saved=saved,
            proposals_saved=saved,
            relationships_saved=0,
        )

    def _save_proposals(
        self,
        proposals: tuple[EntityProposal, ...],
        doc_id: str,
        source: str,
        detected_at: datetime,
        run_id: str | None,
    ) -> int:
        """Persist LLM entity proposals as new entities.

        Creates an :class:`Entity` for each proposal and
        a :class:`Provenance` linking it to the source
        article.

        :return: Number of entities created.
        """
        if not proposals:
            return 0
        count = 0
        for proposal in proposals:
            entity = Entity(
                canonical_name=proposal.canonical_name,
                entity_type=proposal.entity_type,
                subtype=proposal.subtype,
                description=proposal.description,
                aliases=proposal.aliases,
                status=EntityStatus.ACTIVE,
            )
            self._store.save_entity(
                entity,
                reason="proposed by LLM",
            )
            self._store.save_provenances(
                [
                    Provenance(
                        entity_id=entity.entity_id,
                        document_id=doc_id,
                        source=source,
                        mention_text=(
                            proposal.canonical_name
                        ),
                        context_snippet=(
                            proposal.context_snippet
                        ),
                        detected_at=detected_at,
                        run_id=run_id,
                    )
                ]
            )
            count += 1
            logger.info(
                "Created entity %s (%s) from LLM "
                "proposal",
                entity.canonical_name,
                entity.entity_id,
            )
        return count

    def _extract_relationships(
        self,
        chunk: Chunk,
        resolved: tuple,
        proposals: tuple[EntityProposal, ...],
        doc_id: str,
        detected_at: datetime,
        run_id: str | None,
    ) -> int:
        """Run pass 2 and persist extracted relationships.

        Calls the relationship extractor (if configured)
        with the resolved entities, converts
        ``ExtractedRelationship`` objects to
        ``Relationship`` records, and bulk-inserts them
        into the KG.

        :return: Number of relationships persisted.
        """
        if self._extractor is None:
            return 0
        if not resolved:
            return 0

        result = self._extractor.extract(
            chunk, resolved
        )
        if not result.relationships:
            return 0

        relationships = [
            Relationship(
                source_id=er.source_id,
                target_id=er.target_id,
                relation_type=er.relation_type,
                description=er.context_snippet,
                qualifier_id=er.qualifier_id,
                valid_from=er.valid_from,
                valid_until=er.valid_until,
                document_id=doc_id,
                discovered_at=detected_at,
                run_id=run_id,
            )
            for er in result.relationships
        ]
        count = self._store.save_relationships(
            relationships
        )
        logger.info(
            "Extracted %d relationships from %s",
            count,
            doc_id,
        )
        return count
