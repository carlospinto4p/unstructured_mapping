"""Tests for the shared ``open_kg_store`` helper."""

import pytest

from unstructured_mapping.cli._db_helpers import open_kg_store
from unstructured_mapping.knowledge_graph import KnowledgeStore


def test_open_kg_store_missing_path_raises(tmp_path):
    missing = tmp_path / "nope.db"
    with pytest.raises(SystemExit, match="not found"):
        open_kg_store(missing)


def test_open_kg_store_create_if_missing(tmp_path):
    missing = tmp_path / "fresh.db"
    with open_kg_store(missing, create_if_missing=True) as store:
        assert isinstance(store, KnowledgeStore)
    assert missing.exists()


def test_open_kg_store_existing_opens_without_error(tmp_path):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db):
        pass
    with open_kg_store(db) as store:
        assert isinstance(store, KnowledgeStore)
