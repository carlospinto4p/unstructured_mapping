"""Data models for the knowledge graph.

This module defines the core entities, relationships, and
provenance records that make up the knowledge graph. The
design is LLM-first: the graph serves as a rich reference
catalog that an LLM reads and reasons over, rather than an
engine for algorithmic vector matching.

See ``docs/knowledge_graph/`` for detailed rationale
behind every enum value, field choice, and deferred feature.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4


class EntityType(StrEnum):
    """Classification of knowledge graph entities.

    Ten types for financial-news entity mapping. The first
    eight (PERSON through METRIC) classify real-world
    things. ROLE and RELATION_KIND are meta-types that
    enable structured querying and synonym resolution by
    reusing the entity/alias system.

    See ``docs/knowledge_graph/`` for why EVENT was
    excluded and what each type covers.
    """

    PERSON = "person"
    ORGANIZATION = "organization"
    PLACE = "place"
    TOPIC = "topic"
    PRODUCT = "product"
    LEGISLATION = "legislation"
    ASSET = "asset"
    METRIC = "metric"
    ROLE = "role"
    RELATION_KIND = "relation_kind"


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

    Represents a real-world thing that can be mentioned
    in text and resolved against the graph. See
    :class:`EntityType` for the ten supported types.

    :param entity_id: Unique identifier (UUID hex).
        Auto-generated when not provided.
    :param canonical_name: Authoritative display name.
    :param entity_type: Coarse classification.
    :param subtype: Optional finer classification within
        the entity type (e.g. ``"company"`` for
        ORGANIZATION, ``"equity"`` for ASSET). Free-form
        string — not an enum — to avoid combinatorial
        explosion. Used as a routing hint for the LLM
        and for structured filtering.
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
    :param updated_at: When this record was last modified.
        ``None`` until the first update. Used for cache
        invalidation and freshness tracking.
    """

    canonical_name: str
    entity_type: EntityType
    description: str
    subtype: str | None = None
    aliases: tuple[str, ...] = ()
    entity_id: str = field(default_factory=lambda: uuid4().hex)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: EntityStatus = EntityStatus.ACTIVE
    merged_into: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


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
    :param run_id: Optional FK to ``ingestion_runs.run_id``.
        Links this record to the pipeline run that created
        it, replacing timestamp-based correlation.
    """

    entity_id: str
    document_id: str
    source: str
    mention_text: str
    context_snippet: str
    detected_at: datetime | None = None
    run_id: str | None = None


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
    :param qualifier_id: Optional FK to an entity
        (typically ROLE) that qualifies the
        relationship. Solves n-ary relationships:
        Person→Company qualified by CTO role.
    :param relation_kind_id: Optional FK to a
        RELATION_KIND entity for normalized lookup.
        The raw `relation_type` string is kept as-is;
        this provides canonical grouping so synonyms
        like "works_at" / "employed_by" resolve to
        the same kind.
    :param valid_from: When the relationship started.
        ``None`` if unbounded.
    :param valid_until: When the relationship ended.
        ``None`` if still active.
    :param document_id: The document where this
        relationship was discovered. ``None`` if
        manually curated.
    :param discovered_at: When this relationship was
        first detected. ``None`` if not tracked.
    :param run_id: Optional FK to ``ingestion_runs.run_id``.
        Links this record to the pipeline run that created
        it, replacing timestamp-based correlation.
    :param confidence: LLM-reported confidence in the
        relationship, clamped to [0.0, 1.0]. ``None`` when
        the extractor did not report a score (e.g. older
        runs, rule-based sources, or the LLM omitted the
        field). Downstream filters (e.g.
        ``find_relationships(min_confidence=...)``) use
        this to drop weak extractions without re-reading
        the source text.
    """

    source_id: str
    target_id: str
    relation_type: str
    description: str
    qualifier_id: str | None = None
    relation_kind_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    document_id: str | None = None
    discovered_at: datetime | None = None
    run_id: str | None = None
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class EntityRevision:
    """A snapshot of an entity at a point in time.

    Written to the ``entity_history`` audit log on every
    create, update, or merge operation. The full entity
    state (including aliases as a JSON list) is captured
    so any revision can be restored without loss.

    :param history_id: Auto-incremented primary key.
    :param entity_id: The entity this revision belongs to.
    :param operation: What triggered the snapshot:
        ``"create"``, ``"update"``, ``"merge"``,
        or ``"revert"``.
    :param changed_at: When the operation occurred.
    :param canonical_name: Entity name at this revision.
    :param entity_type: Entity type at this revision.
    :param subtype: Subtype at this revision.
    :param description: Description at this revision.
    :param aliases: Aliases at this revision.
    :param valid_from: Temporal lower bound.
    :param valid_until: Temporal upper bound.
    :param status: Lifecycle status at this revision.
    :param merged_into: Merge target, if applicable.
    :param reason: Optional free-text explanation
        (e.g. ``"merged duplicate"``).
    """

    history_id: int
    entity_id: str
    operation: str
    changed_at: datetime
    canonical_name: str
    entity_type: EntityType
    subtype: str | None
    description: str
    aliases: tuple[str, ...]
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    status: EntityStatus = EntityStatus.ACTIVE
    merged_into: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RelationshipRevision:
    """A snapshot of a relationship at a point in time.

    Written to the ``relationship_history`` audit log on
    every create or merge-redirect operation.

    :param history_id: Auto-incremented primary key.
    :param operation: What triggered the snapshot.
    :param changed_at: When the operation occurred.
    :param source_id: Subject entity at this revision.
    :param target_id: Object entity at this revision.
    :param relation_type: Relationship label.
    :param description: Context at this revision.
    :param qualifier_id: Qualifier FK at this revision.
    :param relation_kind_id: Kind FK at this revision.
    :param valid_from: Temporal lower bound.
    :param valid_until: Temporal upper bound.
    :param document_id: Originating document.
    :param reason: Optional free-text explanation.
    """

    history_id: int
    operation: str
    changed_at: datetime
    source_id: str
    target_id: str
    relation_type: str
    description: str
    qualifier_id: str | None = None
    relation_kind_id: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    document_id: str | None = None
    reason: str | None = None


