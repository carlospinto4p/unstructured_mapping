"""Data models for the knowledge graph.

This module defines the core entities, relationships, and
provenance records that make up the knowledge graph. The
design is LLM-first: the graph serves as a rich reference
catalog that an LLM reads and reasons over, rather than an
engine for algorithmic vector matching.

See ``DESIGN.md`` in this package for detailed rationale
behind every enum value, field choice, and deferred feature.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import uuid4


class EntityType(StrEnum):
    """Classification of knowledge graph entities.

    Four coarse-grained types chosen for news-domain
    entity mapping. Kept intentionally broad — the LLM
    uses :attr:`Entity.description` for finer-grained
    distinctions (e.g. "state-owned enterprise" within
    ORGANIZATION). Splitting into subtypes would make
    classification harder without improving LLM resolution.

    See ``DESIGN.md`` for why EVENT and CONCEPT were
    excluded and what each type covers.
    """

    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    TOPIC = "topic"


class EntityStatus(StrEnum):
    """Lifecycle state of an entity.

    :cvar ACTIVE: Entity is current and valid.
    :cvar MERGED: Entity was merged into another; see
        :attr:`Entity.merged_into` for the surviving ID.
    :cvar DEPRECATED: Entity is no longer relevant but
        kept for provenance history.
    """

    ACTIVE = "active"
    MERGED = "merged"
    DEPRECATED = "deprecated"


@dataclass(frozen=True, slots=True)
class Entity:
    """A knowledge graph entity.

    Represents a real-world thing (person, organization,
    place, or topic) that can be mentioned in text and
    resolved against the graph.

    :param entity_id: Unique identifier (UUID hex).
        Auto-generated when not provided.
    :param canonical_name: Authoritative display name.
    :param entity_type: Coarse classification.
    :param description: Natural-language context the LLM
        reads for resolution and disambiguation. Should
        include distinguishing details (role, country,
        founding year, etc.).
    :param aliases: Alternative surface forms used for
        detection (nicknames, abbreviations, translations).
        Stored as a tuple for immutability.
    :param valid_from: When this entity became relevant
        (e.g. founding date, birth date). ``None`` if
        unbounded.
    :param valid_until: When this entity ceased to be
        relevant (e.g. dissolution, death). ``None`` if
        still active.
    :param status: Lifecycle state. Defaults to ACTIVE.
    :param merged_into: If status is MERGED, the
        `entity_id` of the surviving entity. ``None``
        otherwise.
    :param created_at: When this record was created.
        Auto-populated when not provided.
    """

    canonical_name: str
    entity_type: EntityType
    description: str
    aliases: tuple[str, ...] = ()
    entity_id: str = field(
        default_factory=lambda: uuid4().hex
    )
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: EntityStatus = EntityStatus.ACTIVE
    merged_into: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Provenance:
    """Evidence that an entity was mentioned in a document.

    Links an entity to the specific document and text
    where it was detected. The `context_snippet` field is
    critical for LLM disambiguation — it provides
    surrounding text, not just the bare mention.

    :param entity_id: The entity that was mentioned.
    :param document_id: Links to the article by its
        `document_id` (see :class:`Article`). Uses a
        string FK rather than an object reference to
        avoid cross-module coupling — the KG can be
        populated from non-scraper sources (e.g.
        Wikidata) without importing the web_scraping
        module.
    :param source: News source name (e.g. ``"bbc"``).
    :param mention_text: Exact surface form found in
        the text (e.g. ``"MBS"``).
    :param context_snippet: Surrounding text for LLM
        disambiguation. Should include enough context
        to distinguish between entities with similar
        names.
    :param detected_at: When the detection occurred.
        ``None`` if not tracked.
    """

    entity_id: str
    document_id: str
    source: str
    mention_text: str
    context_snippet: str
    detected_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Relationship:
    """A directed relationship between two entities.

    Relationships are LLM-generated and open-ended —
    `relation_type` is a free-form string, not an enum,
    because the space of possible relationships in news
    is unbounded ("acquired", "invaded", "appointed",
    "sanctioned", etc.).

    Temporal bounds allow modeling time-limited
    relationships (e.g. "CEO of X from 2020 to 2023").
    Events are modeled as relationships with temporal
    bounds rather than as separate entity types.

    :param source_id: Subject entity `entity_id`.
    :param target_id: Object entity `entity_id`.
    :param relation_type: Free-form label describing
        the relationship (LLM-generated).
    :param description: Natural-language description
        providing context and nuance.
    :param valid_from: When the relationship started.
        ``None`` if unbounded.
    :param valid_until: When the relationship ended.
        ``None`` if still active.
    :param document_id: The document where this
        relationship was discovered. ``None`` if
        manually curated.
    :param discovered_at: When this relationship was
        first detected. ``None`` if not tracked.
    """

    source_id: str
    target_id: str
    relation_type: str
    description: str
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    document_id: str | None = None
    discovered_at: datetime | None = None
