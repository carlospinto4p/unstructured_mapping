"""Shared helpers for knowledge graph storage mixins.

Row converters, datetime utilities, and SQL fragment
constants used across :mod:`_entity_mixin`,
:mod:`_provenance_mixin`, :mod:`_relationship_mixin`,
and :mod:`_run_mixin`.
"""

import json
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
    row: tuple[
        str, str, str, str | None, str,
        str | None, str | None,
        str, str | None, str | None,
        str | None,
    ],
    aliases: tuple[str, ...],
) -> Entity:
    """Convert a raw entity row + aliases to an Entity."""
    return Entity(
        entity_id=row[0],
        canonical_name=row[1],
        entity_type=EntityType(row[2]),
        subtype=row[3],
        description=row[4],
        aliases=aliases,
        valid_from=iso_to_dt(row[5]),
        valid_until=iso_to_dt(row[6]),
        status=EntityStatus(row[7]),
        merged_into=row[8],
        created_at=iso_to_dt(row[9]),
        updated_at=iso_to_dt(row[10]),
    )


def row_to_provenance(
    row: tuple[
        str, str, str, str, str,
        str | None, str | None,
    ],
) -> Provenance:
    """Convert a raw provenance row to a Provenance."""
    return Provenance(
        entity_id=row[0],
        document_id=row[1],
        source=row[2],
        mention_text=row[3],
        context_snippet=row[4],
        detected_at=iso_to_dt(row[5]),
        run_id=row[6],
    )


def row_to_relationship(
    row: tuple[
        str, str, str, str,
        str | None, str | None,
        str | None, str | None,
        str | None, str | None,
        str | None,
    ],
) -> Relationship:
    """Convert a raw relationship row to a Relationship."""
    return Relationship(
        source_id=row[0],
        target_id=row[1],
        relation_type=row[2],
        description=row[3],
        qualifier_id=row[4],
        relation_kind_id=row[5],
        valid_from=iso_to_dt(row[6]),
        valid_until=iso_to_dt(row[7]),
        document_id=row[8],
        discovered_at=iso_to_dt(row[9]),
        run_id=row[10],
    )


def row_to_entity_rev(
    row: tuple[
        int, str, str, str, str, str,
        str | None, str, str | None,
        str | None, str | None,
        str, str | None, str | None,
    ],
) -> EntityRevision:
    """Convert a raw entity_history row to an EntityRevision."""
    aliases_raw = row[8]
    aliases = (
        tuple(json.loads(aliases_raw))
        if aliases_raw
        else ()
    )
    return EntityRevision(
        revision_id=row[0],
        entity_id=row[1],
        operation=row[2],
        changed_at=datetime.fromisoformat(row[3]),
        canonical_name=row[4],
        entity_type=EntityType(row[5]),
        subtype=row[6],
        description=row[7],
        aliases=aliases,
        valid_from=iso_to_dt(row[9]),
        valid_until=iso_to_dt(row[10]),
        status=EntityStatus(row[11]),
        merged_into=row[12],
        reason=row[13],
    )


def row_to_run(
    row: tuple[
        str, str, str | None, str,
        int, int, int, str | None,
    ],
) -> IngestionRun:
    """Convert a raw ingestion_runs row to an IngestionRun."""
    return IngestionRun(
        run_id=row[0],
        started_at=datetime.fromisoformat(row[1]),
        finished_at=iso_to_dt(row[2]),
        status=RunStatus(row[3]),
        document_count=row[4],
        entity_count=row[5],
        relationship_count=row[6],
        error_message=row[7],
    )


def row_to_relationship_rev(
    row: tuple[
        int, str, str, str, str,
        str, str, str | None,
        str | None, str | None,
        str | None, str | None,
        str | None,
    ],
) -> RelationshipRevision:
    """Convert a raw relationship_history row."""
    return RelationshipRevision(
        revision_id=row[0],
        operation=row[1],
        changed_at=datetime.fromisoformat(row[2]),
        source_id=row[3],
        target_id=row[4],
        relation_type=row[5],
        description=row[6],
        qualifier_id=row[7],
        relation_kind_id=row[8],
        valid_from=iso_to_dt(row[9]),
        valid_until=iso_to_dt(row[10]),
        document_id=row[11],
        reason=row[12],
    )
