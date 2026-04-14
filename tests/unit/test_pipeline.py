"""Tests for the pipeline orchestrator."""

import json

import pytest

from tests.unit.conftest import make_article, make_org
from unstructured_mapping.knowledge_graph import (
    EntityType,
    KnowledgeStore,
    Provenance,
    RunStatus,
)
from unstructured_mapping.pipeline import (
    AliasResolver,
    ArticleResult,
    LLMEntityResolver,
    Pipeline,
    PipelineResult,
    RuleBasedDetector,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMProvider,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    ExtractedRelationship,
    ExtractionResult,
    Mention,
    ResolutionResult,
    ResolvedMention,
)
from unstructured_mapping.pipeline.detection import (
    EntityDetector,
)
from unstructured_mapping.pipeline.extraction import (
    RelationshipExtractor,
)
from unstructured_mapping.pipeline.resolution import (
    EntityResolver,
)


class _StubDetector(EntityDetector):
    """Returns preset mentions regardless of chunk."""

    def __init__(self, mentions: tuple[Mention, ...]):
        self._mentions = mentions

    def detect(self, chunk: Chunk) -> tuple[Mention, ...]:
        return self._mentions


class _StubResolver(EntityResolver):
    """Returns a preset ResolutionResult."""

    def __init__(self, result: ResolutionResult):
        self._result = result

    def resolve(
        self,
        chunk: Chunk,
        mentions: tuple[Mention, ...],
    ) -> ResolutionResult:
        return self._result


class _ExplodingResolver(EntityResolver):
    """Raises on every call — used for isolation tests."""

    def resolve(
        self,
        chunk: Chunk,
        mentions: tuple[Mention, ...],
    ) -> ResolutionResult:
        raise RuntimeError("boom")


# -- ArticleResult / PipelineResult models --


def test_article_result_defaults():
    r = ArticleResult(document_id="d1")
    assert r.provenances_saved == 0
    assert r.skipped is False
    assert r.error is None
    assert r.resolution.resolved == ()


def test_article_result_frozen():
    r = ArticleResult(document_id="d1")
    with pytest.raises(AttributeError):
        r.document_id = "d2"  # type: ignore[misc]


# -- Pipeline.run: happy path --


