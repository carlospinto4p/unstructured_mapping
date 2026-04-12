"""Tests for the seed loader CLI."""

import json
from pathlib import Path

import pytest

from unstructured_mapping.cli.seed import (
    _parse_entity,
    load_seed,
    main,
)
from unstructured_mapping.knowledge_graph import (
    EntityType,
    KnowledgeStore,
)


# -- fixtures ---------------------------------------------------


def _write_seed(
    path: Path, entities: list[dict]
) -> Path:
    path.write_text(
        json.dumps({"version": 1, "entities": entities}),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def seed_file(tmp_path: Path) -> Path:
    return _write_seed(
        tmp_path / "seed.json",
        [
            {
                "canonical_name": "Federal Reserve",
                "entity_type": "organization",
                "subtype": "central_bank",
                "description": "US central bank.",
                "aliases": ["Fed", "FOMC"],
            },
            {
                "canonical_name": "Gold",
                "entity_type": "asset",
                "subtype": "commodity",
                "description": "Precious metal.",
            },
        ],
    )


# -- _parse_entity ----------------------------------------------


def test_parse_entity_maps_all_fields():
    raw = {
        "canonical_name": "Apple Inc.",
        "entity_type": "organization",
        "subtype": "company",
        "description": "Tech company.",
        "aliases": ["Apple", "AAPL"],
    }
    entity = _parse_entity(raw)
    assert entity.canonical_name == "Apple Inc."
    assert entity.entity_type is EntityType.ORGANIZATION
    assert entity.subtype == "company"
    assert entity.aliases == ("Apple", "AAPL")


def test_parse_entity_defaults_aliases_to_empty_tuple():
    raw = {
        "canonical_name": "X",
        "entity_type": "person",
        "description": "Y",
    }
    assert _parse_entity(raw).aliases == ()


def test_parse_entity_rejects_unknown_type():
    raw = {
        "canonical_name": "X",
        "entity_type": "not_a_type",
        "description": "Y",
    }
    with pytest.raises(ValueError):
        _parse_entity(raw)


def test_parse_entity_requires_canonical_name():
    with pytest.raises(KeyError):
        _parse_entity(
            {
                "entity_type": "person",
                "description": "Y",
            }
        )


# -- load_seed --------------------------------------------------


def test_load_seed_creates_entities(
    tmp_path: Path, seed_file: Path
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        created, skipped, counts = load_seed(
            seed_file, store
        )
        assert created == 2
        assert skipped == 0
        assert counts["organization"] == 1
        assert counts["asset"] == 1
        fed = store.find_by_name("Federal Reserve")
        assert len(fed) == 1
        assert set(fed[0].aliases) == {"Fed", "FOMC"}


def test_load_seed_is_idempotent(
    tmp_path: Path, seed_file: Path
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        load_seed(seed_file, store)
        created, skipped, counts = load_seed(
            seed_file, store
        )
        assert created == 0
        assert skipped == 2
        assert counts == {}


def test_load_seed_skip_is_case_insensitive(
    tmp_path: Path
):
    seed = _write_seed(
        tmp_path / "seed.json",
        [
            {
                "canonical_name": "gold",
                "entity_type": "asset",
                "description": "v2",
            }
        ],
    )
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(
            _parse_entity(
                {
                    "canonical_name": "Gold",
                    "entity_type": "asset",
                    "description": "v1",
                }
            )
        )
        created, skipped, _ = load_seed(seed, store)
        assert created == 0
        assert skipped == 1


def test_load_seed_same_name_different_type_not_skipped(
    tmp_path: Path,
):
    seed = _write_seed(
        tmp_path / "seed.json",
        [
            {
                "canonical_name": "Gold",
                "entity_type": "asset",
                "description": "commodity",
            }
        ],
    )
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(
            _parse_entity(
                {
                    "canonical_name": "Gold",
                    "entity_type": "topic",
                    "description": "A colour.",
                }
            )
        )
        created, skipped, _ = load_seed(seed, store)
        assert created == 1
        assert skipped == 0


def test_load_seed_dry_run_does_not_write(
    tmp_path: Path, seed_file: Path
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        created, skipped, counts = load_seed(
            seed_file, store, dry_run=True
        )
        assert created == 2
        assert skipped == 0
        assert counts["organization"] == 1
        assert store.find_by_name("Federal Reserve") == []


def test_load_seed_tags_history_with_seed_reason(
    tmp_path: Path, seed_file: Path
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        load_seed(seed_file, store)
        fed = store.find_by_name("Federal Reserve")[0]
        history = store.get_entity_history(fed.entity_id)
        assert history[0].reason == "seed"


# -- main -------------------------------------------------------


def test_main_missing_seed_file_exits(tmp_path: Path):
    db = tmp_path / "kg.db"
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(SystemExit) as exc:
        main(["--seed", str(missing), "--db", str(db)])
    assert exc.value.code == 1


def test_main_loads_real_seed(
    tmp_path: Path, seed_file: Path
):
    db = tmp_path / "kg.db"
    main(["--seed", str(seed_file), "--db", str(db)])
    with KnowledgeStore(db_path=db) as store:
        assert len(store.find_by_name("Gold")) == 1


# -- curated seed file sanity checks ----------------------------


def test_curated_seed_file_is_valid():
    """The shipped curated seed file must parse cleanly
    and every entry must have a valid entity_type."""
    path = Path("data/seed/financial_entities.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    entities = data["entities"]
    assert len(entities) >= 50
    for raw in entities:
        _parse_entity(raw)


def test_curated_seed_file_has_unique_names_per_type():
    path = Path("data/seed/financial_entities.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    seen: set[tuple[str, str]] = set()
    for raw in data["entities"]:
        key = (
            raw["canonical_name"].lower(),
            raw["entity_type"],
        )
        assert key not in seen, (
            f"duplicate seed entry: {key}"
        )
        seen.add(key)
