"""Tests for the ``cli.ingest`` batch-ingest CLI.

Exercises:

* the article-loading helper in both filtered and
  ``--resume-run`` modes,
* the pipeline-assembly helper across cold-start,
  no-LLM, and KG-driven shapes,
* ``main`` end-to-end on the alias-only path so the test
  needs no LLM, and
* the resume workflow: save an article failure, run the
  CLI with ``--resume-run``, and verify only the failed
  article is re-processed.
"""

import pytest

from unstructured_mapping.cli import ingest as cli_ingest
from unstructured_mapping.cli.ingest import (
    _build_pipeline,
    _load_articles,
    _summarise,
    ingest,
    main,
)
from unstructured_mapping.knowledge_graph import (
    IngestionRun,
    KnowledgeStore,
)
from unstructured_mapping.pipeline import (
    Pipeline,
    PipelineResult,
)
from unstructured_mapping.pipeline.orchestrator import ArticleResult
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.storage import ArticleStore

from .conftest import make_article, make_org


# -- _load_articles -------------------------------------


@pytest.fixture
def articles_db(tmp_path):
    """Two articles from different sources for filter tests."""
    db = tmp_path / "articles.db"
    ap_article = make_article(body="AP body", title="AP story", source="ap")
    bbc_article = make_article(
        body="BBC body", title="BBC story", source="bbc"
    )
    with ArticleStore(db) as store:
        store.save([ap_article, bbc_article])
    return db, ap_article, bbc_article


@pytest.fixture
def kg_db(tmp_path):
    db = tmp_path / "kg.db"
    # Pre-create the file so open_kg_store does not reject it.
    with KnowledgeStore(db_path=db):
        pass
    return db


def test_load_articles_honours_source_filter(articles_db, kg_db):
    db, ap, _bbc = articles_db
    with KnowledgeStore(db_path=kg_db) as kg_store:
        with ArticleStore(db) as articles_store:
            loaded = _load_articles(
                articles_store,
                kg_store=kg_store,
                source="ap",
                limit=None,
                resume_run_id=None,
            )
    assert [a.document_id for a in loaded] == [ap.document_id]


def test_load_articles_resume_reads_failed_ids(articles_db, kg_db):
    """Resume mode loads only the articles whose
    document_id is recorded in ``article_failures``.
    """
    db, ap, bbc = articles_db
    run = IngestionRun()
    with KnowledgeStore(db_path=kg_db) as kg_store:
        kg_store.save_run(run)
        # Pipeline.run records failures as
        # ``article.document_id.hex`` — mirror that shape.
        kg_store.save_article_failure(run.run_id, bbc.document_id.hex, "boom")
        with ArticleStore(db) as articles_store:
            loaded = _load_articles(
                articles_store,
                kg_store=kg_store,
                source="ap",  # ignored under resume
                limit=None,
                resume_run_id=run.run_id,
            )
    assert [a.document_id for a in loaded] == [bbc.document_id]


def test_load_articles_resume_warns_when_no_failures(
    articles_db, kg_db, caplog
):
    db, *_ = articles_db
    run = IngestionRun()
    with KnowledgeStore(db_path=kg_db) as kg_store:
        kg_store.save_run(run)
        with ArticleStore(db) as articles_store:
            with caplog.at_level("WARNING"):
                loaded = _load_articles(
                    articles_store,
                    kg_store=kg_store,
                    source=None,
                    limit=None,
                    resume_run_id=run.run_id,
                )
    assert loaded == []
    assert any("nothing to resume" in r.message for r in caplog.records)


# -- _build_pipeline ------------------------------------


def test_build_pipeline_cold_start_requires_provider(kg_db):
    with KnowledgeStore(db_path=kg_db) as store:
        with pytest.raises(ValueError, match="Cold-start"):
            _build_pipeline(
                store,
                provider=None,
                cold_start=True,
                extract_relationships=False,
            )


def test_build_pipeline_no_llm_omits_llm_stages(kg_db):
    with KnowledgeStore(db_path=kg_db) as store:
        pipeline = _build_pipeline(
            store,
            provider=None,
            cold_start=False,
            extract_relationships=True,
        )
    # noqa: SLF001 — verifying internal wiring so regression
    # tests catch accidental provider wiring without a mock.
    assert isinstance(pipeline, Pipeline)
    assert pipeline._processor._llm_resolver is None  # noqa: SLF001
    assert pipeline._processor._extractor is None  # noqa: SLF001


# -- ingest (alias-only, no LLM) ------------------------


