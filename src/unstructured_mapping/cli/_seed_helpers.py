"""Shared plumbing for seed-loader CLIs.

Both :mod:`cli.seed` (curated JSON seeds) and
:mod:`cli.wikidata_seed` (Wikidata SPARQL imports) run
the same idempotent-save loop: iterate candidates, skip
duplicates, persist the rest, and return per-type counts.
The loaders only differ in how they produce an
:class:`Entity` from each candidate and how they detect
duplicates.

This module factors the common loop out so adding a new
seed source (CSV importer, LLM-extracted drafts, …) is a
matter of supplying the three small callbacks rather than
copy-pasting the loop body.
"""

from collections.abc import Callable, Iterable
from collections import Counter
from typing import TypeVar

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeStore,
)

T = TypeVar("T")


def exists_by_name_and_type(
    store: KnowledgeStore,
    name: str,
    entity_type: EntityType,
) -> bool:
    """Return True if an entity with this name+type exists.

    Matching on the canonical name is case-insensitive,
    mirroring :meth:`KnowledgeStore.find_by_name`. This is
    the fallback idempotency check for both seed loaders:
    curated seeds have no Wikidata QID, and the Wikidata
    loader also falls back to this check after the primary
    ``wikidata:Qxxx`` alias hit.
    """
    matches = store.find_by_name(name)
    return any(
        e.entity_type == entity_type for e in matches
    )


def import_with_dedup(
    items: Iterable[T],
    store: KnowledgeStore,
    *,
    get_entity: Callable[[T], Entity],
    is_duplicate: Callable[[KnowledgeStore, T], bool],
    counter_key: Callable[[Entity], str],
    reason: str,
    dry_run: bool = False,
) -> tuple[int, int, Counter]:
    """Persist ``items``, skipping duplicates.

    :param items: Candidate records. The loop is typed
        generically so callers can pass raw mapped
        structures (e.g. ``MappedEntity``) or plain
        :class:`Entity` instances.
    :param store: Target knowledge store.
    :param get_entity: Produce the :class:`Entity` that
        should be persisted for a given candidate — used
        only on non-duplicates, so the caller can keep
        mapping work lazy.
    :param is_duplicate: Return True if this candidate is
        already represented in the store. Runs before
        ``get_entity`` for efficiency.
    :param counter_key: Derive the bucket (usually the
        entity type or subtype string) under which the
        created entity is counted.
    :param reason: ``entity_history.reason`` tag attached
        to every new write.
    :param dry_run: When True, run the dedup loop without
        writing.
    :return: ``(created, skipped, counts)`` where
        ``counts`` is a :class:`Counter` keyed by
        ``counter_key(entity)``.
    """
    created = 0
    skipped = 0
    counts: Counter = Counter()
    for item in items:
        if is_duplicate(store, item):
            skipped += 1
            continue
        entity = get_entity(item)
        if not dry_run:
            store.save_entity(entity, reason=reason)
        created += 1
        counts[counter_key(entity)] += 1
    return created, skipped, counts
