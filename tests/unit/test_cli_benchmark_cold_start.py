"""Tests for the cold-start benchmarking CLI.

Exercises the labelled-file loader, the scoring helpers,
and the end-to-end benchmark with a fake LLM provider so
precision/recall math is deterministic.
"""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from unstructured_mapping.cli import benchmark_cold_start
from unstructured_mapping.cli.benchmark_cold_start import (
    ArticleScore,
    BenchmarkReport,
    LabelledArticle,
    LabelledEntity,
    ModeReport,
    benchmark,
    load_labelled,
)
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)


def _write_labelled(path: Path, articles: list[dict]) -> Path:
    path.write_text(
        json.dumps({"articles": articles}),
        encoding="utf-8",
    )
    return path


def _labelled_article(
    *,
    doc_id: str | None = None,
    body: str = "Apple reported strong earnings.",
    expected: tuple[tuple[str, str], ...] = (("Apple", "organization"),),
) -> dict:
    return {
        "document_id": doc_id or uuid4().hex,
        "title": "t",
        "body": body,
        "source": "benchmark",
        "entities": [
            {"canonical_name": n, "entity_type": t} for n, t in expected
        ],
    }


# -- load_labelled ---------------------------------------


def test_load_labelled_parses_valid_file(tmp_path):
    path = _write_labelled(
        tmp_path / "labels.json",
        [
            _labelled_article(
                doc_id="a" * 32,
                expected=(
                    ("Apple", "organization"),
                    ("Tim Cook", "person"),
                ),
            )
        ],
    )
    labelled = load_labelled(path)
    assert len(labelled) == 1
    la = labelled[0]
    assert la.article.document_id == UUID("a" * 32)
    assert len(la.expected) == 2
    assert la.expected[0] == LabelledEntity(
        canonical_name="Apple",
        entity_type="organization",
    )


def test_load_labelled_rejects_unknown_entity_type(
    tmp_path,
):
    path = _write_labelled(
        tmp_path / "labels.json",
        [_labelled_article(expected=(("Apple", "not_a_type"),))],
    )
    with pytest.raises(ValueError):
        load_labelled(path)


