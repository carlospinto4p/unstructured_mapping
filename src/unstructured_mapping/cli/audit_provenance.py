"""Audit provenance quality — surface low-signal rows.

Three quality heuristics help spot entities the pipeline
is under-covering:

1. **Short context snippets.** Snippets below a token
   threshold are unlikely to give a downstream consumer
   enough context to disambiguate or cite. Snippet length
   is estimated in tokens using the existing 4-char
   heuristic from ``pipeline/budget.py``.
2. **Thin mention coverage.** Entities with fewer than
   ``--min-mentions`` distinct mentions across the corpus
   look more like noise than a confirmed match — worth a
   human look before downstream analysis leans on them.
3. **Narrow temporal spread.** An entity every mention of
   which falls inside a short window (e.g. < 1 day) may
   be tied to a single news event rather than a durable
   KG entity. Reporting the spread lets an operator
   decide whether to promote or demote the entity.

Each finding is a row in the output; ``--csv`` writes the
rows to a CSV file for spreadsheet review, otherwise the
CLI prints a compact text report to stdout.

Usage::

    uv run python -m unstructured_mapping.cli.audit_provenance \\
        --db data/knowledge.db
    uv run python -m unstructured_mapping.cli.audit_provenance \\
        --db data/knowledge.db \\
        --min-tokens 5 --min-mentions 2 --min-days 1 \\
        --csv audit.csv
"""

import argparse
import csv
import logging
import sys
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    add_csv_output_argument,
    add_db_argument,
)
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)
from unstructured_mapping.knowledge_graph._audit_mixin import (
    NarrowSpreadFinding,
    ShortSnippetFinding,
    ThinMentionFinding,
)

logger = logging.getLogger(__name__)

#: Default snippet threshold — five tokens is enough to
#: include the mention plus a couple of surrounding
#: words. Anything shorter is noise.
_DEFAULT_MIN_TOKENS = 5

#: Default mention-count threshold. Two distinct
#: provenance rows is the weakest signal we still treat
#: as "this entity exists"; single-mention entities are
#: flagged so an operator can review them.
_DEFAULT_MIN_MENTIONS = 2

#: Default temporal spread threshold. 24h is a single
#: news cycle — anything tighter is usually a one-shot
#: event, not a durable KG entity.
_DEFAULT_MIN_DAYS = 1


def find_short_snippets(
    store: KnowledgeStore, *, min_tokens: int
) -> list[ShortSnippetFinding]:
    """Thin wrapper around
    :meth:`AuditMixin.find_short_snippets`.

    Kept so the public ``cli.audit_provenance`` module
    surface (used by tests and any external scripts)
    stays stable after the query moved into the store.
    """
    return store.find_short_snippets(min_tokens=min_tokens)


def find_thin_mentions(
    store: KnowledgeStore, *, min_mentions: int
) -> list[ThinMentionFinding]:
    """Thin wrapper around
    :meth:`AuditMixin.find_thin_mentions`."""
    return store.find_thin_mentions(min_mentions=min_mentions)


def find_narrow_spread(
    store: KnowledgeStore, *, min_days: float
) -> list[NarrowSpreadFinding]:
    """Thin wrapper around
    :meth:`AuditMixin.find_narrow_spread`."""
    return store.find_narrow_spread(min_days=min_days)


def _report_text(
    shorts: list[ShortSnippetFinding],
    thins: list[ThinMentionFinding],
    narrows: list[NarrowSpreadFinding],
) -> str:
    parts: list[str] = []
    parts.append(f"Short context snippets: {len(shorts)}")
    for f in shorts[:20]:
        parts.append(
            f"  [{f.entity_type}] {f.canonical_name}"
            f"  tokens={f.token_estimate}"
            f"  doc={f.document_id[:12]}"
        )
    parts.append("")
    parts.append(f"Thin mention coverage: {len(thins)}")
    for f in thins[:20]:
        parts.append(
            f"  [{f.entity_type}] {f.canonical_name}"
            f"  mentions={f.mention_count}"
        )
    parts.append("")
    parts.append(f"Narrow temporal spread: {len(narrows)}")
    for f in narrows[:20]:
        parts.append(
            f"  [{f.entity_type}] {f.canonical_name}"
            f"  mentions={f.mention_count}"
            f"  span={f.span_seconds:.0f}s"
        )
    return "\n".join(parts)


def _write_csv(
    path: Path,
    shorts: list[ShortSnippetFinding],
    thins: list[ThinMentionFinding],
    narrows: list[NarrowSpreadFinding],
) -> None:
    """Write all three finding types to a single CSV.

    One file keeps the operator's spreadsheet workflow
    simple — a ``finding_type`` column discriminates the
    rows. Columns common to every finding (``entity_id``
    / ``canonical_name`` / ``entity_type``) come first;
    finding-specific columns follow.
    """
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "finding_type",
                "entity_id",
                "canonical_name",
                "entity_type",
                "detail_key",
                "detail_value",
            ]
        )
        for f in shorts:
            writer.writerow(
                [
                    "short_snippet",
                    f.entity_id,
                    f.canonical_name,
                    f.entity_type,
                    f"tokens@{f.document_id}",
                    f.token_estimate,
                ]
            )
        for f in thins:
            writer.writerow(
                [
                    "thin_mentions",
                    f.entity_id,
                    f.canonical_name,
                    f.entity_type,
                    "mention_count",
                    f.mention_count,
                ]
            )
        for f in narrows:
            writer.writerow(
                [
                    "narrow_spread",
                    f.entity_id,
                    f.canonical_name,
                    f.entity_type,
                    f"span_seconds@{f.mention_count}_mentions",
                    f.span_seconds,
                ]
            )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Surface low-signal provenance: short "
            "context snippets, under-mentioned "
            "entities, and narrow temporal spread."
        ),
    )
    add_db_argument(p, required=True)
    p.add_argument(
        "--min-tokens",
        type=int,
        default=_DEFAULT_MIN_TOKENS,
        help=(
            "Snippets below this token count are "
            f"flagged (default: {_DEFAULT_MIN_TOKENS})."
        ),
    )
    p.add_argument(
        "--min-mentions",
        type=int,
        default=_DEFAULT_MIN_MENTIONS,
        help=(
            "Entities below this mention count are "
            f"flagged (default: {_DEFAULT_MIN_MENTIONS})."
        ),
    )
    p.add_argument(
        "--min-days",
        type=float,
        default=_DEFAULT_MIN_DAYS,
        help=(
            "Entities whose mentions span less than "
            "this many days are flagged "
            f"(default: {_DEFAULT_MIN_DAYS})."
        ),
    )
    add_csv_output_argument(p)
    return p


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    args = _build_parser().parse_args(argv)
    with KnowledgeStore(db_path=args.db) as store:
        shorts = find_short_snippets(store, min_tokens=args.min_tokens)
        thins = find_thin_mentions(store, min_mentions=args.min_mentions)
        narrows = find_narrow_spread(store, min_days=args.min_days)
    if args.csv is not None:
        _write_csv(args.csv, shorts, thins, narrows)
        logger.info("Wrote %s", args.csv)
        return
    sys.stdout.write(_report_text(shorts, thins, narrows) + "\n")


if __name__ == "__main__":
    main()


__all__ = [
    "NarrowSpreadFinding",
    "ShortSnippetFinding",
    "ThinMentionFinding",
    "find_narrow_spread",
    "find_short_snippets",
    "find_thin_mentions",
    "main",
]