def test_ingest_alias_only_writes_provenance(kg_db):
    """Alias resolver + rule-based detector are enough to
    write provenance for an article that mentions a known
    entity — no LLM needed.
    """
    apple = make_org("Apple", aliases=("Apple",))
    article = Article(
        title="t",
        body="Apple reported strong earnings.",
        url="https://ex/1",
        source="wire",
    )
    with KnowledgeStore(db_path=kg_db) as store:
        store.save_entity(apple)
        result = ingest(
            [article],
            store,
            provider=None,
            cold_start=False,
            extract_relationships=False,
            resume_run_id=None,
        )
        provenance = store.get_provenance(apple.entity_id)

    assert isinstance(result, PipelineResult)
    assert result.documents_processed == 1
    assert result.provenances_saved >= 1
    assert any(p.document_id == article.document_id.hex for p in provenance)


# -- _summarise -----------------------------------------


def test_summarise_counts_skips_and_failures():
    results = (
        ArticleResult(document_id="a", provenances_saved=1),
        ArticleResult(document_id="b", skipped=True),
        ArticleResult(document_id="c", error="boom"),
    )
    pr = PipelineResult(
        run_id="run-x",
        results=results,
        documents_processed=1,
        provenances_saved=1,
        proposals_saved=0,
        relationships_saved=0,
    )
    text = _summarise(pr)
    assert "Run run-x" in text
    assert "articles submitted:   3" in text
    assert "processed:            1" in text
    # One skipped-idempotent (b), one failed (c).
    assert "skipped (idempotent): 1" in text
    assert "failed:               1" in text


# -- main end-to-end (no LLM) ---------------------------


def test_main_ingests_and_prints_summary(articles_db, kg_db, capsys):
    db, ap, _bbc = articles_db
    apple = make_org("Apple", aliases=("AP body",))
    with KnowledgeStore(db_path=kg_db) as store:
        store.save_entity(apple)

    main(
        [
            "--db",
            str(kg_db),
            "--articles-db",
            str(db),
            "--source",
            "ap",
            "--no-llm",
        ]
    )
    captured = capsys.readouterr()
    assert "articles submitted:   1" in captured.out
    assert "processed:            1" in captured.out

    # Provenance landed against the AP article.
    with KnowledgeStore(db_path=kg_db) as store:
        provenance = store.get_provenance(apple.entity_id)
    assert any(p.document_id == ap.document_id.hex for p in provenance)


def test_main_exits_cleanly_when_no_articles(
    articles_db, kg_db, capsys, caplog
):
    db, *_ = articles_db
    with caplog.at_level("INFO"):
        main(
            [
                "--db",
                str(kg_db),
                "--articles-db",
                str(db),
                "--source",
                "nonexistent-wire",
                "--no-llm",
            ]
        )
    assert any("No articles to process" in r.message for r in caplog.records)
    assert capsys.readouterr().out == ""


def test_main_resume_run_processes_only_failed_article(
    articles_db, kg_db, capsys
):
    """Seed a prior failure for BBC, then resume.

    Even though the KG has no matching entity and we pass
    ``--no-llm`` so no proposals are made, the resumed
    article is still *processed* (documents_processed=1)
    — which is what we assert. The AP article is not
    attempted, proving the resume filter bit.
    """
    db, ap, bbc = articles_db
    prior = IngestionRun()
    with KnowledgeStore(db_path=kg_db) as store:
        store.save_run(prior)
        store.save_article_failure(
            prior.run_id, bbc.document_id.hex, "transient"
        )

    main(
        [
            "--db",
            str(kg_db),
            "--articles-db",
            str(db),
            "--resume-run",
            prior.run_id,
            "--no-llm",
        ]
    )
    captured = capsys.readouterr()
    assert "articles submitted:   1" in captured.out
    assert "processed:            1" in captured.out

    # AP had no failure row so resume never touched it —
    # provenance remains empty for its document_id.
    with KnowledgeStore(db_path=kg_db) as store:
        assert not store.has_document_provenance(ap.document_id.hex)


def test_main_cold_start_with_no_llm_errors(kg_db, articles_db):
    db, *_ = articles_db
    with pytest.raises(SystemExit, match="LLM provider"):
        main(
            [
                "--db",
                str(kg_db),
                "--articles-db",
                str(db),
                "--cold-start",
                "--no-llm",
            ]
        )


# -- ArticleStore.load document_ids ---------------------


def test_articles_load_by_document_ids_accepts_hex(articles_db):
    """Pipeline stores ids as ``UUID.hex`` but the articles
    table keeps ``str(UUID)`` — the ``load_by_document_ids``
    path must bridge both shapes.
    """
    db, ap, bbc = articles_db
    with ArticleStore(db) as store:
        loaded = store.load(document_ids=[bbc.document_id.hex])
    assert [a.document_id for a in loaded] == [bbc.document_id]


def test_articles_load_by_document_ids_empty_shortcircuits(articles_db):
    db, *_ = articles_db
    with ArticleStore(db) as store:
        loaded = store.load(document_ids=[])
    assert loaded == []


# Silence "unused import" on attribute lookups:
_ = cli_ingest
