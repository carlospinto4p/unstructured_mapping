"""Tests for the pipeline orchestrator."""

import pytest

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeStore,
    Provenance,
    RunStatus,
)
from unstructured_mapping.pipeline import (
    AliasResolver,
    ArticleResult,
    Pipeline,
    PipelineResult,
    RuleBasedDetector,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    Mention,
    ResolutionResult,
    ResolvedMention,
)
from unstructured_mapping.pipeline.detection import (
    EntityDetector,
)
from unstructured_mapping.pipeline.resolution import (
    EntityResolver,
)
from unstructured_mapping.web_scraping.models import Article


# -- Helpers --


def make_article(
    body: str = "Apple and Microsoft both grew.",
    title: str = "Tech news",
    source: str = "bbc",
) -> Article:
    return Article(
        title=title,
        body=body,
        url=f"https://example.com/{title}",
        source=source,
    )


def make_org(
    name: str,
    aliases: tuple[str, ...] = (),
) -> Entity:
    return Entity(
        canonical_name=name,
        entity_type=EntityType.ORGANIZATION,
        description=f"Test entity {name}",
        aliases=aliases,
        entity_id=name.lower().replace(" ", "_"),
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
