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
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityStatus,
    IngestionRun,
    Provenance,
    Relationship,
    RunMetrics,
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
    ExtractedRelationship,
    ResolutionResult,
    ResolvedMention,
)
from unstructured_mapping.pipeline.aggregation import (
    AggregatedOutcome,
    ChunkAggregator,
    ChunkOutcome,
)
from unstructured_mapping.pipeline.segmentation import (
    DocumentSegmenter,
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
        sum(r.relationships_saved for r in results),
    )


@dataclass
class _MetricsAccumulator:
    """Mutable counter accumulated over one pipeline run.

    Lives for the duration of a single :meth:`Pipeline.run`
    call. Finalised into a :class:`RunMetrics` row at the
    end so the aggregated scorecard is available for
    cross-run comparison.
    """

    run_id: str
    started_monotonic: float
    provider_name: str | None = None
    model_name: str | None = None
    chunks_processed: int = 0
    mentions_detected: int = 0
    mentions_resolved_alias: int = 0
    mentions_resolved_llm: int = 0
    llm_resolver_calls: int = 0
    llm_extractor_calls: int = 0
    proposals_saved: int = 0
    relationships_saved: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def finalize(self) -> RunMetrics:
        """Return a frozen snapshot for persistence."""
        return RunMetrics(
            run_id=self.run_id,
            chunks_processed=self.chunks_processed,
            mentions_detected=self.mentions_detected,
            mentions_resolved_alias=(self.mentions_resolved_alias),
            mentions_resolved_llm=(self.mentions_resolved_llm),
            llm_resolver_calls=self.llm_resolver_calls,
            llm_extractor_calls=(self.llm_extractor_calls),
            proposals_saved=self.proposals_saved,
            relationships_saved=(self.relationships_saved),
            provider_name=self.provider_name,
            model_name=self.model_name,
            wall_clock_seconds=(time.monotonic() - self.started_monotonic),
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
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
    resolution: ResolutionResult = field(default_factory=ResolutionResult)
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
        self._detector = detector
        self._resolver = resolver
        self._store = store
        self._llm_resolver = llm_resolver
        self._extractor = extractor
        self._cold_start_discoverer = cold_start_discoverer
        #: Optional chunker. When ``None`` every article
        #: is processed as a single chunk (the legacy
        #: inverted-pyramid behaviour for news). When set
        #: — typically to a ``ResearchSegmenter``,
        #: ``TranscriptSegmenter`` or ``FilingSegmenter``
        #: — each article is split and every chunk flows
        #: through the existing per-chunk stages in turn.
        #: Cold-start mode ignores the segmenter: the LLM
        #: discoverer sees the full article body by
        #: design.
        self._segmenter = segmenter
        #: Cross-chunk aggregator. Stateless; single-chunk
        #: articles produce a no-op aggregation so the
        #: path is uniform.
        self._aggregator = ChunkAggregator()
        self._skip_processed = skip_processed
        #: Metrics accumulator. Re-created at the start of
        #: every :meth:`run` so cross-call counters don't
        #: leak. A placeholder is set here so ad-hoc
        #: :meth:`process_article` calls (which bypass
        #: :meth:`run`) don't crash on the attribute —
        #: they just don't persist a scorecard.
        self._metrics = _MetricsAccumulator(
            run_id="",
            started_monotonic=time.monotonic(),
        )

    # -- Public API -----------------------------------------

    def run(self, articles: list[Article]) -> PipelineResult:
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
        self._metrics = _MetricsAccumulator(
            run_id=run.run_id,
            started_monotonic=time.monotonic(),
            provider_name=self._provider_name(),
            model_name=self._model_name(),
        )
        # Prefetch the idempotency set once rather than
        # hitting SQLite per article: on a 1000-article
        # batch this replaces 1000 queries with one.
        already_processed: set[str] = set()
        if self._skip_processed and articles:
            already_processed = self._store.documents_with_provenance(
                [a.document_id.hex for a in articles]
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
        return self._process_article(article, run_id)

    # -- Internal helpers -----------------------------------

    def _provider_name(self) -> str | None:
        """Read the LLM provider's identifier, if any.

        Returns whichever of the resolver or extractor has
        a backing provider (the first hit wins — in
        practice both are configured with the same
        provider). ``None`` when no LLM stage is wired.
        """
        for stage in (
            self._llm_resolver,
            self._extractor,
            self._cold_start_discoverer,
        ):
            provider = getattr(stage, "_provider", None)
            name = getattr(provider, "provider_name", None)
            if name is not None:
                return name
        return None

    def _model_name(self) -> str | None:
        for stage in (
            self._llm_resolver,
            self._extractor,
            self._cold_start_discoverer,
        ):
            provider = getattr(stage, "_provider", None)
            name = getattr(provider, "model_name", None)
            if name is not None:
                return name
        return None

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
            return ArticleResult(document_id=doc_id, skipped=True)
        try:
            if self._cold_start_discoverer is not None:
                # Cold-start sees the whole article body:
                # the LLM proposes entities from scratch,
                # so chunking would just split prompts
                # without benefit.
                full_chunk = Chunk(
                    document_id=doc_id,
                    chunk_index=0,
                    text=article.body,
                    section_name=None,
                )
                return self._process_cold_start(full_chunk, article, run_id)

            chunks = self._chunks_for(article, doc_id)
            if not chunks:
                return ArticleResult(document_id=doc_id)

            # Document-level alias pre-scan: run the rule-
            # based detector over the whole article body
            # once and hand every resolved candidate to
            # every chunk's resolver. Solves long-range
            # coreference — chunk 5 saying "the company"
            # still sees Apple from chunk 1 in its KG
            # context window. Only runs when the pipeline
            # is actually chunking (>1 chunk); a single-
            # chunk article is already self-contained.
            prescan = (
                self._document_prescan(article, doc_id)
                if len(chunks) > 1
                else ()
            )

            # Thread resolved entities forward through
            # the chunk sequence so each chunk's LLM
            # resolver sees what earlier chunks pinned
            # down. Chunk 5 can still coreference an
            # entity the LLM proposed in chunk 2 even
            # though it is not in the KG yet — the KG
            # pre-scan only covers existing entities.
            outcomes: list[ChunkOutcome] = []
            running_entities: list[ResolvedMention] = []
            for chunk in chunks:
                outcome = self._process_chunk(
                    chunk,
                    article,
                    run_id,
                    prescan,
                    prev_entities=tuple(running_entities),
                )
                outcomes.append(outcome)
                running_entities.extend(outcome.resolution.resolved)
            aggregated = self._aggregator.aggregate(outcomes)
            # One transaction per article: all provenance,
            # proposal-entity, and relationship writes
            # share one COMMIT. Aggregation already
            # dedupes within the article; the DB layer
            # handles cross-article dedup.
            with self._store.transaction():
                saved = self._persist_aggregated(aggregated, article, run_id)
            self._metrics.proposals_saved += saved[1]
            self._metrics.relationships_saved += saved[2]
            return ArticleResult(
                document_id=doc_id,
                resolution=aggregated.resolution,
                provenances_saved=saved[0],
                proposals_saved=saved[1],
                relationships_saved=saved[2],
            )
        except Exception as exc:  # noqa: BLE001
            # Per-article isolation: log and carry on.
            # Pipeline-level errors should be raised by
            # the store directly and propagate out of
            # :meth:`run`.
            logger.exception("Failed to process article %s", doc_id)
            return ArticleResult(
                document_id=doc_id,
                error=str(exc),
            )

    def _document_prescan(
        self, article: Article, doc_id: str
    ) -> tuple[Entity, ...]:
        """Run the detector over the full article body.

        Returns every KG entity whose alias the rule-based
        detector matched anywhere in the document. These
        ride along with each chunk's LLM resolver call so
        a mention like "the company" in chunk 5 can be
        resolved against Apple when Apple's name appeared
        only in chunk 1.

        Implementation detail: we reuse the same
        :class:`EntityDetector` — the alias trie is the
        cheapest pre-scan available (pure string work, no
        LLM call) and it already knows every alias the
        detector knows, so the pre-scan and the per-chunk
        detection stay consistent.
        """
        full_chunk = Chunk(
            document_id=doc_id,
            chunk_index=0,
            text=article.body,
            section_name=None,
        )
        mentions = self._detector.detect(full_chunk)
        seen: set[str] = set()
        ids: list[str] = []
        for mention in mentions:
            for eid in mention.candidate_ids:
                if eid in seen:
                    continue
                seen.add(eid)
                ids.append(eid)
        if not ids:
            return ()
        found = self._store.get_entities(ids)
        return tuple(found[eid] for eid in ids if eid in found)

    def _chunks_for(self, article: Article, doc_id: str) -> list[Chunk]:
        """Return the chunks to process for this article.

        When no segmenter is configured the article body
        becomes a single chunk (preserving the legacy
        behaviour for news). When a segmenter is set it
        owns the split.
        """
        if self._segmenter is None:
            return [
                Chunk(
                    document_id=doc_id,
                    chunk_index=0,
                    text=article.body,
                    section_name=None,
                )
            ]
        return self._segmenter.segment(doc_id, article.body)

    def _process_chunk(
        self,
        chunk: Chunk,
        article: Article,
        run_id: str | None,
        prescan: tuple[Entity, ...] = (),
        *,
        prev_entities: tuple[ResolvedMention, ...] = (),
    ) -> ChunkOutcome:
        """Run detection / resolution / extraction on one
        chunk and return its outputs.

        No KG writes happen here — the outputs are handed
        to :class:`ChunkAggregator` and only persisted
        once, after cross-chunk dedup. Empty chunks (the
        transcript Q&A divider, e.g.) return an empty
        outcome so the caller can loop uniformly.

        :param prescan: Document-level alias pre-scan
            candidates passed through to the LLM
            resolver's KG context window for cross-chunk
            coreference. Ignored when no LLM resolver is
            configured.
        :param prev_entities: Running entity header —
            resolved mentions accumulated from earlier
            chunks in the same article. Forwarded to the
            LLM resolver so a later chunk's prompt knows
            what earlier chunks resolved to.
        """
        if not chunk.text.strip():
            return ChunkOutcome()

        doc_id = chunk.document_id
        mentions = self._detector.detect(chunk)
        resolution = self._resolver.resolve(chunk, mentions)

        self._metrics.chunks_processed += 1
        self._metrics.mentions_detected += len(mentions)
        self._metrics.mentions_resolved_alias += len(resolution.resolved)

        proposals: tuple[EntityProposal, ...] = ()
        if self._llm_resolver is not None and resolution.unresolved:
            llm_result = self._llm_resolver.resolve(
                chunk,
                resolution.unresolved,
                extra_candidates=prescan,
                prev_entities=prev_entities,
            )
            proposals = self._llm_resolver.proposals
            self._metrics.llm_resolver_calls += 1
            self._metrics.mentions_resolved_llm += len(llm_result.resolved)
            res_usage = getattr(
                self._llm_resolver,
                "last_token_usage",
                None,
            )
            if res_usage is not None:
                self._metrics.input_tokens += res_usage.input_tokens
                self._metrics.output_tokens += res_usage.output_tokens
            resolution = ResolutionResult(
                resolved=(resolution.resolved + llm_result.resolved),
            )

        detected_at = _utcnow()
        provenances = tuple(
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
        )

        extracted: tuple[ExtractedRelationship, ...] = ()
        if self._extractor is not None and resolution.resolved:
            result = self._extractor.extract(chunk, resolution.resolved)
            extracted = result.relationships
            self._metrics.llm_extractor_calls += 1
            ext_usage = getattr(
                self._extractor,
                "last_token_usage",
                None,
            )
            if ext_usage is not None:
                self._metrics.input_tokens += ext_usage.input_tokens
                self._metrics.output_tokens += ext_usage.output_tokens

        return ChunkOutcome(
            resolution=resolution,
            provenances=provenances,
            proposals=proposals,
            relationships=extracted,
        )

    def _persist_aggregated(
        self,
        aggregated: AggregatedOutcome,
        article: Article,
        run_id: str | None,
    ) -> tuple[int, int, int]:
        """Persist the aggregated outputs of one article.

        :return: ``(provenances_saved, proposals_saved,
            relationships_saved)``.
        """
        detected_at = _utcnow()
        prov_saved = (
            self._store.save_provenances(list(aggregated.provenances))
            if aggregated.provenances
            else 0
        )
        proposals_saved = self._persist_proposals(
            aggregated.proposals,
            article.document_id.hex,
            article.source,
            detected_at,
            run_id,
        )
        rels_saved = self._persist_relationships(
            aggregated.relationships,
            article.document_id.hex,
            detected_at,
            run_id,
        )
        return prov_saved, proposals_saved, rels_saved

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
        proposals = self._cold_start_discoverer.discover(chunk)
        cs_usage = getattr(
            self._cold_start_discoverer,
            "last_token_usage",
            None,
        )
        if cs_usage is not None:
            self._metrics.input_tokens += cs_usage.input_tokens
            self._metrics.output_tokens += cs_usage.output_tokens
        detected_at = _utcnow()
        saved = self._persist_proposals(
            proposals,
            chunk.document_id,
            article.source,
            detected_at,
            run_id,
        )
        # Cold-start bypasses the chunk loop; record a
        # single chunk and the saved count so the
        # scorecard still reflects the work done.
        self._metrics.chunks_processed += 1
        self._metrics.proposals_saved += saved
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

    def _persist_proposals(
        self,
        proposals: tuple[EntityProposal, ...],
        doc_id: str,
        source: str,
        detected_at: datetime,
        run_id: str | None,
    ) -> int:
        """Create new entities from aggregated proposals.

        The aggregator already deduped by name+type; each
        proposal here becomes a single :class:`Entity`
        plus a :class:`Provenance` tying it to the source
        article.
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
                        mention_text=(proposal.canonical_name),
                        context_snippet=(proposal.context_snippet),
                        detected_at=detected_at,
                        run_id=run_id,
                    )
                ]
            )
            count += 1
            logger.info(
                "Created entity %s (%s) from LLM proposal",
                entity.canonical_name,
                entity.entity_id,
            )
        return count

    def _persist_relationships(
        self,
        extracted: tuple[ExtractedRelationship, ...],
        doc_id: str,
        detected_at: datetime,
        run_id: str | None,
    ) -> int:
        """Persist aggregated relationships to the KG.

        Converts each :class:`ExtractedRelationship`
        (already cross-chunk deduped) into a
        :class:`Relationship` tied to the source article
        and run, then bulk-inserts.
        """
        if not extracted:
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
                confidence=er.confidence,
            )
            for er in extracted
        ]
        count = self._store.save_relationships(relationships)
        logger.info(
            "Persisted %d relationships from %s",
            count,
            doc_id,
        )
        return count
