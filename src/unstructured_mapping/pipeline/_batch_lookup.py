"""Batch-vs-single entity lookup helper.

The LLM resolver and relationship extractor both need to
turn a list of candidate entity IDs into a
``{id: Entity}`` mapping before the LLM call. In
production both are wired with
``KnowledgeStore.get_entities`` — one ``WHERE id IN (...)``
query per chunk. Tests and smaller callers sometimes only
have the single-id ``get_entity``; this module wraps that
case so the two call sites stop carrying their own copy of
the fallback.

The fallback is still ``N`` SQL calls by construction —
there is no way to synthesise a batch out of a
one-at-a-time callable. Having a single helper makes the
cost visible (``logger.debug`` records every fallback)
and keeps the two hot-path sites focused on their LLM
work instead of conditional lookup plumbing.
"""

import logging
from collections.abc import Callable

from unstructured_mapping.knowledge_graph.models import (
    Entity,
)

logger = logging.getLogger(__name__)


def resolve_batch(
    ids: list[str],
    *,
    single: Callable[[str], Entity | None],
    batch: Callable[[list[str]], dict[str, Entity]] | None,
) -> dict[str, Entity]:
    """Fetch every id via ``batch`` when available, else ``single``.

    :param ids: Entity IDs to resolve. Duplicates are
        tolerated — the caller's dedup (if any) owns the
        input shape.
    :param single: Per-id fallback used when ``batch`` is
        ``None``. Typically ``KnowledgeStore.get_entity``.
    :param batch: Preferred bulk lookup. Typically
        ``KnowledgeStore.get_entities``. When supplied the
        helper fires one query; when ``None`` it falls
        back to ``N`` calls through ``single``.
    :return: ``{id: Entity}`` for every id that resolved.
        Missing ids are silently absent — callers keep
        the "candidate may have been deleted" semantics
        they already had.
    """
    if not ids:
        return {}
    if batch is not None:
        return batch(ids)
    logger.debug(
        "Falling back to %d per-id entity lookups; "
        "wire entity_batch_lookup for one bulk query",
        len(ids),
    )
    return {eid: ent for eid in ids if (ent := single(eid)) is not None}
