"""Tests for the populate orchestrator CLI."""

import json
from pathlib import Path

import pytest

from unstructured_mapping.cli.populate import (
    main,
    populate,
)
from unstructured_mapping.knowledge_graph import KnowledgeStore


# -- fixtures ---------------------------------------------------


def _write_seed(path: Path, entities: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "entities": entities}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def seed_dir(tmp_path: Path) -> Path:
    base = tmp_path / "seed"
    _write_seed(
        base / "financial_entities.json",
        [
            {
                "canonical_name": "Federal Reserve",
                "entity_type": "organization",
                "subtype": "central_bank",
                "description": "US central bank.",
                "aliases": ["Fed"],
            }
        ],
    )
    _write_seed(
        base / "wikidata" / "currency.json",
        [
            {
                "canonical_name": "US dollar",
                "entity_type": "asset",
                "subtype": "currency",
                "description": "USD.",
            }
        ],
    )
    _write_seed(
        base / "wikidata" / "company.json",
        [
            {
                "canonical_name": "Apple Inc.",
                "entity_type": "organization",
                "subtype": "company",
                "description": "Tech.",
            }
        ],
    )
    return base


# -- populate --------------------------------------------------


def test_populate_runs_curated_then_snapshots(
    tmp_path: Path, seed_dir: Path
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        reports = populate(seed_dir, store)
    names = [r.name for r in reports]
    assert names == ["curated", "company", "currency"]
    # Curated must precede Wikidata snapshots so its
    # canonical names win on dedup.
    assert names.index("curated") == 0


def test_populate_creates_all_entities(
    tmp_path: Path, seed_dir: Path
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        reports = populate(seed_dir, store)
        assert store.find_by_name("Federal Reserve")
        assert store.find_by_name("US dollar")
        assert store.find_by_name("Apple Inc.")
    total_created = sum(r.created for r in reports)
    assert total_created == 3


def test_populate_is_idempotent(
    tmp_path: Path, seed_dir: Path
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        populate(seed_dir, store)
        reports = populate(seed_dir, store)
    assert sum(r.created for r in reports) == 0
    assert sum(r.skipped for r in reports) == 3


def test_populate_dry_run_writes_nothing(
    tmp_path: Path, seed_dir: Path
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        reports = populate(seed_dir, store, dry_run=True)
        assert store.find_by_name("Federal Reserve") == []
    assert sum(r.created for r in reports) == 3


def test_populate_curated_wins_on_name_conflict(
    tmp_path: Path,
):
    base = tmp_path / "seed"
    _write_seed(
        base / "financial_entities.json",
        [
            {
                "canonical_name": "Apple Inc.",
                "entity_type": "organization",
                "description": "Curated description.",
            }
        ],
    )
    _write_seed(
        base / "wikidata" / "company.json",
        [
            {
                "canonical_name": "apple inc.",
                "entity_type": "organization",
                "description": "Wikidata description.",
            }
        ],
    )
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        reports = populate(base, store)
        matches = store.find_by_name("Apple Inc.")
    assert len(matches) == 1
    assert matches[0].description == "Curated description."
    wikidata_stage = next(
        r for r in reports if r.name == "company"
    )
    assert wikidata_stage.skipped == 1
    assert wikidata_stage.created == 0


def test_populate_raises_when_seed_dir_empty(tmp_path: Path):
    db = tmp_path / "kg.db"
    empty = tmp_path / "empty"
    empty.mkdir()
    with KnowledgeStore(db_path=db) as store:
        with pytest.raises(FileNotFoundError):
            populate(empty, store)


def test_populate_runs_without_curated_file(
    tmp_path: Path,
):
    base = tmp_path / "seed"
    _write_seed(
        base / "wikidata" / "crypto.json",
        [
            {
                "canonical_name": "Bitcoin",
                "entity_type": "asset",
                "subtype": "crypto",
                "description": "BTC.",
            }
        ],
    )
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        reports = populate(base, store)
    assert [r.name for r in reports] == ["crypto"]


# -- main -------------------------------------------------------


def test_main_populates_from_seed_dir(
    tmp_path: Path, seed_dir: Path
):
    db = tmp_path / "kg.db"
    main(
        [
            "--seed-dir",
            str(seed_dir),
            "--db",
            str(db),
        ]
    )
    with KnowledgeStore(db_path=db) as store:
        assert store.find_by_name("Federal Reserve")
        assert store.find_by_name("US dollar")


def test_main_dry_run_is_noop(
    tmp_path: Path, seed_dir: Path
):
    db = tmp_path / "kg.db"
    main(
        [
            "--seed-dir",
            str(seed_dir),
            "--db",
            str(db),
            "--dry-run",
        ]
    )
    with KnowledgeStore(db_path=db) as store:
        assert store.find_by_name("Federal Reserve") == []
