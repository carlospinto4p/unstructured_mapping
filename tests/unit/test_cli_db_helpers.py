"""Tests for the shared DB-open helpers."""

import pytest

from unstructured_mapping.cli._db_helpers import (
    open_kg_store,
    prepare_throwaway_kg,
)
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


# -- prepare_throwaway_kg --


def test_prepare_throwaway_kg_no_source(tmp_path):
    target = prepare_throwaway_kg(tmp_path, "scratch.db")
    assert target == tmp_path / "scratch.db"
    assert not target.exists()


def test_prepare_throwaway_kg_copies_from_source(tmp_path):
    source = tmp_path / "seed.db"
    with KnowledgeStore(db_path=source):
        pass
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    target = prepare_throwaway_kg(workdir, "copy.db", source=source)
    assert target.exists()
    assert target != source
    # Source must remain untouched (throwaway policy).
    assert source.exists()


def test_prepare_throwaway_kg_overwrites_stale_target(tmp_path):
    """A stale file from a prior run must be unlinked so
    ``create_if_missing=False`` callers opening the target
    see a truly empty slate (or, with ``source``, only the
    copied content)."""
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    stale = workdir / "scratch.db"
    stale.write_bytes(b"old")
    target = prepare_throwaway_kg(workdir, "scratch.db")
    assert not target.exists()


def test_prepare_throwaway_kg_missing_source_raises(tmp_path):
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    with pytest.raises(FileNotFoundError):
        prepare_throwaway_kg(workdir, "copy.db", source=tmp_path / "nope.db")
