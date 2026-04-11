"""KG validation — temporal, alias, and constraint checks.

Three categories of validation:

1. **Temporal consistency** — ``valid_until >= valid_from``
   on entities and relationships. Enforced at save time
   via :func:`validate_temporal`.
2. **Alias collision detection** — identifies aliases shared
   by multiple entities. Advisory (not enforced on save)
   via :func:`find_alias_collisions`.
3. **Relationship constraint checking** — validates that
   relationships match documented canonical patterns from
   ``docs/knowledge_graph/relationships.md``. Advisory
   via :func:`check_relationship_constraints` and
   :func:`audit_relationship_constraints`.

Why save-time for temporal, advisory for the rest?
    Temporal inconsistency is always a data error — an
    entity cannot expire before it begins. Alias
    collisions and relationship patterns have legitimate
    exceptions (shared aliases for ROLE entities, novel
    relationship types from the LLM), so blocking on
    save would be too aggressive.

See ``docs/knowledge_graph/validation.md`` for full
design rationale.
"""

import logging
import sqlite3
from dataclasses import dataclass

from unstructured_mapping.knowledge_graph.exceptions import (
    ValidationError,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityType,
    Relationship,
)

logger = logging.getLogger(__name__)


# -- Temporal consistency --------------------------------


def validate_temporal(
    obj: Entity | Relationship,
) -> None:
    """Check that ``valid_until >= valid_from``.

    Called from :meth:`KnowledgeStore.save_entity` and
    :meth:`KnowledgeStore.save_relationship` before the
    INSERT.

    :param obj: An ``Entity`` or ``Relationship`` with
        temporal bounds.
    :raises ValidationError: If ``valid_until`` is
        before ``valid_from``.
    """
    if (
        obj.valid_from is not None
        and obj.valid_until is not None
        and obj.valid_until < obj.valid_from
    ):
        kind = type(obj).__name__
        raise ValidationError(
            f"{kind} has valid_until "
            f"({obj.valid_until.isoformat()}) before "
            f"valid_from "
            f"({obj.valid_from.isoformat()})"
        )


# -- Alias collision detection ---------------------------


@dataclass(frozen=True, slots=True)
class AliasCollision:
    """An alias shared by multiple entities.

    :param alias: The conflicting alias text.
    :param entities: List of (entity_id, canonical_name,
        entity_type) tuples sharing the alias.
    """

    alias: str
    entities: tuple[
        tuple[str, str, str], ...
    ]


def find_alias_collisions(
    conn: sqlite3.Connection,
) -> list[AliasCollision]:
    """Find aliases shared by multiple entities.

    Queries the ``entity_aliases`` table for aliases
    that appear on two or more entities, grouped by
    case-insensitive alias text. Returns structured
    results for reporting.

    This is an advisory audit function — it does not
    block saves. Call it periodically or after bulk
    ingestion to detect potential conflicts.

    :param conn: SQLite connection to the KG database.
    :return: List of collisions, empty if none found.
    """
    rows = conn.execute(
        "SELECT a.alias, a.entity_id, "
        "e.canonical_name, e.entity_type "
        "FROM entity_aliases a "
        "JOIN entities e "
        "ON a.entity_id = e.entity_id "
        "WHERE a.alias IN ("
        "  SELECT alias FROM entity_aliases "
        "  GROUP BY alias COLLATE NOCASE "
        "  HAVING COUNT(DISTINCT entity_id) > 1"
        ") "
        "ORDER BY a.alias COLLATE NOCASE, "
        "e.canonical_name"
    ).fetchall()

    grouped: dict[
        str, list[tuple[str, str, str]]
    ] = {}
    for alias, eid, name, etype in rows:
        key = alias.lower()
        if key not in grouped:
            grouped[key] = []
        grouped[key].append((eid, name, etype))

    return [
        AliasCollision(
            alias=alias,
            entities=tuple(entities),
        )
        for alias, entities in grouped.items()
    ]


# -- Relationship constraint checking -------------------


@dataclass(frozen=True, slots=True)
class ConstraintWarning:
    """A relationship that doesn't match known patterns.

    :param source_id: Subject entity ID.
    :param target_id: Object entity ID.
    :param relation_type: The relationship label.
    :param source_type: Entity type of the source.
    :param target_type: Entity type of the target.
    :param message: Human-readable warning.
    """

    source_id: str
    target_id: str
    relation_type: str
    source_type: str
    target_type: str
    message: str


