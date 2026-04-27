"""Per-article processing stages.

Encapsulates detection / resolution / extraction /
persistence for a single article and the metrics
accumulated over those stages. Kept separate from
:mod:`orchestrator` so the per-article logic can be
developed and tested in isolation from batch-level
run tracking in :class:`Pipeline`.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityStatus,
    Provenance,
    Relationship,
    RunMetrics,
)
from unstructured_mapping.knowledge_graph.storage import (
    KnowledgeStore,
)
from unstructured_mapping.pipeline.aggregation import (
    AggregatedOutcome,
    ChunkAggregator,
    ChunkOutcome,
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
from unstructured_mapping.pipeline.resolution import (
    EntityResolver,
    LLMEntityResolver,
)
from unstructured_mapping.pipeline.segmentation import (
    DocumentSegmenter,
)
from unstructured_mapping.web_scraping.models import Article

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


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


class ArticleProcessor:
    """Per-article detection / resolution / extraction.

    Owns all stages that operate on a single article:
    chunking, detection, alias and LLM resolution,
    relationship extraction, and persistence. Metrics
    are accumulated into a caller-supplied
    :class:`_MetricsAccumulator` so one accumulator can
    span an entire batch without state living here.

    :param detector: Entity detector implementation.
    :param resolver: Primary entity resolver.
    :param store: KG store receiving provenance /
        relationship writes.
    :param llm_resolver: Optional LLM cascade resolver.
    :param extractor: Optional relationship extractor.
    :param cold_start_discoverer: Optional cold-start
        discoverer; enables cold-start mode when set.
    :param segmenter: Optional document segmenter; when
        ``None`` each article is treated as one chunk.
    :param skip_processed: When ``True`` articles
        already having provenance are skipped.
    """

    def __init__(
        self,
        detector: EntityDetector,
        resolver: EntityResolver,
        store: KnowledgeStore,
        *,
        llm_resolver: LLMEntityResolver | None = None,
        extractor: RelationshipExtractor | None = None,
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

    @property
    def skip_processed(self) -> bool:
        return self._skip_processed

    @property
    def provider_name(self) -> str | None:
        """LLM provider identifier from any wired stage."""
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

    @property
    def model_name(self) -> str | None:
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

    def process_article(
        self,
        article: Article,
        run_id: str | None,
        metrics: _MetricsAccumulator,
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
                return self._process_cold_start(
                    full_chunk, article, run_id, metrics
                )

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
                    metrics=metrics,
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
            metrics.proposals_saved += saved[1]
            metrics.relationships_saved += saved[2]
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
            # :meth:`Pipeline.run`.
            logger.exception("Failed to process article %s", doc_id)
            # Persist the failure so a resumed run can
            # re-queue just the crashed articles via
            # :meth:`KnowledgeStore.find_failed_document_ids`
            # instead of burning LLM tokens on the whole
            # batch again. ``run_id`` is ``None`` in
            # single-article test drivers (e.g. preview);
            # skip the write in that case — there is no
            # run to attribute the failure to.
            if run_id is not None:
                try:
                    self._store.save_article_failure(run_id, doc_id, str(exc))
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "Failed to record article_failures "
                        "row for %s in run %s",
                        doc_id,
                        run_id,
                    )
            return ArticleResult(
                document_id=doc_id,
                error=str(exc),
            )

    def _is_processed(
        self,
        doc_id: str,
        already_processed: set[str] | None,
    ) -> bool:
        """Resolve the idempotency check.

        When :meth:`Pipeline.run` pre-fetched a batch
        set, use it (O(1) lookup). For ad-hoc single-
        article calls there is no batch, so fall back to
        the per-row store query.
        """
        if already_processed is not None:
            return doc_id in already_processed
        return self._store.has_document_provenance(doc_id)

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
        metrics: _MetricsAccumulator,
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
        :param metrics: Accumulator to update in place.
        """
        if not chunk.text.strip():
            return ChunkOutcome()

        doc_id = chunk.document_id
        mentions = self._detector.detect(chunk)
        resolution = self._resolver.resolve(chunk, mentions)

        metrics.chunks_processed += 1
        metrics.mentions_detected += len(mentions)
        metrics.mentions_resolved_alias += len(resolution.resolved)

        proposals: tuple[EntityProposal, ...] = ()
        if self._llm_resolver is not None and (resolution.unresolved):
            llm_result = self._llm_resolver.resolve(
                chunk,
                resolution.unresolved,
                extra_candidates=prescan,
                prev_entities=prev_entities,
            )
            proposals = self._llm_resolver.proposals
            metrics.llm_resolver_calls += 1
            metrics.mentions_resolved_llm += len(llm_result.resolved)
            res_usage = getattr(
                self._llm_resolver,
                "last_token_usage",
                None,
            )
            if res_usage is not None:
                metrics.input_tokens += res_usage.input_tokens
                metrics.output_tokens += res_usage.output_tokens
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
        if self._extractor is not None and (resolution.resolved):
            result = self._extractor.extract(chunk, resolution.resolved)
            extracted = result.relationships
            metrics.llm_extractor_calls += 1
            ext_usage = getattr(
                self._extractor,
                "last_token_usage",
                None,
            )
            if ext_usage is not None:
                metrics.input_tokens += ext_usage.input_tokens
                metrics.output_tokens += ext_usage.output_tokens

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

        All writes run inside a single
        ``store.transaction()`` so one article commits
        once — previously fired up to 2N+2 COMMITs (one
        per ``save_entity``/``save_provenances`` call
        inside the proposal loop, plus the relationship
        batch).

        :return: ``(provenances_saved, proposals_saved,
            relationships_saved)``.
        """
        detected_at = _utcnow()
        with self._store.transaction():
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
        metrics: _MetricsAccumulator,
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
            metrics.input_tokens += cs_usage.input_tokens
            metrics.output_tokens += cs_usage.output_tokens
        detected_at = _utcnow()
        with self._store.transaction():
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
        metrics.chunks_processed += 1
        metrics.proposals_saved += saved
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
        article. All provenance rows are accumulated and
        written in a single ``save_provenances`` call so
        large proposal batches avoid N separate
        executemany round-trips.
        """
        if not proposals:
            return 0
        provenances: list[Provenance] = []
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
            provenances.append(
                Provenance(
                    entity_id=entity.entity_id,
                    document_id=doc_id,
                    source=source,
                    mention_text=proposal.canonical_name,
                    context_snippet=(proposal.context_snippet),
                    detected_at=detected_at,
                    run_id=run_id,
                )
            )
            logger.info(
                "Created entity %s (%s) from LLM proposal",
                entity.canonical_name,
                entity.entity_id,
            )
        self._store.save_provenances(provenances)
        return len(provenances)

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


__all__ = [
    "_MetricsAccumulator",
    "ArticleProcessor",
    "ArticleResult",
]