def test_pipeline_run_end_to_end(tmp_path):
    """Real detector + resolver + store wiring works."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    msft = make_org("Microsoft", aliases=("Microsoft",))
    article = make_article(
        body=(
            "Apple reported earnings. "
            "Microsoft also reported."
        ),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_entity(msft)
        detector = RuleBasedDetector([apple, msft])
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
        )
        result = pipeline.run([article])
        run = store.get_run(result.run_id)
        prov_apple = store.get_provenance(apple.entity_id)
        prov_msft = store.get_provenance(msft.entity_id)

    assert isinstance(result, PipelineResult)
    assert result.documents_processed == 1
    assert result.provenances_saved == 2
    assert len(prov_apple) == 1
    assert len(prov_msft) == 1
    # Provenance is attributed to the run.
    assert prov_apple[0].run_id == result.run_id
    assert prov_apple[0].document_id == (
        article.document_id.hex
    )
    assert prov_apple[0].source == "bbc"
    assert "Apple" in prov_apple[0].context_snippet
    # Run is finalized.
    assert run is not None
    assert run.status == RunStatus.COMPLETED
    assert run.document_count == 1
    assert run.entity_count == 2
    assert run.finished_at is not None


def test_pipeline_with_segmenter_processes_each_chunk(
    tmp_path,
):
    """A configured segmenter splits every article, and
    per-chunk detection + resolution + provenance happens
    independently. Demonstrates the v0.39.1 wiring: the
    ``ResearchSegmenter`` fires on an article with
    markdown headings, each section becomes its own
    chunk, and every chunk contributes provenance."""
    from unstructured_mapping.pipeline.segmentation import (
        ResearchSegmenter,
    )

    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    msft = make_org("Microsoft", aliases=("Microsoft",))
    article = make_article(
        body=(
            "## Executive Summary\n"
            "Apple leads the pack.\n\n"
            "## Risks\n"
            "Microsoft competition intensifies."
        ),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_entity(msft)
        pipeline = Pipeline(
            detector=RuleBasedDetector([apple, msft]),
            resolver=AliasResolver(),
            store=store,
            segmenter=ResearchSegmenter(),
        )
        result = pipeline.run([article])
        prov_apple = store.get_provenance(apple.entity_id)
        prov_msft = store.get_provenance(msft.entity_id)

    assert result.documents_processed == 1
    # Two sections, each contributes one entity
    # provenance — Apple in the Summary section,
    # Microsoft in the Risks section.
    assert result.provenances_saved == 2
    assert len(prov_apple) == 1
    assert len(prov_msft) == 1


def test_pipeline_aggregator_dedupes_duplicate_proposals(
    tmp_path,
):
    """Two segmenter chunks that each surface the same
    new entity must produce one KG entity, not two.
    Uses a stub LLM resolver that returns an
    `EntityProposal` for every unresolved mention."""
    from unstructured_mapping.knowledge_graph.models import (
        EntityType,
    )
    from unstructured_mapping.pipeline.models import (
        EntityProposal,
        Mention,
        ResolutionResult,
    )
    from unstructured_mapping.pipeline.segmentation import (
        ResearchSegmenter,
    )

    class StubLLMResolver:
        """Minimal LLMEntityResolver replacement that
        proposes a new entity for every unresolved
        mention seen. No network, no prompts — just
        exercises the cascade path."""

        def __init__(self):
            self.proposals: tuple = ()

        def resolve(
            self, chunk, unresolved, *, extra_candidates=()
        ):
            props = tuple(
                EntityProposal(
                    canonical_name="NewCo",
                    entity_type=EntityType.ORGANIZATION,
                    description=(
                        f"Seen in {chunk.section_name}"
                    ),
                    context_snippet="NewCo",
                )
                for _ in unresolved
            )
            self.proposals = props
            return ResolutionResult(
                resolved=(),
                unresolved=(),
            )

    db = tmp_path / "kg.db"

    class AlwaysUnresolvedDetector:
        """Emits one Mention per chunk with zero
        candidate ids, so the cascade path always fires."""

        def detect(self, chunk):
            return (
                Mention(
                    surface_form="NewCo",
                    span_start=0,
                    span_end=5,
                    candidate_ids=(),
                ),
            )

    class PassthroughResolver:
        def resolve(self, chunk, mentions):
            return ResolutionResult(
                resolved=(),
                unresolved=mentions,
            )

    article = make_article(
        body=(
            "## Summary\n"
            "NewCo is a new startup.\n\n"
            "## Risks\n"
            "NewCo faces competition."
        ),
    )
    with KnowledgeStore(db_path=db) as store:
        pipeline = Pipeline(
            detector=AlwaysUnresolvedDetector(),
            resolver=PassthroughResolver(),
            store=store,
            llm_resolver=StubLLMResolver(),
            segmenter=ResearchSegmenter(),
        )
        result = pipeline.run([article])
        matches = store.find_by_name("NewCo")

    # Two chunks → two proposals → aggregator dedupes
    # to a single new entity.
    assert result.results[0].proposals_saved == 1
    assert len(matches) == 1


def test_pipeline_alias_prescan_pulls_full_body_matches(
    tmp_path,
):
    """End-to-end proof that when a downstream chunk has
    no detector hit but the full body does, the pre-scan
    candidate is still surfaced to the LLM resolver."""
    from unstructured_mapping.pipeline.models import (
        Mention,
        ResolutionResult,
    )
    from unstructured_mapping.pipeline.segmentation import (
        ResearchSegmenter,
    )

    apple = make_org("Apple", aliases=("Apple",))

    extra_seen_per_chunk: list[tuple] = []

    class Recorder:
        def __init__(self):
            self.proposals: tuple = ()

        def resolve(
            self,
            chunk,
            unresolved,
            *,
            extra_candidates=(),
        ):
            extra_seen_per_chunk.append(
                (
                    chunk.section_name,
                    tuple(
                        e.canonical_name
                        for e in extra_candidates
                    ),
                )
            )
            return ResolutionResult(resolved=(), unresolved=())

    class HybridDetector:
        """Rule-based for the pre-scan path; stub for the
        per-chunk path so the Risks chunk yields an
        unresolved mention without candidate_ids."""

        def __init__(self, full_detector):
            self._full = full_detector

        def detect(self, chunk):
            # Full-body pre-scan (chunk_index == 0 and
            # section_name is None): use the rule-based
            # detector that knows Apple.
            if chunk.section_name is None:
                return self._full.detect(chunk)
            if "Apple" in chunk.text:
                return self._full.detect(chunk)
            return (
                Mention(
                    surface_form="the company",
                    span_start=0,
                    span_end=11,
                    candidate_ids=(),
                ),
            )

    class EmptyResolver:
        def resolve(self, chunk, mentions):
            return ResolutionResult(
                resolved=(),
                unresolved=mentions,
            )

    db = tmp_path / "kg.db"
    article = make_article(
        body=(
            "## Summary\n"
            "Apple introduced a new product.\n\n"
            "## Risks\n"
            "The company faces supplier concentration."
        ),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        full_detector = RuleBasedDetector([apple])
        pipeline = Pipeline(
            detector=HybridDetector(full_detector),
            resolver=EmptyResolver(),
            store=store,
            llm_resolver=Recorder(),
            segmenter=ResearchSegmenter(),
        )
        pipeline.run([article])

    risks = [
        extras
        for section, extras in extra_seen_per_chunk
        if section == "Risks"
    ]
    assert len(risks) == 1
    assert "Apple" in risks[0]


def test_pipeline_without_segmenter_preserves_legacy_behaviour(
    tmp_path,
):
    """With no segmenter the pipeline still emits one
    chunk per article — news-path callers see no change."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    article = make_article(
        body=(
            "## A heading.\n"
            "Apple dominated the quarter."
        ),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        pipeline = Pipeline(
            detector=RuleBasedDetector([apple]),
            resolver=AliasResolver(),
            store=store,
        )
        # No segmenter: the markdown heading is ignored,
        # the whole body is one chunk, one provenance is
        # written.
        result = pipeline.run([article])
    assert result.provenances_saved == 1


