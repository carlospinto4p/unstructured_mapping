"""Custom exceptions for the knowledge graph module.

Replaces generic ``ValueError`` with domain-specific
exceptions so callers can catch and handle specific
failure modes (e.g. entity not found vs ambiguous
resolution).
"""


class KnowledgeGraphError(Exception):
    """Base exception for all KG operations."""


class EntityNotFound(KnowledgeGraphError):
    """Raised when a referenced entity does not exist.

    :param entity_id: The ID that was not found.
    """

    def __init__(self, entity_id: str) -> None:
        self.entity_id = entity_id
        super().__init__(
            f"entity '{entity_id}' not found"
        )


class RevisionNotFound(KnowledgeGraphError):
    """Raised when a revision does not exist.

    :param revision_id: The revision ID that was not
        found.
    :param entity_id: The entity the revision was
        expected to belong to.
    """

    def __init__(
        self, revision_id: int, entity_id: str
    ) -> None:
        self.revision_id = revision_id
        self.entity_id = entity_id
        super().__init__(
            f"revision {revision_id} not found "
            f"for entity '{entity_id}'"
        )


class ResolutionAmbiguous(KnowledgeGraphError):
    """Raised when entity resolution finds multiple candidates.

    :param mention: The surface form that matched
        multiple entities.
    :param candidates: Entity IDs of the candidates.
    """

    def __init__(
        self,
        mention: str,
        candidates: list[str],
    ) -> None:
        self.mention = mention
        self.candidates = candidates
        super().__init__(
            f"ambiguous resolution for '{mention}': "
            f"{len(candidates)} candidates"
        )


class ValidationError(KnowledgeGraphError):
    """Raised when KG data fails validation checks.

    Covers temporal consistency, alias collisions,
    and relationship constraint violations.
    """
