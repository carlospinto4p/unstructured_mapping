"""Knowledge graph module for entity mapping.

See ``docs/knowledge_graph/`` for detailed rationale
behind the data model, enum values, and deferred features.
"""

from unstructured_mapping.knowledge_graph.exceptions import (
    EntityNotFound,
    KnowledgeGraphError,
    ResolutionAmbiguous,
    RevisionNotFound,
    ValidationError,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityRevision,
    EntityStatus,
    EntityType,
    IngestionRun,
    Provenance,
    Relationship,
    RelationshipRevision,
    RunMetrics,
    RunStatus,
)
from unstructured_mapping.knowledge_graph.storage import (
    KnowledgeStore,
)
from unstructured_mapping.knowledge_graph.validation import (
    AliasCollision,
    ConstraintWarning,
    audit_relationship_constraints,
    check_relationship_constraints,
    find_alias_collisions,
    validate_temporal,
)

__all__ = [
    "AliasCollision",
    "Entity",
    "EntityNotFound",
    "EntityRevision",
    "EntityStatus",
    "EntityType",
    "IngestionRun",
    "KnowledgeGraphError",
    "KnowledgeStore",
    "Provenance",
    "Relationship",
    "RelationshipRevision",
    "ResolutionAmbiguous",
    "RevisionNotFound",
    "RunMetrics",
    "RunStatus",
    "ConstraintWarning",
    "ValidationError",
    "audit_relationship_constraints",
    "check_relationship_constraints",
    "find_alias_collisions",
    "validate_temporal",
]
