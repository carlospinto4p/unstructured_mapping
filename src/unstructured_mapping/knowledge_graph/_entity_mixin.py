"""Composite entity mixin for KnowledgeStore.

Ties the four focused sub-mixins together into the single
:class:`EntityMixin` that
:class:`~unstructured_mapping.knowledge_graph.storage.KnowledgeStore`
inherits:

- :class:`~._entity_crud_mixin.EntityCRUDMixin` — save /
  get / find by name or alias.
- :class:`~._entity_search_mixin.EntitySearchMixin` —
  filtered queries (by type, status, prefix, recency)
  and aggregate counts.
- :class:`~._entity_merge_mixin.EntityMergeMixin` — merge
  two entities with FK redirection and audit trail.
- :class:`~._entity_history_mixin.EntityHistoryMixin` —
  revision history, point-in-time queries, and revert.

Internal helpers (alias sync, row conversion, audit
logging) live as module-level functions in
:mod:`._entity_helpers`.

Why four files: the four concerns are independently
readable, independently tested, and changing one no longer
scrolls past the others. Keeping the composite here
preserves the single ``EntityMixin`` import site used by
``storage.py``.
"""

from unstructured_mapping.knowledge_graph._entity_crud_mixin import (
    EntityCRUDMixin,
)
from unstructured_mapping.knowledge_graph._entity_history_mixin import (
    EntityHistoryMixin,
)
from unstructured_mapping.knowledge_graph._entity_merge_mixin import (
    EntityMergeMixin,
)
from unstructured_mapping.knowledge_graph._entity_search_mixin import (
    EntitySearchMixin,
)


class EntityMixin(
    EntityCRUDMixin,
    EntitySearchMixin,
    EntityMergeMixin,
    EntityHistoryMixin,
):
    """All entity operations, composed from sub-mixins.

    :class:`KnowledgeStore` inherits this single mixin
    to get the full entity API. The sub-mixins can also
    be used individually in tests or narrower contexts.
    """


__all__ = [
    "EntityCRUDMixin",
    "EntityHistoryMixin",
    "EntityMergeMixin",
    "EntityMixin",
    "EntitySearchMixin",
]