def test_pipeline_run_multiple_articles(tmp_path):
    """Counts aggregate across articles."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    articles = [
        make_article(body="Apple rose.", title=f"a{i}")
        for i in range(3)
    ]
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        pipeline = Pipeline(
            detector=RuleBasedDetector([apple]),
            resolver=AliasResolver(),
            store=store,
        )
        result = pipeline.run(articles)

    assert result.documents_processed == 3
    assert result.provenances_saved == 3
    assert len(result.results) == 3
    assert all(
        r.provenances_saved == 1 for r in result.results
    )


def test_pipeline_run_no_mentions(tmp_path):
    """Articles without matches still succeed."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    article = make_article(body="Nothing interesting here.")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        pipeline = Pipeline(
            detector=RuleBasedDetector([apple]),
            resolver=AliasResolver(),
            store=store,
        )
        result = pipeline.run([article])
        run = store.get_run(result.run_id)

    assert result.documents_processed == 1
    assert result.provenances_saved == 0
    assert run is not None
    assert run.status == RunStatus.COMPLETED


def test_pipeline_run_empty_list(tmp_path):
    """Empty input still opens/closes a run cleanly."""
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        pipeline = Pipeline(
            detector=_StubDetector(()),
            resolver=AliasResolver(),
            store=store,
        )
        result = pipeline.run([])
        run = store.get_run(result.run_id)

    assert result.documents_processed == 0
    assert result.provenances_saved == 0
    assert run is not None
    assert run.status == RunStatus.COMPLETED


# -- Pipeline.run: skip already-processed --


def test_pipeline_skips_processed_articles(tmp_path):
    """Articles with existing provenance are skipped."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    article = make_article(body="Apple rose.")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        # Pre-seed provenance as if a prior run saw it.
        store.save_provenance(Provenance(
            entity_id=apple.entity_id,
            document_id=article.document_id.hex,
            source="bbc",
            mention_text="Apple",
            context_snippet="ctx",
        ))
        pipeline = Pipeline(
            detector=RuleBasedDetector([apple]),
            resolver=AliasResolver(),
            store=store,
        )
        result = pipeline.run([article])
        prov = store.get_provenance(apple.entity_id)

    # Article skipped — no new provenance.
    assert result.documents_processed == 0
    assert result.provenances_saved == 0
    assert result.results[0].skipped is True
    # Original provenance untouched.
    assert len(prov) == 1


def test_pipeline_skip_processed_false_reprocesses(
    tmp_path,
):
    """skip_processed=False runs the pipeline anyway."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    article = make_article(body="Apple rose again.")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_provenance(Provenance(
            entity_id=apple.entity_id,
            document_id=article.document_id.hex,
            source="bbc",
            mention_text="Apple",
            context_snippet="old ctx",
        ))
        pipeline = Pipeline(
            detector=RuleBasedDetector([apple]),
            resolver=AliasResolver(),
            store=store,
            skip_processed=False,
        )
        result = pipeline.run([article])

    assert result.documents_processed == 1
    # The new mention has a fresh context_snippet, so
    # dedup by (entity_id, document_id, mention_text)
    # blocks it. provenances_saved==0 is the expected
    # outcome — the point is that the article was not
    # skipped.
    assert result.results[0].skipped is False


