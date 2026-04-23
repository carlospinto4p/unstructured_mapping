"""Audit queries mixin for KnowledgeStore.

Three quality heuristics surface low-signal provenance
so an operator can spot entities the pipeline is
under-covering:

1. **Short context snippets** — mentions whose context
   is too short to disambiguate or cite.
2. **Thin mention coverage** — entities with fewer
   distinct ``(document_id, mention_text)`` pairs than
   a threshold (including zero-mention orphans).
3. **Narrow temporal spread** — entities whose mentions
   cluster in a window shorter than a threshold, which
   often signals a one-shot news event rather than a
   durable KG entity.

The token estimate uses the same ``ceil(chars / 4)``
approximation as :mod:`pipeline.budget`; both sites
import :data:`unstructured_mapping.tokens._CHARS_PER_TOKEN`
so the KG layer stays independent of the pipeline.
"""

import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from unstructured_mapping.tokens import _CHARS_PER_TOKEN


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


def _estimate_tokens(text: str) -> int:
    """Approximate token count for a snippet.

    Matches ``pipeline.budget.estimate_tokens`` exactly
    but lives here so the KG layer stays independent of
    the pipeline.
    """
    if not text:
        return 0
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


def _spread_seconds(earliest: str | None, latest: str | None) -> float | None:
    """Safely compute the gap between two ISO strings."""
    if not earliest or not latest:
        return None
    try:
        e = datetime.fromisoformat(earliest)
        l_ = datetime.fromisoformat(latest)
    except ValueError:
        return None
    return (l_ - e).total_seconds()


class AuditMixin:
    """Audit queries for :class:`KnowledgeStore`."""

    _conn: sqlite3.Connection

    def find_short_snippets(
        self, *, min_tokens: int
    ) -> list[ShortSnippetFinding]:
        """Return provenance rows whose context is thin.

        :param min_tokens: Snippets whose estimated token
            count is below this threshold are flagged.
        :return: One finding per low-token provenance
            row, in the order returned by the join (not
            sorted — presentation layers decide).

        A ``LENGTH(context_snippet) < ? * _CHARS_PER_TOKEN``
        predicate is pushed down to SQLite so obviously-long
        snippets are skipped before row hydration. Token
        counting in Python still applies the exact
        ``ceil(len / 4)`` estimate as a post-filter — the SQL
        bound is a conservative superset because a snippet
        with ``len == min_tokens * 4`` ceils to ``min_tokens``
        (not below) and must still be inspected.
        """
        char_bound = min_tokens * _CHARS_PER_TOKEN
        rows = self._conn.execute(
            "SELECT p.entity_id, p.document_id, "
            "p.mention_text, p.context_snippet, "
            "e.canonical_name, e.entity_type "
            "FROM provenance p "
            "JOIN entities e "
            "ON e.entity_id = p.entity_id "
            "WHERE LENGTH(p.context_snippet) < ?",
            (char_bound,),
        ).fetchall()
        findings: list[ShortSnippetFinding] = []
        for r in rows:
            tokens = _estimate_tokens(r["context_snippet"])
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
        self, *, min_mentions: int
    ) -> list[ThinMentionFinding]:
        """Return entities with fewer distinct mentions
        than ``min_mentions``.

        "Distinct mention" = distinct ``(document_id,
        mention_text)`` pair, matching the provenance
        primary key so reprocessing the same article
        does not inflate counts. The ``LEFT JOIN`` keeps
        zero-mention orphan entities in the result.
        """
        rows = self._conn.execute(
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
        self, *, min_days: float
    ) -> list[NarrowSpreadFinding]:
        """Return entities whose mention timestamps span
        less than ``min_days``.

        Entities with a single mention are excluded —
        they are covered by :meth:`find_thin_mentions`
        and would always have a zero-second span,
        drowning out the useful multi-mention findings.
        Sorted by span ascending, tie-broken on
        canonical name, so the most suspicious
        single-cycle clusters come first.
        """
        threshold = timedelta(days=min_days).total_seconds()
        rows = self._conn.execute(
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
        findings.sort(
            key=lambda f: (
                f.span_seconds,
                f.canonical_name,
            )
        )
        return findings
