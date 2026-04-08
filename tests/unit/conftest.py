"""Shared test fixtures for unstructured_mapping unit tests."""

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
)


def _make_entity(**kwargs):
    defaults = {
        "canonical_name": "Test Entity",
        "entity_type": EntityType.PERSON,
        "description": "A test entity.",
    }
    defaults.update(kwargs)
    return Entity(**defaults)
