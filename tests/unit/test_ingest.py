"""Tests for cli.ingest._summarise."""

from unstructured_mapping.cli.ingest import _summarise
from unstructured_mapping.pipeline import PipelineResult
from unstructured_mapping.pipeline._article_processor import ArticleResult


def _make_result(
    *,
    run_id: str = "run-abc",
    results: tuple[ArticleResult, ...] = (),
    documents_processed: int = 0,
    provenances_saved: int = 0,
    proposals_saved: int = 0,
    relationships_saved: int = 0,
) -> PipelineResult:
    return PipelineResult(
        run_id=run_id,
        results=results,
        documents_processed=documents_processed,
        provenances_saved=provenances_saved,
        proposals_saved=proposals_saved,
        relationships_saved=relationships_saved,
    )


def _article(
    doc_id: str,
    *,
    skipped: bool = False,
    error: str | None = None,
    provenances: int = 0,
) -> ArticleResult:
    return ArticleResult(
        document_id=doc_id,
        skipped=skipped,
        error=error,
        provenances_saved=provenances,
    )


def test_summarise_all_processed():
    results = (
        _article("a1", provenances=2),
        _article("a2", provenances=1),
    )
    r = _make_result(
        results=results, documents_processed=2, provenances_saved=3
    )
    out = _summarise(r)
    assert "processed:            2" in out
    assert "skipped (idempotent): 0" in out
    assert "failed:               0" in out
    assert "provenance rows:      3" in out


def test_summarise_with_failures_never_negative():
    """skipped (idempotent) must not go negative when articles fail."""
    results = (
        _article("a1", error="LLM auth failed"),
        _article("a2", error="LLM auth failed"),
        _article("a3", provenances=1),
    )
    r = _make_result(
        results=results, documents_processed=3, provenances_saved=1
    )
    out = _summarise(r)
    assert "processed:            1" in out
    assert "skipped (idempotent): 0" in out
    assert "failed:               2" in out


def test_summarise_with_skipped():
    results = (
        _article("a1", skipped=True),
        _article("a2", provenances=2),
    )
    r = _make_result(
        results=results, documents_processed=1, provenances_saved=2
    )
    out = _summarise(r)
    assert "processed:            1" in out
    assert "skipped (idempotent): 1" in out
    assert "failed:               0" in out


def test_summarise_mixed_skipped_failed_processed():
    """submitted = processed + skipped + failed always balances."""
    results = (
        _article("a1", provenances=3),
        _article("a2", skipped=True),
        _article("a3", error="timeout"),
        _article("a4", provenances=1),
    )
    r = _make_result(
        results=results, documents_processed=3, provenances_saved=4
    )
    out = _summarise(r)
    assert "articles submitted:   4" in out
    assert "processed:            2" in out
    assert "skipped (idempotent): 1" in out
    assert "failed:               1" in out


def test_summarise_counts_relationships_and_proposals():
    results = (_article("a1", provenances=1),)
    r = _make_result(
        results=results,
        documents_processed=1,
        provenances_saved=1,
        proposals_saved=3,
        relationships_saved=5,
    )
    out = _summarise(r)
    assert "new entities:         3" in out
    assert "relationships:        5" in out