# -- Pipeline.run: per-article isolation --


def test_pipeline_isolates_article_failure(tmp_path):
    """One failing article does not kill the run."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    articles = [
        make_article(body="Apple a.", title="good"),
    ]
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        pipeline = Pipeline(
            detector=RuleBasedDetector([apple]),
            resolver=_ExplodingResolver(),
            store=store,
        )
        result = pipeline.run(articles)
        run = store.get_run(result.run_id)

    assert len(result.results) == 1
    assert result.results[0].error == "boom"
    assert result.results[0].provenances_saved == 0
    # Run still completes — isolation is per-article.
    assert run is not None
    assert run.status == RunStatus.COMPLETED


# -- Pipeline.process_article: direct call --


def test_process_article_direct(tmp_path):
    """process_article works without a run."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    article = make_article(body="Apple rose.")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        pipeline = Pipeline(
            detector=RuleBasedDetector([apple]),
            resolver=AliasResolver(),
            store=store,
        )
        r = pipeline.process_article(article)
        prov = store.get_provenance(apple.entity_id)

    assert isinstance(r, ArticleResult)
    assert r.provenances_saved == 1
    assert len(prov) == 1
    # No run_id attached since none was supplied.
    assert prov[0].run_id is None


# -- Pipeline.run: stub wiring for deterministic check --


def test_pipeline_uses_injected_components(tmp_path):
    """Stubs verify the orchestrator calls the stages."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    article = make_article(body="anything")
    mention = Mention(
        surface_form="Apple",
        span_start=0,
        span_end=5,
        candidate_ids=(apple.entity_id,),
    )
    resolution = ResolutionResult(
        resolved=(
            ResolvedMention(
                entity_id=apple.entity_id,
                surface_form="Apple",
                context_snippet="...Apple...",
            ),
        ),
    )
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        pipeline = Pipeline(
            detector=_StubDetector((mention,)),
            resolver=_StubResolver(resolution),
            store=store,
        )
        result = pipeline.run([article])
        prov = store.get_provenance(apple.entity_id)

    assert result.provenances_saved == 1
    assert prov[0].mention_text == "Apple"
    assert prov[0].context_snippet == "...Apple..."


# -- LLM cascade tests --


class _FakeLLMProvider(LLMProvider):
    """Fake LLM provider for pipeline cascade tests."""

    provider_name = "fake"
    supports_json_mode = True
    model_name = "fake-1"
    context_window = 4096

    def __init__(self, response: str = "{}"):
        self._response = response

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        return self._response


def _llm_response(*entities):
    return json.dumps({"entities": list(entities)})


def _resolved_entry(eid, form, snippet="...ctx..."):
    return {
        "surface_form": form,
        "entity_id": eid,
        "new_entity": None,
        "context_snippet": snippet,
    }


def _new_entry(
    form, name, etype="organization",
    desc="A new entity.",
    snippet="...ctx...",
):
    return {
        "surface_form": form,
        "entity_id": None,
        "new_entity": {
            "canonical_name": name,
            "entity_type": etype,
            "description": desc,
            "aliases": [],
        },
        "context_snippet": snippet,
    }


def test_pipeline_llm_cascade_resolves_ambiguous(
    tmp_path,
):
    """LLM resolver handles mentions the alias resolver
    leaves unresolved."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    fed = make_org(
        "Federal Reserve", aliases=("the bank",)
    )
    ecb = make_org("ECB", aliases=("the bank",))

    # "the bank" is ambiguous (2 candidates).
    # LLM resolves it to "fed".
    response = _llm_response(
        _resolved_entry(
            fed.entity_id, "the bank"
        )
    )
    provider = _FakeLLMProvider(response)

    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_entity(fed)
        store.save_entity(ecb)
        detector = RuleBasedDetector(
            [apple, fed, ecb]
        )
        llm_resolver = LLMEntityResolver(
            provider=provider,
            entity_lookup=store.get_entity,
        )
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
            llm_resolver=llm_resolver,
        )
        article = make_article(
            body="Apple and the bank both grew."
        )
        result = pipeline.run([article])
        prov_fed = store.get_provenance(
            fed.entity_id
        )

    ar = result.results[0]
    # Apple resolved by alias, bank resolved by LLM.
    assert ar.provenances_saved == 2
    assert len(prov_fed) == 1
    assert prov_fed[0].mention_text == "the bank"


