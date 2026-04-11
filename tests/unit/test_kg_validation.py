"""Tests for KG validation — temporal, alias, constraint.

Covers:
- Temporal consistency (validate_temporal)
- Alias collision detection (find_alias_collisions)
- Relationship constraint checking
  (check_relationship_constraints,
  audit_relationship_constraints)
- Save-time integration (save_entity, save_relationship)
"""

from datetime import datetime, timezone

import pytest

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityStatus,
    EntityType,
    KnowledgeStore,
    Relationship,
    ValidationError,
    check_relationship_constraints,
    find_alias_collisions,
    validate_temporal,
)


# -- Helpers --


def _make_entity(
    name: str = "Test Entity",
    entity_type: EntityType = EntityType.ORGANIZATION,
    *,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    aliases: tuple[str, ...] = (),
    entity_id: str | None = None,
) -> Entity:
    kwargs: dict = {
        "canonical_name": name,
        "entity_type": entity_type,
        "description": f"Test {name}",
        "valid_from": valid_from,
        "valid_until": valid_until,
        "aliases": aliases,
        "status": EntityStatus.ACTIVE,
    }
    if entity_id is not None:
        kwargs["entity_id"] = entity_id
    return Entity(**kwargs)


def _make_relationship(
    source_id: str = "src",
    target_id: str = "tgt",
    *,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> Relationship:
    return Relationship(
        source_id=source_id,
        target_id=target_id,
        relation_type="related_to",
        description="test",
        valid_from=valid_from,
        valid_until=valid_until,
    )


DT_2020 = datetime(2020, 1, 1, tzinfo=timezone.utc)
DT_2023 = datetime(2023, 1, 1, tzinfo=timezone.utc)
DT_2025 = datetime(2025, 1, 1, tzinfo=timezone.utc)


# -- Temporal: Entity --


def test_temporal_entity_both_none():
    """Both None is valid (unbounded)."""
    validate_temporal(_make_entity())


def test_temporal_entity_from_only():
    """valid_from set, valid_until None is OK."""
    validate_temporal(
        _make_entity(valid_from=DT_2020)
    )


def test_temporal_entity_until_only():
    """valid_from None, valid_until set is OK."""
    validate_temporal(
        _make_entity(valid_until=DT_2025)
    )


def test_temporal_entity_valid_range():
    """valid_until > valid_from is OK."""
    validate_temporal(
        _make_entity(
            valid_from=DT_2020,
            valid_until=DT_2025,
        )
    )


def test_temporal_entity_equal():
    """valid_until == valid_from is OK."""
    validate_temporal(
        _make_entity(
            valid_from=DT_2023,
            valid_until=DT_2023,
        )
    )


def test_temporal_entity_invalid():
    """valid_until < valid_from raises."""
    with pytest.raises(
        ValidationError, match="valid_until.*before"
    ):
        validate_temporal(
            _make_entity(
                valid_from=DT_2025,
                valid_until=DT_2020,
            )
        )


# -- Temporal: Relationship --


def test_temporal_relationship_both_none():
    validate_temporal(_make_relationship())


def test_temporal_relationship_valid_range():
    validate_temporal(
        _make_relationship(
            valid_from=DT_2020,
            valid_until=DT_2025,
        )
    )


def test_temporal_relationship_invalid():
    with pytest.raises(
        ValidationError, match="Relationship"
    ):
        validate_temporal(
            _make_relationship(
                valid_from=DT_2025,
                valid_until=DT_2020,
            )
        )


# -- Alias collision detection --


@pytest.fixture
def store(tmp_path):
    with KnowledgeStore(
        db_path=tmp_path / "test.db"
    ) as s:
        yield s


def test_alias_no_collisions(store):
    """No collisions when aliases are unique."""
    e1 = _make_entity(
        "Apple Inc.",
        aliases=("Apple", "AAPL"),
        entity_id="e1",
    )
    e2 = _make_entity(
        "Google",
        aliases=("Alphabet", "GOOGL"),
        entity_id="e2",
    )
    store.save_entity(e1)
    store.save_entity(e2)

    collisions = find_alias_collisions(store._conn)
    assert collisions == []


def test_alias_collision_detected(store):
    """Shared alias across entities is detected."""
    e1 = _make_entity(
        "Apple Inc.",
        aliases=("Apple",),
        entity_id="e1",
    )
    e2 = _make_entity(
        "Apple Records",
        aliases=("Apple",),
        entity_id="e2",
    )
    store.save_entity(e1)
    store.save_entity(e2)

    collisions = find_alias_collisions(store._conn)
    assert len(collisions) == 1
    assert collisions[0].alias == "apple"
    assert len(collisions[0].entities) == 2


def test_alias_collision_different_types(store):
    """Collision flagged even across entity types."""
    e1 = _make_entity(
        "CEO Person",
        EntityType.PERSON,
        aliases=("CEO",),
        entity_id="e1",
    )
    e2 = _make_entity(
        "CEO Role",
        EntityType.ROLE,
        aliases=("CEO",),
        entity_id="e2",
    )
    store.save_entity(e1)
    store.save_entity(e2)

    collisions = find_alias_collisions(store._conn)
    assert len(collisions) == 1


def test_alias_collision_multiple(store):
    """Multiple collisions returned."""
    e1 = _make_entity(
        "Entity A",
        aliases=("shared1", "shared2"),
        entity_id="e1",
    )
    e2 = _make_entity(
        "Entity B",
        aliases=("shared1", "shared2"),
        entity_id="e2",
    )
    store.save_entity(e1)
    store.save_entity(e2)

    collisions = find_alias_collisions(store._conn)
    assert len(collisions) == 2


# -- Relationship constraint checking --


def test_constraint_known_pattern():
    """Known pattern returns no warnings."""
    warnings = check_relationship_constraints(
        "works_at",
        EntityType.PERSON,
        EntityType.ORGANIZATION,
    )
    assert warnings == []


def test_constraint_unknown_relation_type():
    """Unknown relation_type for known pair warns."""
    warnings = check_relationship_constraints(
        "invented",
        EntityType.PERSON,
        EntityType.ORGANIZATION,
    )
    assert len(warnings) == 1
    assert "Unknown relation_type" in warnings[0]
    assert "invented" in warnings[0]


def test_constraint_unknown_type_pair():
    """Unknown entity type pair warns."""
    warnings = check_relationship_constraints(
        "whatever",
        EntityType.ROLE,
        EntityType.ROLE,
    )
    assert len(warnings) == 1
    assert "No known patterns" in warnings[0]


def test_constraint_multiple_known():
    """Multiple relation_types valid for same pair."""
    for rel in (
        "acquired",
        "competes_with",
        "supplies",
    ):
        assert check_relationship_constraints(
            rel,
            EntityType.ORGANIZATION,
            EntityType.ORGANIZATION,
        ) == []


# -- Save integration --


def test_save_entity_rejects_bad_temporal(store):
    """save_entity raises on invalid temporal bounds."""
    entity = _make_entity(
        valid_from=DT_2025,
        valid_until=DT_2020,
    )
    with pytest.raises(ValidationError):
        store.save_entity(entity)


def test_save_entity_accepts_valid_temporal(store):
    """save_entity succeeds with valid bounds."""
    entity = _make_entity(
        valid_from=DT_2020,
        valid_until=DT_2025,
    )
    store.save_entity(entity)
    loaded = store.get_entity(entity.entity_id)
    assert loaded is not None


def test_save_relationship_rejects_bad_temporal(store):
    """save_relationship raises on invalid bounds."""
    src = _make_entity("Src", entity_id="src")
    tgt = _make_entity("Tgt", entity_id="tgt")
    store.save_entity(src)
    store.save_entity(tgt)

    rel = _make_relationship(
        valid_from=DT_2025,
        valid_until=DT_2020,
    )
    with pytest.raises(ValidationError):
        store.save_relationship(rel)


def test_save_relationships_rejects_bad_temporal(
    store,
):
    """save_relationships raises on invalid bounds."""
    src = _make_entity("Src", entity_id="src")
    tgt = _make_entity("Tgt", entity_id="tgt")
    store.save_entity(src)
    store.save_entity(tgt)

    rels = [
        _make_relationship(
            valid_from=DT_2025,
            valid_until=DT_2020,
        )
    ]
    with pytest.raises(ValidationError):
        store.save_relationships(rels)


def test_save_relationship_accepts_valid(store):
    """save_relationship succeeds with valid bounds."""
    src = _make_entity("Src", entity_id="src")
    tgt = _make_entity("Tgt", entity_id="tgt")
    store.save_entity(src)
    store.save_entity(tgt)

    rel = _make_relationship(
        valid_from=DT_2020,
        valid_until=DT_2025,
    )
    store.save_relationship(rel)

    loaded = store.get_relationships("src")
    assert len(loaded) == 1
