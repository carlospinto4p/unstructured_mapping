"""Cross-chunk aggregation before KG persistence.

When an article is segmented into N chunks, each chunk
runs detection / resolution / extraction independently.
The outputs then need to be combined so the KG writer
sees a single coherent view of the article, not N
overlapping ones:

- **Provenance** passes through unchanged. Every chunk
  detection records a different ``(entity_id,
  document_id, mention_text)`` and the PK guarantees
  dedup at the DB layer. Multiple mentions of the same
  entity across chunks are the correct signal — each one
  is a distinct piece of evidence.
- **Entity proposals** need to dedupe on case-insensitive
  ``canonical_name`` + ``entity_type``. Two chunks may
  both surface a new company name; the aggregator keeps
  the proposal with the longest description (more
  context is better for future resolution) and drops the
  rest. When two chunks propose the *same name* but
  *different types* the aggregator drops both and logs a
  :class:`ProposalConflict` so the review workflow can
  decide.
- **Relationships** dedupe on ``(source_id, target_id,
  relation_type)`` keeping the row whose
  ``context_snippet`` is longest (richest evidence).
  Different ``relation_type`` values between the same
  pair survive as separate relationships — they
  represent different facets of the interaction.

Design rationale lives in ``docs/pipeline/09_chunking.md``
§"Aggregation".
"""

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

from unstructured_mapping.knowledge_graph.models import (
    EntityType,
    Provenance,
)
from unstructured_mapping.pipeline.models import (
    EntityProposal,
    ExtractedRelationship,
    ResolutionResult,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ProposalConflict:
    """Record of a same-name-different-type collision.

    Two chunks proposed a new entity with the same
    ``canonical_name`` but conflicting ``entity_type``
    values. The aggregator drops both rather than guess;
    a human (or a later type-resolution step) picks which
    is real.

    :param canonical_name: The colliding name.
    :param entity_types: The distinct types seen.
    """

    canonical_name: str
    entity_types: tuple[EntityType, ...]


@dataclass(frozen=True, slots=True)
class ChunkOutcome:
    """Per-chunk outputs handed to the aggregator.

    Mirrors the orchestrator's per-chunk working state
    *without* any persistence side-effect — the
    aggregator only reads fields.

    :param resolution: Resolver output for this chunk.
    :param provenances: Provenance rows the resolver
        mapped from resolved mentions. Pre-built so the
        orchestrator doesn't need to rebuild them after
        aggregation.
    :param proposals: LLM entity proposals from the
        resolver's cascade.
    :param relationships: Extractor output (pre-
        persistence).
    """

    resolution: ResolutionResult = field(
        default_factory=ResolutionResult
    )
    provenances: tuple[Provenance, ...] = ()
    proposals: tuple[EntityProposal, ...] = ()
    relationships: tuple[
        ExtractedRelationship, ...
    ] = ()


@dataclass(frozen=True, slots=True)
class AggregatedOutcome:
    """Deduped, cross-chunk view of one article.

    :param resolution: All resolved and unresolved
        mentions, concatenated across chunks. Kept as a
        single result to match the pre-aggregation
        :class:`ArticleResult` contract.
    :param provenances: Every provenance row to persist.
    :param proposals: Deduped proposals. Type conflicts
        are excluded; see ``conflicts``.
    :param relationships: Deduped relationships.
    :param conflicts: Proposal name collisions with
        divergent types that were dropped.
    """

    resolution: ResolutionResult
    provenances: tuple[Provenance, ...]
    proposals: tuple[EntityProposal, ...]
    relationships: tuple[ExtractedRelationship, ...]
    conflicts: tuple[ProposalConflict, ...]


class ChunkAggregator:
    """Combine per-chunk pipeline outputs for one article.

    Stateless — every call is fully determined by the
    inputs. The orchestrator creates one and reuses it
    across articles. Single-chunk articles go through the
    same code path: dedup is a no-op for them and the
    overhead is negligible.
    """

    def aggregate(
        self, outcomes: Iterable[ChunkOutcome]
    ) -> AggregatedOutcome:
        """Collapse chunk outcomes into one article view."""
        outcomes = list(outcomes)
        resolved: list = []
        unresolved: list = []
        provenances: list[Provenance] = []
        proposals_by_key: dict[
            tuple[str, EntityType], EntityProposal
        ] = {}
        type_sets: dict[
            str, set[EntityType]
        ] = {}
        # Preserve the first-seen original casing for
        # conflict reporting — the lowercased key is
        # just an implementation detail.
        original_names: dict[str, str] = {}
        rels_by_key: dict[
            tuple[str, str, str], ExtractedRelationship
        ] = {}

        for outcome in outcomes:
            resolved.extend(outcome.resolution.resolved)
            unresolved.extend(outcome.resolution.unresolved)
            provenances.extend(outcome.provenances)
            self._merge_proposals(
                outcome.proposals,
                proposals_by_key,
                type_sets,
                original_names,
            )
            self._merge_relationships(
                outcome.relationships, rels_by_key
            )

        conflicts = tuple(
            ProposalConflict(
                canonical_name=original_names[name],
                entity_types=tuple(
                    sorted(types, key=lambda t: t.value)
                ),
            )
            for name, types in type_sets.items()
            if len(types) > 1
        )
        for conflict in conflicts:
            logger.warning(
                "Dropping conflicting proposals for %r "
                "(types: %s)",
                conflict.canonical_name,
                ", ".join(
                    t.value for t in conflict.entity_types
                ),
            )
            for t in conflict.entity_types:
                proposals_by_key.pop(
                    (conflict.canonical_name.lower(), t),
                    None,
                )

        return AggregatedOutcome(
            resolution=ResolutionResult(
                resolved=tuple(resolved),
                unresolved=tuple(unresolved),
            ),
            provenances=tuple(provenances),
            proposals=tuple(proposals_by_key.values()),
            relationships=tuple(rels_by_key.values()),
            conflicts=conflicts,
        )

    @staticmethod
    def _merge_proposals(
        proposals: Iterable[EntityProposal],
        store: dict[
            tuple[str, EntityType], EntityProposal
        ],
        type_sets: dict[str, set[EntityType]],
        original_names: dict[str, str],
    ) -> None:
        """Dedup on lowercased name + type; keep the
        longest description.

        Also tracks every type seen per name so the
        aggregator can emit a conflict record when two
        chunks disagree on the type, and the first
        original-casing so conflict records read
        naturally.
        """
        for proposal in proposals:
            name_key = proposal.canonical_name.lower()
            key = (name_key, proposal.entity_type)
            type_sets.setdefault(
                name_key, set()
            ).add(proposal.entity_type)
            original_names.setdefault(
                name_key, proposal.canonical_name
            )
            prior = store.get(key)
            if prior is None or len(
                proposal.description
            ) > len(prior.description):
                store[key] = proposal

    @staticmethod
    def _merge_relationships(
        relationships: Iterable[ExtractedRelationship],
        store: dict[
            tuple[str, str, str], ExtractedRelationship
        ],
    ) -> None:
        """Dedup on ``(source, target, relation_type)``
        keeping the instance with the richest
        ``context_snippet``.

        Same pair + same type → merge (keep best
        evidence). Same pair + different relation_type →
        kept as separate rows, the two types describe
        different facets.
        """
        for rel in relationships:
            key = (
                rel.source_id,
                rel.target_id,
                rel.relation_type,
            )
            prior = store.get(key)
            if prior is None or len(
                rel.context_snippet
            ) > len(prior.context_snippet):
                store[key] = rel