#: Canonical relationship patterns from
#: ``docs/knowledge_graph/relationships.md``.
#:
#: Each key is ``(source_type, target_type)`` and the
#: value is a frozenset of known ``relation_type``
#: strings for that entity type pair.
#:
#: This is not exhaustive — it covers the documented
#: conventions. Unknown patterns produce advisory
#: warnings, not errors.
RELATIONSHIP_CONSTRAINTS: dict[
    tuple[str, str], frozenset[str]
] = {
    ("asset", "organization"): frozenset({
        "issued_by", "managed_by", "listed_on",
        "component_of",
    }),
    ("asset", "asset"): frozenset({
        "tracks", "derived_from", "component_of",
    }),
    ("organization", "organization"): frozenset({
        "acquired", "merged_with", "spun_off",
        "competes_with", "supplies", "partners_with",
        "invests_in", "subsidiary_of", "parent_of",
        "listed_on", "ipo_on", "delisted_from",
        "managed_by", "member_of",
    }),
    ("organization", "legislation"): frozenset({
        "enforces", "sponsored_by",
    }),
    ("organization", "topic"): frozenset({
        "hosts", "classified_as",
    }),
    ("organization", "metric"): frozenset({
        "sets",
    }),
    ("organization", "place"): frozenset({
        "headquartered_in", "located_in",
    }),
    ("organization", "product"): frozenset({
        "approved", "grounded",
    }),
    ("organization", "asset"): frozenset({
        "covers",
    }),
    ("person", "organization"): frozenset({
        "works_at", "employed_by", "leads",
        "appointed_at", "departed_from", "founded",
    }),
    ("person", "asset"): frozenset({
        "covers",
    }),
    ("legislation", "organization"): frozenset({
        "targets", "applies_to", "sponsored_by",
    }),
    ("legislation", "place"): frozenset({
        "targets", "applies_to",
    }),
    ("metric", "organization"): frozenset({
        "issued_by", "set_by",
    }),
    ("metric", "place"): frozenset({
        "measures",
    }),
    ("product", "organization"): frozenset({
        "manufactured_by",
    }),
    ("product", "product"): frozenset({
        "competes_with", "runs_on",
    }),
    ("topic", "metric"): frozenset({
        "triggers",
    }),
    ("topic", "topic"): frozenset({
        "affects",
    }),
    ("topic", "asset"): frozenset({
        "affects",
    }),
    ("place", "place"): frozenset({
        "member_of",
    }),
    ("place", "organization"): frozenset({
        "member_of",
    }),
    ("asset", "topic"): frozenset({
        "belongs_to",
    }),
}


def check_relationship_constraints(
    relation_type: str,
    source_type: EntityType,
    target_type: EntityType,
) -> list[str]:
    """Check a relationship against known patterns.

    Returns a list of warning strings if the
    relationship does not match any documented canonical
    pattern. An empty list means the pattern is known.

    This does not validate whether the relationship is
    *wrong* — free-form relationship types are
    intentionally open-ended. It flags relationships
    that don't match documented conventions for review.

    :param relation_type: The relationship label.
    :param source_type: Entity type of the source.
    :param target_type: Entity type of the target.
    :return: List of warnings (empty if pattern is
        known).
    """
    key = (source_type.value, target_type.value)
    known = RELATIONSHIP_CONSTRAINTS.get(key)
    if known is None:
        return [
            f"No known patterns for "
            f"{source_type.value} -> "
            f"{target_type.value}"
        ]
    if relation_type not in known:
        return [
            f"Unknown relation_type "
            f"'{relation_type}' for "
            f"{source_type.value} -> "
            f"{target_type.value}. "
            f"Known types: "
            f"{', '.join(sorted(known))}"
        ]
    return []


def audit_relationship_constraints(
    conn: sqlite3.Connection,
) -> list[ConstraintWarning]:
    """Scan all relationships for constraint violations.

    Joins relationships with source/target entity types
    and checks each against
    :data:`RELATIONSHIP_CONSTRAINTS`. Returns warnings
    for relationships that don't match documented
    patterns.

    :param conn: SQLite connection to the KG database.
    :return: List of warnings, empty if all match.
    """
    rows = conn.execute(
        "SELECT r.source_id, r.target_id, "
        "r.relation_type, "
        "s.entity_type AS source_type, "
        "t.entity_type AS target_type "
        "FROM relationships r "
        "JOIN entities s "
        "ON r.source_id = s.entity_id "
        "JOIN entities t "
        "ON r.target_id = t.entity_id"
    ).fetchall()

    warnings: list[ConstraintWarning] = []
    for (
        source_id,
        target_id,
        relation_type,
        source_type,
        target_type,
    ) in rows:
        try:
            st = EntityType(source_type)
            tt = EntityType(target_type)
        except ValueError:
            continue
        issues = check_relationship_constraints(
            relation_type, st, tt
        )
        for msg in issues:
            warnings.append(
                ConstraintWarning(
                    source_id=source_id,
                    target_id=target_id,
                    relation_type=relation_type,
                    source_type=source_type,
                    target_type=target_type,
                    message=msg,
                )
            )
    return warnings
