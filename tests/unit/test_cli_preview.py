"""Tests for the dry-run pipeline preview CLI.

The preview lives outside the real KG path (it writes to
a throwaway SQLite file and returns a JSON payload), so
tests exercise article loading, the payload shape, and
the argument validation that guards the two modes.
"""

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from tests.unit.conftest import make_org
from unstructured_mapping.cli.preview import (
    load_article,
    preview,
)
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)


# -- load_article ---------------------------------------


def test_load_article_from_text():
    article = load_article(article_file=None, text="Apple acquired Pebble.")
    assert article.body == "Apple acquired Pebble."
    assert article.source == "preview"


def test_load_article_from_file(tmp_path):
    doc_id = uuid4().hex
    path = tmp_path / "art.json"
    path.write_text(
        json.dumps(
            {
                "document_id": doc_id,
                "title": "Q3",
                "body": "Apple reported.",
                "url": "https://ex",
                "source": "wire",
            }
        ),
        encoding="utf-8",
    )
    article = load_article(article_file=path, text=None)
    assert article.document_id == UUID(doc_id)
    assert article.title == "Q3"
    assert article.source == "wire"


def test_load_article_requires_exactly_one_input():
    with pytest.raises(ValueError, match="exactly one"):
        load_article(article_file=None, text=None)
    with pytest.raises(ValueError, match="exactly one"):
        load_article(article_file=Path("x"), text="body")


def test_load_article_file_missing_body_raises(
    tmp_path,
):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps({"title": "no body"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="body"):
        load_article(article_file=path, text=None)


# -- preview end-to-end (no LLM) ------------------------


def test_preview_kg_driven_without_llm(tmp_path):
    """Without an LLM provider the preview still reports
    alias-resolved mentions from the KG."""
    kg_db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    with KnowledgeStore(db_path=kg_db) as store:
        store.save_entity(apple)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    article = load_article(
        article_file=None,
        text="Apple reported strong earnings.",
    )
    payload = preview(
        article,
        kg_db=kg_db,
        provider=None,
        workdir=workdir,
        cold_start=False,
    )
    assert payload["mode"] == "kg-driven"
    assert payload["chunks_processed"] == 1
    mentions = payload["mentions"]
    assert any(m["canonical_name"] == "Apple" for m in mentions)
    # No LLM → no token spend.
    assert payload["token_usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
    }


def test_preview_cold_start_requires_provider(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    article = load_article(article_file=None, text="Anything.")
    with pytest.raises(ValueError, match="provider"):
        preview(
            article,
            kg_db=None,
            provider=None,
            workdir=workdir,
            cold_start=True,
        )


def test_preview_does_not_touch_source_kg(tmp_path):
    """Running a preview must not mutate the source KG."""
    kg_db = tmp_path / "kg.db"
    apple = make_org("Apple", aliases=("Apple",))
    with KnowledgeStore(db_path=kg_db) as store:
        store.save_entity(apple)

    workdir = tmp_path / "workdir"
    workdir.mkdir()
    article = load_article(
        article_file=None,
        text="Apple did things.",
    )
    preview(
        article,
        kg_db=kg_db,
        provider=None,
        workdir=workdir,
        cold_start=False,
    )
    # The source KG still has exactly one entity and no
    # provenance rows from the preview run.
    with KnowledgeStore(db_path=kg_db) as store:
        rows = store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM provenance"
        ).fetchone()
        assert rows[0] == 0
        entities = store._conn.execute(  # noqa: SLF001
            "SELECT COUNT(*) FROM entities"
        ).fetchone()
        assert entities[0] == 1