def test_pipeline_llm_cascade_creates_proposal(
    tmp_path,
):
    """LLM proposals are persisted as new entities."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))

    # LLM proposes "Tim Cook" as a new person entity
    # for the unresolved "Cook" mention.
    response = _llm_response(
        _new_entry(
            "Cook", "Tim Cook", "person",
            desc="CEO of Apple Inc.",
            snippet="...CEO Cook announced...",
        )
    )
    provider = _FakeLLMProvider(response)

    # Use a detector that finds both "Apple" (resolvable)
    # and "Cook" (unresolvable — no entity in KG).
    apple_mention = Mention(
        surface_form="Apple",
        span_start=0,
        span_end=5,
        candidate_ids=(apple.entity_id,),
    )
    cook_mention = Mention(
        surface_form="Cook",
        span_start=10,
        span_end=14,
        candidate_ids=(),
    )

    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        llm_resolver = LLMEntityResolver(
            provider=provider,
            entity_lookup=store.get_entity,
        )
        pipeline = Pipeline(
            detector=_StubDetector(
                (apple_mention, cook_mention)
            ),
            resolver=AliasResolver(),
            store=store,
            llm_resolver=llm_resolver,
        )
        article = make_article(
            body="Apple CEO Cook announced earnings."
        )
        result = pipeline.run([article])

        # New entity should exist in the KG.
        new_entities = store.find_by_name("Tim Cook")

    ar = result.results[0]
    assert ar.proposals_saved == 1
    assert len(new_entities) == 1
    assert (
        new_entities[0].entity_type
        == EntityType.PERSON
    )
    assert new_entities[0].description == (
        "CEO of Apple Inc."
    )


def test_pipeline_llm_cascade_proposal_provenance(
    tmp_path,
):
    """Proposed entities get provenance linked to the
    run."""
    db = tmp_path / "kg.db"
    response = _llm_response(
        _new_entry(
            "Powell", "Jerome Powell", "person",
        )
    )
    provider = _FakeLLMProvider(response)
    mention = Mention(
        surface_form="Powell",
        span_start=0,
        span_end=6,
        candidate_ids=(),
    )

    with KnowledgeStore(db_path=db) as store:
        llm_resolver = LLMEntityResolver(
            provider=provider,
            entity_lookup=store.get_entity,
        )
        pipeline = Pipeline(
            detector=_StubDetector((mention,)),
            resolver=AliasResolver(),
            store=store,
            llm_resolver=llm_resolver,
        )
        article = make_article(
            body="Powell spoke at the Fed."
        )
        result = pipeline.run([article])

        new_entities = store.find_by_name(
            "Jerome Powell"
        )
        prov = store.get_provenance(
            new_entities[0].entity_id
        )

    assert len(prov) == 1
    assert prov[0].run_id == result.run_id
    assert prov[0].mention_text == "Jerome Powell"
    assert prov[0].source == "bbc"


def test_pipeline_no_llm_resolver_leaves_unresolved(
    tmp_path,
):
    """Without llm_resolver, unresolved stay unresolved."""
    db = tmp_path / "kg.db"
    mention = Mention(
        surface_form="unknown",
        span_start=0,
        span_end=7,
        candidate_ids=(),
    )

    with KnowledgeStore(db_path=db) as store:
        pipeline = Pipeline(
            detector=_StubDetector((mention,)),
            resolver=AliasResolver(),
            store=store,
        )
        article = make_article(body="unknown entity")
        result = pipeline.run([article])

    ar = result.results[0]
    assert ar.provenances_saved == 0
    assert ar.proposals_saved == 0


def test_pipeline_llm_cascade_skips_when_all_resolved(
    tmp_path,
):
    """LLM resolver is not called when all mentions are
    resolved by the alias resolver."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    provider = _FakeLLMProvider("should not be called")

    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        detector = RuleBasedDetector([apple])
        llm_resolver = LLMEntityResolver(
            provider=provider,
            entity_lookup=store.get_entity,
        )
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
            llm_resolver=llm_resolver,
        )
        article = make_article(body="Apple grew.")
        result = pipeline.run([article])

    ar = result.results[0]
    assert ar.provenances_saved == 1
    assert ar.proposals_saved == 0


