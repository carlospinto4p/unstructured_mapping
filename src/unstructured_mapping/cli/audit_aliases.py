"""Audit alias collisions in the KG and propose merges.

Wraps :func:`knowledge_graph.validation.find_alias_collisions`
with two practical affordances:

1. **Prevalence-weighted ranking.** Collisions between
   entities that actually get mentioned are more urgent
   than collisions between entities that never show up
   in provenance. The CLI joins each side of a collision
   against the provenance table and orders the report by
   total mention count.
2. **Same-type merge proposals.** When every entity
   sharing an alias has the same ``entity_type``, the
   collision is almost certainly a duplicate — the alias
   just happens to be authoritative for two rows of the
   same kind. The CLI proposes merging into the most-
   mentioned entity (ties broken by canonical name) and
   offers an interactive confirm in ``--apply`` mode.

Cross-type collisions (e.g. alias ``"Apple"`` shared by
an ``organization`` and a ``product``) are never
auto-proposed; they are reported for human inspection.

Usage::

    # Dry-run report, ordered by prevalence.
    uv run python -m unstructured_mapping.cli.audit_aliases \\
        --db data/knowledge.db

    # Interactive merges for same-type collisions.
    uv run python -m unstructured_mapping.cli.audit_aliases \\
        --db data/knowledge.db --apply

The tool never merges without explicit confirmation.
``--auto-confirm`` skips the per-collision prompt only
when ``--apply`` is also set — this is the escape hatch
for scripted cleanup after a human has reviewed the
dry-run report.
"""

import argparse
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)
from unstructured_mapping.knowledge_graph.validation import (
    AliasCollision,
    find_alias_collisions,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ScoredEntity:
    """Side of a collision enriched with mention count."""

    entity_id: str
    canonical_name: str
    entity_type: str
    mention_count: int


@dataclass(frozen=True, slots=True)
class ScoredCollision:
    """One collision ranked by total mention prevalence."""

    alias: str
    entities: tuple[ScoredEntity, ...]

    @property
    def total_mentions(self) -> int:
        return sum(e.mention_count for e in self.entities)

    @property
    def same_type(self) -> bool:
        """All sides share the same ``entity_type``.

        The merge proposal is only generated for
        same-type collisions — cross-type overlaps
        (``Apple`` as organization + product) are
        legitimate.
        """
        if not self.entities:
            return False
        first = self.entities[0].entity_type
        return all(e.entity_type == first for e in self.entities)

    @property
    def merge_target(self) -> ScoredEntity | None:
        """The entity to keep after a merge.

        Picks the most-mentioned side, tie-breaking on
        canonical name (alphabetical). ``None`` when the
        collision is cross-type; callers must gate merge
        actions on :attr:`same_type`.
        """
        if not self.same_type:
            return None
        # Sort mutates a list copy; primary key is
        # mention count (descending), secondary is name
        # (ascending) for stable output.
        ranked = sorted(
            self.entities,
            key=lambda e: (
                -e.mention_count,
                e.canonical_name,
            ),
        )
        return ranked[0] if ranked else None


def score_collisions(
    store: KnowledgeStore,
    collisions: list[AliasCollision],
) -> list[ScoredCollision]:
    """Enrich raw collisions with per-entity mention counts.

    Emits one :class:`ScoredCollision` per input
    collision, with entities sorted by mention count
    (descending) so the merge target is always at index
    zero for same-type collisions.
    """
    scored: list[ScoredCollision] = []
    for c in collisions:
        scored_entities = [
            ScoredEntity(
                entity_id=eid,
                canonical_name=name,
                entity_type=etype,
                mention_count=(store.count_mentions_for_entity(eid)),
            )
            for eid, name, etype in c.entities
        ]
        scored_entities.sort(
            key=lambda e: (
                -e.mention_count,
                e.canonical_name,
            )
        )
        scored.append(
            ScoredCollision(
                alias=c.alias,
                entities=tuple(scored_entities),
            )
        )
    scored.sort(key=lambda c: -c.total_mentions)
    return scored


def format_collision(c: ScoredCollision) -> str:
    lines = [
        f"alias={c.alias!r}  "
        f"total_mentions={c.total_mentions}  "
        f"same_type={c.same_type}",
    ]
    for e in c.entities:
        marker = ""
        if c.same_type and e is c.merge_target:
            marker = "  <- keep"
        lines.append(
            f"  [{e.entity_type}] "
            f"{e.canonical_name}  "
            f"({e.entity_id})  "
            f"mentions={e.mention_count}"
            f"{marker}"
        )
    return "\n".join(lines)


def _confirm(prompt: str) -> bool:
    """Return True on explicit 'y' / 'yes' input.

    Any other answer, EOF, or non-interactive stdin
    returns ``False`` — the CLI never merges unless the
    operator types yes.
    """
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return False
    return answer in ("y", "yes")


def _apply_merges(
    store: KnowledgeStore,
    collisions: list[ScoredCollision],
    *,
    auto_confirm: bool,
) -> int:
    merged = 0
    for c in collisions:
        if not c.same_type:
            continue
        target = c.merge_target
        if target is None:
            continue
        losers = [e for e in c.entities if e.entity_id != target.entity_id]
        if not losers:
            continue
        logger.info(
            "Proposed merge for alias %r: keep %s "
            "(mentions=%d), merge %d other(s) into it.",
            c.alias,
            target.canonical_name,
            target.mention_count,
            len(losers),
        )
        if not auto_confirm:
            if not _confirm(f"Merge into {target.canonical_name}? [y/N] "):
                logger.info("Skipped alias %r", c.alias)
                continue
        for loser in losers:
            store.merge_entities(
                deprecated_id=loser.entity_id,
                surviving_id=target.entity_id,
            )
            merged += 1
    return merged


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Audit alias collisions ranked by mention "
            "prevalence; optionally merge same-type "
            "duplicates with human confirmation."
        ),
    )
    p.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to the KG SQLite database.",
    )
    p.add_argument(
        "--min-mentions",
        type=int,
        default=0,
        help=(
            "Drop collisions whose total mention count "
            "is below this threshold (default: 0)."
        ),
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Merge same-type collisions. Prompts for "
            "confirmation per collision unless "
            "--auto-confirm is also set."
        ),
    )
    p.add_argument(
        "--auto-confirm",
        action="store_true",
        help=(
            "Skip the interactive prompt during "
            "--apply. Scripted use only — run a "
            "dry-run first."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    args = _build_parser().parse_args(argv)
    if args.auto_confirm and not args.apply:
        raise SystemExit("--auto-confirm requires --apply.")
    with KnowledgeStore(db_path=args.db) as store:
        raw = find_alias_collisions(store._conn)  # noqa: SLF001
        scored = score_collisions(store, raw)
        scored = [c for c in scored if c.total_mentions >= args.min_mentions]
        if not scored:
            logger.info("No alias collisions above threshold.")
            return
        for c in scored:
            sys.stdout.write(format_collision(c) + "\n\n")
        if args.apply:
            merged = _apply_merges(
                store,
                scored,
                auto_confirm=args.auto_confirm,
            )
            logger.info("Merged %d entity/entities.", merged)


if __name__ == "__main__":
    main()


__all__ = [
    "ScoredCollision",
    "ScoredEntity",
    "format_collision",
    "main",
    "score_collisions",
]
