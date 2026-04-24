"""Entity history / audit-trail mixin.

Revision history reads, point-in-time queries, and the
``revert_entity`` helper that restores a prior snapshot via
``save_entity``. Split out of :mod:`._entity_mixin`
alongside the other entity sub-mixins; see that module for
the composite that :class:`KnowledgeStore` actually
inherits.
"""

from datetime import datetime

from unstructured_mapping.knowledge_graph._entity_helpers import (
    EntityHelpersMixin,
)
from unstructured_mapping.knowledge_graph._helpers import (
    dt_to_iso,
    row_to_entity_rev,
)
from unstructured_mapping.knowledge_graph.exceptions import (
    RevisionNotFound,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityRevision,
)


class EntityHistoryMixin(EntityHelpersMixin):
    """Revision history, point-in-time queries, revert."""

    def find_entity_history(self, entity_id: str) -> list[EntityRevision]:
        """Fetch all revisions for an entity.

        Returns revisions in chronological order
        (oldest first).

        :param entity_id: The entity's unique identifier.
        :return: List of revisions.
        """
        rows = self._conn.execute(
            "SELECT history_id, entity_id, operation,"
            " changed_at, canonical_name, entity_type,"
            " subtype, description, aliases, "
            "valid_from, valid_until, status, "
            "merged_into, reason "
            "FROM entity_history "
            "WHERE entity_id = ? "
            "ORDER BY history_id",
            (entity_id,),
        ).fetchall()
        return [row_to_entity_rev(r) for r in rows]

    #: Back-compat alias for the canonical
    #: :meth:`find_entity_history`.
    get_entity_history = find_entity_history

    def get_entity_at(
        self,
        entity_id: str,
        at: datetime,
    ) -> EntityRevision | None:
        """Fetch an entity's state at a point in time.

        Returns the latest revision with
        ``changed_at <= at``.

        :param entity_id: The entity's unique identifier.
        :param at: The point in time to query.
        :return: The revision, or ``None`` if the entity
            did not exist at that time.
        """
        row = self._conn.execute(
            "SELECT history_id, entity_id, operation,"
            " changed_at, canonical_name, entity_type,"
            " subtype, description, aliases, "
            "valid_from, valid_until, status, "
            "merged_into, reason "
            "FROM entity_history "
            "WHERE entity_id = ? "
            "AND changed_at <= ? "
            "ORDER BY history_id DESC LIMIT 1",
            (entity_id, dt_to_iso(at)),
        ).fetchone()
        if row is None:
            return None
        return row_to_entity_rev(row)

    def revert_entity(self, entity_id: str, history_id: int) -> Entity:
        """Revert an entity to a previous revision.

        Copies the snapshot from ``entity_history`` back
        to ``entities`` and logs a ``"revert"`` operation
        in the audit trail.

        :param entity_id: The entity to revert.
        :param history_id: The revision to restore.
        :return: The restored entity.
        :raises RevisionNotFound: If the revision is not
            found or belongs to a different entity.
        """
        row = self._conn.execute(
            "SELECT history_id, entity_id, operation,"
            " changed_at, canonical_name, entity_type,"
            " subtype, description, aliases, "
            "valid_from, valid_until, status, "
            "merged_into, reason "
            "FROM entity_history "
            "WHERE history_id = ? "
            "AND entity_id = ?",
            (history_id, entity_id),
        ).fetchone()
        if row is None:
            raise RevisionNotFound(history_id, entity_id)
        rev = row_to_entity_rev(row)
        restored = Entity(
            entity_id=rev.entity_id,
            canonical_name=rev.canonical_name,
            entity_type=rev.entity_type,
            subtype=rev.subtype,
            description=rev.description,
            aliases=rev.aliases,
            valid_from=rev.valid_from,
            valid_until=rev.valid_until,
            status=rev.status,
            merged_into=rev.merged_into,
        )
        self.save_entity(
            restored,
            reason=f"reverted to revision {history_id}",
            _operation="revert",
        )
        return restored
