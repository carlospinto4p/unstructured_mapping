"""Shared helpers for knowledge graph storage mixins.

Row converters, datetime utilities, and SQL fragment
constants used across :mod:`_entity_mixin`,
:mod:`_provenance_mixin`, :mod:`_relationship_mixin`,
and :mod:`_run_mixin`.
"""

import json
import sqlite3
from datetime import datetime, timezone

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityRevision,
    EntityStatus,
    EntityType,
    IngestionRun,
    Provenance,
    Relationship,
    RelationshipRevision,
    RunStatus,
)

# -- SQL fragments -----------------------------------------------

ENTITY_SELECT = (
    "SELECT entity_id, canonical_name, "
    "entity_type, subtype, description, "
    "valid_from, valid_until, status, "
    "merged_into, created_at, updated_at "
    "FROM entities "
)

ENTITY_SELECT_ALIASED = (
    "SELECT e.entity_id, e.canonical_name, "
    "e.entity_type, e.subtype, e.description, "
    "e.valid_from, e.valid_until, e.status, "
    "e.merged_into, e.created_at, "
    "e.updated_at FROM entities e "
)

REL_SELECT = (
    "SELECT source_id, target_id, relation_type, "
    "description, qualifier_id, relation_kind_id, "
    "valid_from, valid_until, document_id, "
    "discovered_at, run_id FROM relationships "
)

# -- Datetime utilities ------------------------------------------


def now_iso() -> str:
    """Return the current UTC time as an ISO string."""
    return datetime.now(timezone.utc).isoformat()


def dt_to_iso(dt: datetime | None) -> str | None:
    """Convert a datetime to ISO string, or ``None``."""
    return dt.isoformat() if dt else None


def iso_to_dt(s: str | None) -> datetime | None:
    """Parse an ISO string to datetime, or ``None``."""
    return datetime.fromisoformat(s) if s else None


# -- Row converters ----------------------------------------------


def row_to_entity(
    row: sqlite3.Row,
    aliases: tuple[str, ...],
) -> Entity:
    """Convert a ``sqlite3.Row`` + aliases to an Entity."""
    return Entity(
        entity_id=row["entity_id"],
        canonical_name=row["canonical_name"],
        entity_type=EntityType(row["entity_type"]),
        subtype=row["subtype"],
        description=row["description"],
        aliases=aliases,
        valid_from=iso_to_dt(row["valid_from"]),
        valid_until=iso_to_dt(row["valid_until"]),
        status=EntityStatus(row["status"]),
        merged_into=row["merged_into"],
        created_at=iso_to_dt(row["created_at"]),
        updated_at=iso_to_dt(row["updated_at"]),
    )


def row_to_provenance(row: sqlite3.Row) -> Provenance:
    """Convert a ``sqlite3.Row`` to a Provenance."""
    return Provenance(
        entity_id=row["entity_id"],
        document_id=row["document_id"],
        source=row["source"],
        mention_text=row["mention_text"],
        context_snippet=row["context_snippet"],
        detected_at=iso_to_dt(row["detected_at"]),
        run_id=row["run_id"],
    )


def row_to_relationship(
    row: sqlite3.Row,
) -> Relationship:
    """Convert a ``sqlite3.Row`` to a Relationship."""
    return Relationship(
        source_id=row["source_id"],
        target_id=row["target_id"],
        relation_type=row["relation_type"],
        description=row["description"],
        qualifier_id=row["qualifier_id"],
        relation_kind_id=row["relation_kind_id"],
        valid_from=iso_to_dt(row["valid_from"]),
        valid_until=iso_to_dt(row["valid_until"]),
        document_id=row["document_id"],
        discovered_at=iso_to_dt(row["discovered_at"]),
        run_id=row["run_id"],
    )


def row_to_entity_rev(
    row: sqlite3.Row,
) -> EntityRevision:
    """Convert a ``sqlite3.Row`` to an EntityRevision."""
    aliases_raw = row["aliases"]
    aliases = (
        tuple(json.loads(aliases_raw))
        if aliases_raw
        else ()
    )
    return EntityRevision(
        revision_id=row["revision_id"],
        entity_id=row["entity_id"],
        operation=row["operation"],
        changed_at=datetime.fromisoformat(
            row["changed_at"]
        ),
        canonical_name=row["canonical_name"],
        entity_type=EntityType(row["entity_type"]),
        subtype=row["subtype"],
        description=row["description"],
        aliases=aliases,
        valid_from=iso_to_dt(row["valid_from"]),
        valid_until=iso_to_dt(row["valid_until"]),
        status=EntityStatus(row["status"]),
        merged_into=row["merged_into"],
        reason=row["reason"],
    )


def row_to_run(row: sqlite3.Row) -> IngestionRun:
    """Convert a ``sqlite3.Row`` to an IngestionRun."""
    return IngestionRun(
        run_id=row["run_id"],
        started_at=datetime.fromisoformat(
            row["started_at"]
        ),
        finished_at=iso_to_dt(row["finished_at"]),
        status=RunStatus(row["status"]),
        document_count=row["document_count"],
        entity_count=row["entity_count"],
        relationship_count=row["relationship_count"],
        error_message=row["error_message"],
    )


def row_to_relationship_rev(
    row: sqlite3.Row,
) -> RelationshipRevision:
    """Convert a ``sqlite3.Row`` to a RelationshipRevision."""
    return RelationshipRevision(
        revision_id=row["revision_id"],
        operation=row["operation"],
        changed_at=datetime.fromisoformat(
            row["changed_at"]
        ),
        source_id=row["source_id"],
        target_id=row["target_id"],
        relation_type=row["relation_type"],
        description=row["description"],
        qualifier_id=row["qualifier_id"],
        relation_kind_id=row["relation_kind_id"],
        valid_from=iso_to_dt(row["valid_from"]),
        valid_until=iso_to_dt(row["valid_until"]),
        document_id=row["document_id"],
        reason=row["reason"],
    )