def test_load_labelled_missing_field_raises(tmp_path):
    path = tmp_path / "labels.json"
    path.write_text(
        json.dumps({"articles": [{"title": "x"}]}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing field"):
        load_labelled(path)


# -- scoring --------------------------------------------


def test_article_score_tp_fp_fn():
    score = ArticleScore(
        document_id="d",
        expected=frozenset(
            {
                ("apple", "organization"),
                ("tim cook", "person"),
            }
        ),
        discovered=frozenset(
            {
                ("apple", "organization"),
                ("microsoft", "organization"),
            }
        ),
    )
    assert score.true_positives == 1
    assert score.false_positives == 1
    assert score.false_negatives == 1


def test_mode_report_aggregates_metrics():
    s1 = ArticleScore(
        document_id="d1",
        expected=frozenset({("a", "person")}),
        discovered=frozenset({("a", "person")}),
    )
    s2 = ArticleScore(
        document_id="d2",
        expected=frozenset({("b", "person")}),
        discovered=frozenset({("b", "person"), ("c", "person")}),
    )
    mr = ModeReport(mode="cold-start", articles=(s1, s2))
    # TP=2, FP=1, FN=0
    assert mr.precision == pytest.approx(2 / 3)
    assert mr.recall == pytest.approx(1.0)
    assert mr.f1 == pytest.approx(0.8)


def test_mode_report_empty_articles_returns_zero():
    mr = ModeReport(mode="cold-start", articles=())
    assert mr.precision == 0.0
    assert mr.recall == 0.0
    assert mr.f1 == 0.0


# -- benchmark end-to-end via a fake cold-start ---------


class _FakeDiscoverer:
    """Mimics ColdStartEntityDiscoverer without an LLM.

    Returns a canned list of proposals per document so the
    scoring path can be exercised deterministically. The
    orchestrator only calls ``discover`` and reads
    ``last_token_usage`` — both are satisfied here.
    """

    def __init__(self, per_doc: dict[str, list[tuple[str, str]]]):
        self._per_doc = per_doc
        from unstructured_mapping.pipeline import TokenUsage

        self._usage = TokenUsage(input_tokens=10, output_tokens=2)
        # Exposed so `Pipeline._provider_name` returns
        # our fake provider identity.
        self._provider = _FakeProviderHandle()

    @property
    def last_token_usage(self):
        return self._usage

    def discover(self, chunk):
        from unstructured_mapping.knowledge_graph import (
            EntityType,
        )
        from unstructured_mapping.pipeline.models import (
            EntityProposal,
        )

        specs = self._per_doc.get(chunk.document_id, [])
        proposals = []
        for name, etype in specs:
            proposals.append(
                EntityProposal(
                    canonical_name=name,
                    entity_type=EntityType(etype),
                    description=f"Benchmark {name}",
                    aliases=(),
                    context_snippet="...",
                )
            )
        return tuple(proposals)


class _FakeProviderHandle:
    provider_name = "fake"
    model_name = "fake-1"


def test_benchmark_cold_start_scores_discovered(tmp_path, monkeypatch):
    """End-to-end: labelled file + fake discoverer →
    precision/recall reflects the LLM's coverage."""
    doc_a = uuid4().hex
    doc_b = uuid4().hex
    labels = _write_labelled(
        tmp_path / "labels.json",
        [
            _labelled_article(
                doc_id=doc_a,
                expected=(
                    ("Apple", "organization"),
                    ("Tim Cook", "person"),
                ),
            ),
            _labelled_article(
                doc_id=doc_b,
                expected=(("Microsoft", "organization"),),
            ),
        ],
    )
    labelled = load_labelled(labels)

    fake = _FakeDiscoverer(
        per_doc={
            # Perfect match on article A
            doc_a: [
                ("Apple", "organization"),
                ("Tim Cook", "person"),
            ],
            # Miss on B and a false positive instead
            doc_b: [("Oracle", "organization")],
        }
    )

    # Swap the real cold-start run for one that uses the
    # fake discoverer. We keep all scoring/persistence
    # logic intact so the test exercises the real code
    # path for provenance → scoring.
    from unstructured_mapping.pipeline import (
        AliasResolver,
        NoopDetector,
        Pipeline,
    )

    def _fake_run_cold_start(labelled, provider, db_path):
        articles = [la.article for la in labelled]
        with KnowledgeStore(db_path=db_path) as store:
            pipeline = Pipeline(
                detector=NoopDetector(),
                resolver=AliasResolver(),
                store=store,
                cold_start_discoverer=fake,
            )
            result = pipeline.run(articles)
            metrics = store.get_run_metrics(result.run_id)
            scores = benchmark_cold_start._score_articles(labelled, store)
        return ModeReport(
            mode="cold-start",
            articles=scores,
            tokens_in=metrics.input_tokens,
            tokens_out=metrics.output_tokens,
        )

    monkeypatch.setattr(
        benchmark_cold_start,
        "_run_cold_start",
        _fake_run_cold_start,
    )

    report = benchmark(
        labelled,
        provider=None,  # unused: fake run ignores it
        seed_db=None,
        mode="cold-start",
        workdir=tmp_path,
    )
    assert isinstance(report, BenchmarkReport)
    assert len(report.modes) == 1
    mr = report.modes[0]
    # Article A: 2 TPs, 0 FP, 0 FN
    # Article B: 0 TP, 1 FP (Oracle), 1 FN (Microsoft)
    # Overall: TP=2, FP=1, FN=1
    assert mr.precision == pytest.approx(2 / 3)
    assert mr.recall == pytest.approx(2 / 3)
    # Tokens accumulate from the fake discoverer.
    assert mr.tokens_in == 20  # 10 per article × 2
    assert mr.tokens_out == 4


def test_benchmark_kg_driven_requires_seed_db(tmp_path):
    labelled: list[LabelledArticle] = []
    with pytest.raises(ValueError, match="seed-db"):
        benchmark(
            labelled,
            provider=None,
            seed_db=None,
            mode="kg-driven",
            workdir=tmp_path,
        )


def test_benchmark_rejects_unknown_mode(tmp_path):
    with pytest.raises(ValueError, match="mode"):
        benchmark(
            [],
            provider=None,
            seed_db=None,
            mode="nonsense",
            workdir=tmp_path,
        )
