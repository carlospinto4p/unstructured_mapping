"""Entity merge mixin.

Single-entry-point merge: redirect every foreign-key
reference from the deprecated entity to the surviving one,
mark the deprecated entity ``MERGED``, and log both sides
to the audit history inside one transaction. Split out of
:mod:`._entity_mixin` alongside the other entity
sub-mixins; see that module for the composite that
:class:`KnowledgeStore` actually inherits.
"""

import logging
from dataclasses import replace

from unstructured_mapping.knowledge_graph._entity_helpers import (
    EntityHelpersMixin,
)
from unstructured_mapping.knowledge_graph.exceptions import (
    EntityNotFound,
)
from unstructured_mapping.knowledge_graph.models import (
    EntityStatus,
)

logger = logging.getLogger(__name__)


class EntityMergeMixin(EntityHelpersMixin):
    """Merge two entities with FK redirection."""

    def merge_entities(
        self,
        deprecated_id: str,
        surviving_id: str,
    ) -> None:
        """Merge one entity into another.

        Updates all foreign key references (provenance,
        relationships) to point to the surviving entity,
        then marks the deprecated entity as MERGED.

        Both entities and all affected relationships are
        logged to the audit history.

        Runs in a single transaction for atomicity.

        :param deprecated_id: Entity to deprecate.
        :param surviving_id: Entity that absorbs the
            deprecated one.
        :raises EntityNotFound: If either entity is not
            found.
        """
        dep = self.get_entity(deprecated_id)
        surv = self.get_entity(surviving_id)
        if dep is None:
            raise EntityNotFound(deprecated_id)
        if surv is None:
            raise EntityNotFound(surviving_id)

        merge_reason = f"merged {deprecated_id} into {surviving_id}"

        self._redirect_entity_references(deprecated_id, surviving_id)
        self._conn.execute(
            "UPDATE entities SET status = ?, "
            "merged_into = ? WHERE entity_id = ?",
            ("merged", surviving_id, deprecated_id),
        )
        merged_dep = replace(
            dep,
            status=EntityStatus.MERGED,
            merged_into=surviving_id,
        )
        self._log_entity(merged_dep, "merge", merge_reason)
        self._log_entity(surv, "merge", merge_reason)
        self._commit()
        logger.info(
            "Merged entity %s into %s",
            deprecated_id,
            surviving_id,
        )