class RunStatus(StrEnum):
    """Lifecycle state of an ingestion run.

    :cvar RUNNING: Run is currently in progress.
    :cvar COMPLETED: Run finished successfully.
    :cvar FAILED: Run terminated with an error.
    """

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class IngestionRun:
    """Metadata for a single pipeline execution.

    Groups provenance and relationship records created
    during one invocation of the ingestion pipeline,
    replacing timestamp-based correlation with an
    explicit foreign key.

    :param run_id: Unique identifier (UUID hex).
        Auto-generated when not provided.
    :param started_at: When the run began. Auto-populated
        with the current UTC time when not provided.
    :param finished_at: When the run ended. ``None`` while
        the run is in progress.
    :param status: Lifecycle state of the run.
    :param document_count: Number of documents processed.
    :param entity_count: Number of entity mention
        provenance records created (not distinct entities).
    :param relationship_count: Number of relationships
        extracted.
    :param error_message: Error details if the run failed.
        ``None`` on success.
    """

    status: RunStatus = RunStatus.RUNNING
    run_id: str = field(default_factory=lambda: uuid4().hex)
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: datetime | None = None
    document_count: int = 0
    entity_count: int = 0
    relationship_count: int = 0
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """Per-run scorecard — pipeline quality and throughput.

    Keyed on :class:`IngestionRun.run_id`; one row per
    run. Captures what the run actually *did* at each
    stage, so runs can be compared across prompt
    revisions, provider swaps, and cold-start vs
    KG-driven modes without replaying the articles.

    Written at the end of a run alongside
    :class:`IngestionRun` finalisation. Token counters
    (``input_tokens``, ``output_tokens``) are summed over
    every LLM call the pipeline made during the run —
    resolver, extractor, and cold-start discoverer.
    Providers that do not expose usage (e.g. fakes in
    tests) leave these at zero.

    :param run_id: Foreign key to :class:`IngestionRun`.
    :param chunks_processed: Total chunks seen across all
        articles. Equal to ``document_count`` when no
        segmenter is active; higher otherwise.
    :param mentions_detected: Sum of the detector's
        output over every chunk.
    :param mentions_resolved_alias: Mentions the rule-
        based :class:`EntityResolver` resolved without an
        LLM call.
    :param mentions_resolved_llm: Mentions the LLM
        cascade resolved after the alias resolver left
        them unresolved.
    :param llm_resolver_calls: Number of times the LLM
        resolver was invoked (one call per chunk that
        contained unresolved mentions).
    :param llm_extractor_calls: Number of times the LLM
        relationship extractor was invoked (one call per
        chunk that had resolved mentions to feed it).
    :param proposals_saved: New entities created from LLM
        proposals during the run.
    :param relationships_saved: Relationships persisted.
    :param provider_name: LLM provider identifier at run
        time (``"ollama"``, ``"claude"``, ...). ``None``
        when no LLM stage was configured.
    :param model_name: Model identifier at run time.
        ``None`` when no LLM stage was configured.
    :param wall_clock_seconds: Total wall-clock time for
        the run, end-to-end.
    :param input_tokens: Prompt tokens summed across every
        LLM call (resolver, extractor, cold-start
        discoverer). Zero when the provider does not
        expose usage.
    :param output_tokens: Completion tokens summed across
        every LLM call. Zero when the provider does not
        expose usage.
    """

    run_id: str
    chunks_processed: int = 0
    mentions_detected: int = 0
    mentions_resolved_alias: int = 0
    mentions_resolved_llm: int = 0
    llm_resolver_calls: int = 0
    llm_extractor_calls: int = 0
    proposals_saved: int = 0
    relationships_saved: int = 0
    provider_name: str | None = None
    model_name: str | None = None
    wall_clock_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Sum of :attr:`input_tokens` and
        :attr:`output_tokens`."""
        return self.input_tokens + self.output_tokens