# -- Relationship extraction integration ----------------


class _StubExtractor(RelationshipExtractor):
    """Returns preset relationships."""

    def __init__(
        self, result: ExtractionResult | None = None
    ):
        self._result = result or ExtractionResult()
        self.calls: list[
            tuple[Chunk, tuple[ResolvedMention, ...]]
        ] = []

    def extract(
        self,
        chunk: Chunk,
        entities: tuple[ResolvedMention, ...],
    ) -> ExtractionResult:
        self.calls.append((chunk, entities))
        return self._result


class _ExplodingExtractor(RelationshipExtractor):
    """Raises on every call."""

    def extract(
        self,
        chunk: Chunk,
        entities: tuple[ResolvedMention, ...],
    ) -> ExtractionResult:
        raise RuntimeError("extraction boom")


def test_pipeline_extracts_relationships(tmp_path):
    """Relationships are extracted and persisted."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    msft = make_org("Microsoft", aliases=("Microsoft",))

    extraction = ExtractionResult(
        relationships=(
            ExtractedRelationship(
                source_id=apple.entity_id,
                target_id=msft.entity_id,
                relation_type="competes_with",
                context_snippet="Apple and Microsoft",
            ),
        )
    )
    extractor = _StubExtractor(extraction)

    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_entity(msft)
        detector = RuleBasedDetector([apple, msft])
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
            extractor=extractor,
        )
        article = make_article(
            body="Apple and Microsoft both grew."
        )
        result = pipeline.run([article])

        rels = store.get_relationships(
            apple.entity_id
        )

    ar = result.results[0]
    assert ar.relationships_saved == 1
    assert result.relationships_saved == 1
    assert len(rels) == 1
    assert rels[0].relation_type == "competes_with"
    assert rels[0].run_id == result.run_id


def test_pipeline_no_extractor_no_relationships(
    tmp_path,
):
    """Without extractor, relationships_saved is 0."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))

    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        detector = RuleBasedDetector([apple])
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
        )
        article = make_article(body="Apple grew.")
        result = pipeline.run([article])

    assert result.relationships_saved == 0
    assert result.results[0].relationships_saved == 0


def test_pipeline_extraction_error_isolated(tmp_path):
    """Extraction errors don't crash the run."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))

    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        detector = RuleBasedDetector([apple])
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
            extractor=_ExplodingExtractor(),
        )
        article = make_article(body="Apple grew.")
        result = pipeline.run([article])

    ar = result.results[0]
    assert ar.error is not None
    assert "extraction boom" in ar.error


def test_pipeline_relationship_count_in_run(tmp_path):
    """IngestionRun.relationship_count is populated."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    msft = make_org("Microsoft", aliases=("Microsoft",))

    extraction = ExtractionResult(
        relationships=(
            ExtractedRelationship(
                source_id=apple.entity_id,
                target_id=msft.entity_id,
                relation_type="competes_with",
                context_snippet="Apple and Microsoft",
            ),
        )
    )

    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_entity(msft)
        detector = RuleBasedDetector([apple, msft])
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
            extractor=_StubExtractor(extraction),
        )
        article = make_article(
            body="Apple and Microsoft both grew."
        )
        result = pipeline.run([article])

        run = store.get_run(result.run_id)

    assert run is not None
    assert run.relationship_count == 1


def test_pipeline_extractor_receives_resolved(
    tmp_path,
):
    """Extractor receives all resolved entities."""
    db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    msft = make_org("Microsoft", aliases=("Microsoft",))

    extractor = _StubExtractor()

    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_entity(msft)
        detector = RuleBasedDetector([apple, msft])
        pipeline = Pipeline(
            detector=detector,
            resolver=AliasResolver(),
            store=store,
            extractor=extractor,
        )
        article = make_article(
            body="Apple and Microsoft both grew."
        )
        pipeline.run([article])

    assert len(extractor.calls) == 1
    _, entities = extractor.calls[0]
    entity_ids = {e.entity_id for e in entities}
    assert apple.entity_id in entity_ids
    assert msft.entity_id in entity_ids
