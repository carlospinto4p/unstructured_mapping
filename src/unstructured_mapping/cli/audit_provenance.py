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
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)
from unstructured_mapping.pipeline.budget import (
    estimate_tokens,
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


@dataclass(frozen=True, slots=True)
class ShortSnippetFinding:
    """A provenance row whose context is too short."""

    entity_id: str
    canonical_name: str
    entity_type: str
    document_id: str
    mention_text: str
    token_estimate: int


@dataclass(frozen=True, slots=True)
class ThinMentionFinding:
    """An entity with too few distinct mentions."""

    entity_id: str
    canonical_name: str
    entity_type: str
    mention_count: int


@dataclass(frozen=True, slots=True)
class NarrowSpreadFinding:
    """An entity whose mentions cluster in a short
    window."""

    entity_id: str
    canonical_name: str
    entity_type: str
    mention_count: int
    span_seconds: float


def find_short_snippets(
    store: KnowledgeStore,
    *,
    min_tokens: int,
) -> list[ShortSnippetFinding]:
    """Return provenance rows whose context is thin.

    The token estimate reuses :func:`estimate_tokens`
    (len / 4) so the threshold matches the same budget
    math the pipeline uses elsewhere.
    """
    rows = store._conn.execute(  # noqa: SLF001
        "SELECT p.entity_id, p.document_id, "
        "p.mention_text, p.context_snippet, "
        "e.canonical_name, e.entity_type "
        "FROM provenance p "
        "JOIN entities e ON e.entity_id = p.entity_id"
    ).fetchall()
    findings: list[ShortSnippetFinding] = []
    for r in rows:
        tokens = estimate_tokens(r["context_snippet"])
        if tokens < min_tokens:
            findings.append(
                ShortSnippetFinding(
                    entity_id=r["entity_id"],
                    canonical_name=r["canonical_name"],
                    entity_type=r["entity_type"],
                    document_id=r["document_id"],
                    mention_text=r["mention_text"],
                    token_estimate=tokens,
                )
            )
    return findings


def find_thin_mentions(
    store: KnowledgeStore,
    *,
    min_mentions: int,
) -> list[ThinMentionFinding]:
    """Return entities with fewer distinct mentions than
    ``min_mentions``.

    "Distinct mention" = distinct ``(document_id,
    mention_text)`` pair, matching the provenance
    primary key so reprocessing the same article does
    not inflate counts.
    """
    rows = store._conn.execute(  # noqa: SLF001
        "SELECT e.entity_id, e.canonical_name, "
        "e.entity_type, "
        "COUNT(DISTINCT p.document_id || '|' || "
        "p.mention_text) AS mention_count "
        "FROM entities e "
        "LEFT JOIN provenance p "
        "ON p.entity_id = e.entity_id "
        "GROUP BY e.entity_id "
        "HAVING mention_count < ? "
        "ORDER BY mention_count, e.canonical_name",
        (min_mentions,),
    ).fetchall()
    return [
        ThinMentionFinding(
            entity_id=r["entity_id"],
            canonical_name=r["canonical_name"],
            entity_type=r["entity_type"],
            mention_count=int(r["mention_count"]),
        )
        for r in rows
    ]


def find_narrow_spread(
    store: KnowledgeStore,
    *,
    min_days: float,
) -> list[NarrowSpreadFinding]:
    """Return entities whose mention timestamps span
    less than ``min_days``.

    Entities with a single mention are excluded — they
    are covered by :func:`find_thin_mentions` and would
    always have a zero-second span, drowning out the
    useful multi-mention findings.
    """
    threshold = timedelta(days=min_days).total_seconds()
    rows = store._conn.execute(  # noqa: SLF001
        "SELECT e.entity_id, e.canonical_name, "
        "e.entity_type, "
        "COUNT(*) AS mention_count, "
        "MIN(p.detected_at) AS earliest, "
        "MAX(p.detected_at) AS latest "
        "FROM entities e "
        "JOIN provenance p "
        "ON p.entity_id = e.entity_id "
        "WHERE p.detected_at IS NOT NULL "
        "GROUP BY e.entity_id "
        "HAVING mention_count > 1"
    ).fetchall()
    findings: list[NarrowSpreadFinding] = []
    for r in rows:
        span = _spread_seconds(r["earliest"], r["latest"])
        if span is None or span >= threshold:
            continue
        findings.append(
            NarrowSpreadFinding(
                entity_id=r["entity_id"],
                canonical_name=r["canonical_name"],
                entity_type=r["entity_type"],
                mention_count=int(r["mention_count"]),
                span_seconds=span,
            )
        )
    findings.sort(key=lambda f: (f.span_seconds, f.canonical_name))
    return findings


def _spread_seconds(earliest: str | None, latest: str | None) -> float | None:
    """Safely compute the gap between two ISO strings."""
    if not earliest or not latest:
        return None
    from datetime import datetime

    try:
        e = datetime.fromisoformat(earliest)
        l_ = datetime.fromisoformat(latest)
    except ValueError:
        return None
    return (l_ - e).total_seconds()


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
    p.add_argument(
        "--db",
        type=Path,
        required=True,
        help="Path to the KG SQLite database.",
    )
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
    p.add_argument(
        "--csv",
        type=Path,
        default=None,
        help=("Write findings to a CSV file instead of the text report."),
    )
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
