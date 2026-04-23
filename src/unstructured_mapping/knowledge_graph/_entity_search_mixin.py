"""Entity search / filtered-query mixin.

Type/subtype/status/prefix lookups plus aggregate counts
and the ``find_entities_since`` recency query. Split out
of :mod:`._entity_mixin` alongside the other entity
sub-mixins; see that module for the composite that
:class:`KnowledgeStore` actually inherits.
"""

from datetime import datetime

from unstructured_mapping.knowledge_graph._entity_helpers import (
    EntityHelpersMixin,
)
from unstructured_mapping.knowledge_graph._helpers import (
    dt_to_iso,
)
from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityStatus,
    EntityType,
)


class EntitySearchMixin(EntityHelpersMixin):
    """Filtered entity queries and aggregate counts."""

    def find_entities_by_type(
        self,
        entity_type: EntityType,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find all entities of a given type.

        :param entity_type: The type to filter by.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned. Large KGs should pass a bound to
            avoid loading unbounded result sets and
            unnecessary alias lookups.
        :return: Matching entities.
        """
        return self._find_entities_where(
            "entity_type = ?",
            [entity_type.value],
            limit=limit,
        )

    def find_entities_by_subtype(
        self,
        entity_type: EntityType,
        subtype: str,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find entities by type and subtype.

        :param entity_type: The type to filter by.
        :param subtype: The subtype to filter by.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned.
        :return: Matching entities.
        """
        return self._find_entities_where(
            "entity_type = ? AND subtype = ?",
            [entity_type.value, subtype],
            limit=limit,
        )

    def find_entities_by_status(
        self,
        status: EntityStatus,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find all entities with a given status.

        Useful for listing only ACTIVE entities or finding
        all MERGED/DEPRECATED ones.

        :param status: The status to filter by.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned.
        :return: Matching entities.
        """
        return self._find_entities_where(
            "status = ?",
            [status.value],
            limit=limit,
        )

    def find_by_name_prefix(
        self,
        prefix: str,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find entities whose name starts with a prefix.

        Case-insensitive prefix search for
        autocomplete/typeahead lookups.

        :param prefix: The prefix to match against
            ``canonical_name``.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned. Typeahead callers typically pass a
            small bound (e.g. 10).
        :return: Matching entities.
        """
        return self._find_entities_where(
            "canonical_name COLLATE NOCASE LIKE ? || '%'",
            [prefix],
            limit=limit,
        )

    def count_entities_by_type(
        self,
    ) -> dict[str, int]:
        """Count entities grouped by type.

        Returns a mapping of entity type to count,
        useful for dashboard stats without fetching
        all rows.

        :return: Mapping of type string to count.
        """
        rows = self._conn.execute(
            "SELECT entity_type, COUNT(*) FROM entities GROUP BY entity_type"
        ).fetchall()
        return {t: c for t, c in rows}

    def find_entities_since(
        self,
        since: datetime,
        limit: int | None = None,
    ) -> list[Entity]:
        """Find entities created after a given time.

        Returns entities with ``created_at >= since``,
        ordered most recent first. Useful for new-entity
        monitoring ("what was added to the KG today?").

        :param since: Only return entities created at or
            after this datetime.
        :param limit: Maximum number of rows to return.
            When ``None`` (the default), all matches are
            returned.
        :return: Matching entities, newest first.
        """
        return self._find_entities_where(
            "created_at >= ?",
            [dt_to_iso(since)],
            suffix="ORDER BY created_at DESC",
            limit=limit,
        )
