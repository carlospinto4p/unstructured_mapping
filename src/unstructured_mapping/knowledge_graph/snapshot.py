"""KG quality snapshot primitives.

A *snapshot* is a structured summary of a knowledge
graph's shape — entity / relationship / provenance
totals, counts grouped by type and subtype, and the
top-K alias collisions — captured at a moment in time
and persisted as JSON. It is the data model behind the
``cli.validate_snapshot`` quality gate, but the
primitives live here in :mod:`knowledge_graph` because
they are KG-domain concepts, not CLI concerns: future
tooling (drift checks between two live KGs, dashboards,
LLM prompts that need a quick "how big is this graph?"
context block) can re-use them without importing from a
CLI module.

This module contains the read side
(:func:`capture_snapshot`), the comparison gate
(:func:`compare_snapshots`), and on-disk persistence
(:func:`write_snapshot` / :func:`load_snapshot`). The
CLI in :mod:`unstructured_mapping.cli.validate_snapshot`
re-exports the public names and adds the argparse
plumbing.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from unstructured_mapping.knowledge_graph.storage import (
    KnowledgeStore,
)
from unstructured_mapping.knowledge_graph.validation import (
    find_alias_collisions,
)

#: How many top alias collisions to persist in a
#: snapshot. Enough context to debug regressions without
#: turning the file into an unreadable dump.
DEFAULT_TOP_K_COLLISIONS: int = 20

#: Snapshot file-format version. Bumped when the schema
#: gains or drops a field so old baselines raise a clear
#: error instead of silently skipping new metrics.
SCHEMA_VERSION: int = 1


@dataclass(frozen=True, slots=True)
class CollisionSummary:
    """One alias collision reduced to its baseline-worthy
    fields.

    Entity IDs are intentionally excluded — they change
    across runs, making diffs noisy. The alias text plus
    the set of conflicting entity types is what actually
    characterises the collision from a quality-gate
    perspective.
    """

    alias: str
    entity_count: int
    entity_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Snapshot:
    """KG-wide quality summary at one point in time."""

    recorded_at: str
    schema_version: int
    total_entities: int
    total_relationships: int
    total_provenance: int
    counts_by_type: dict[str, int] = field(default_factory=dict)
    counts_by_type_subtype: dict[str, dict[str, int]] = field(
        default_factory=dict
    )
    alias_collision_count: int = 0
    top_collisions: tuple[CollisionSummary, ...] = ()

    @property
    def provenance_density(self) -> float:
        """Average provenance rows per entity.

        Zero when the KG has no entities — avoids a
        ``ZeroDivisionError`` in reports for fresh DBs.
        """
        if self.total_entities == 0:
            return 0.0
        return self.total_provenance / self.total_entities

    def to_dict(self) -> dict[str, object]:
        """Render a JSON-safe dict for on-disk storage."""
        payload = asdict(self)
        payload["top_collisions"] = [
            {
                "alias": c.alias,
                "entity_count": c.entity_count,
                "entity_types": list(c.entity_types),
            }
            for c in self.top_collisions
        ]
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Snapshot":
        """Rehydrate a snapshot from its on-disk JSON form.

        :raises ValueError: If the payload's schema
            version is newer or older than this module
            supports. Callers see a clear, actionable
            message instead of silently mis-reading
            fields.
        """
        version = payload.get("schema_version")
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"snapshot schema_version={version!r} does "
                f"not match supported version "
                f"{SCHEMA_VERSION}. Re-record the baseline."
            )
        raw_cols = payload.get("top_collisions", [])
        collisions = tuple(
            CollisionSummary(
                alias=row["alias"],
                entity_count=row["entity_count"],
                entity_types=tuple(row["entity_types"]),
            )
            for row in raw_cols
        )
        return cls(
            recorded_at=payload["recorded_at"],
            schema_version=SCHEMA_VERSION,
            total_entities=payload["total_entities"],
            total_relationships=payload["total_relationships"],
            total_provenance=payload["total_provenance"],
            counts_by_type=dict(payload.get("counts_by_type", {})),
            counts_by_type_subtype={
                k: dict(v)
                for k, v in payload.get("counts_by_type_subtype", {}).items()
            },
            alias_collision_count=payload.get("alias_collision_count", 0),
            top_collisions=collisions,
        )


def _count_by_type_subtype(
    store: KnowledgeStore,
) -> dict[str, dict[str, int]]:
    """Group entities by ``(entity_type, subtype)``.

    Missing subtypes land under the sentinel key
    ``""`` so the output stays a plain nested dict
    without ``None`` sprinkled through it.
    """
    rows = store._conn.execute(  # noqa: SLF001
        "SELECT entity_type, COALESCE(subtype, ''), COUNT(*) "
        "FROM entities GROUP BY entity_type, subtype"
    ).fetchall()
    out: dict[str, dict[str, int]] = {}
    for etype, subtype, count in rows:
        out.setdefault(etype, {})[subtype] = count
    return out


def _scalar_count(store: KnowledgeStore, table: str) -> int:
    """Return ``SELECT COUNT(*) FROM <table>``.

    Separated for easy mocking and to keep the capture
    function readable.
    """
    row = store._conn.execute(  # noqa: SLF001
        f"SELECT COUNT(*) FROM {table}"
    ).fetchone()
    return int(row[0]) if row else 0


def capture_snapshot(
    store: KnowledgeStore,
    *,
    top_k_collisions: int = DEFAULT_TOP_K_COLLISIONS,
) -> Snapshot:
    """Take a full-KG quality snapshot.

    Reads are scoped to summary-level queries — no row
    data leaves the DB, so the snapshot file is safe to
    commit even from a large KG.
    """
    total_entities = _scalar_count(store, "entities")
    total_relationships = _scalar_count(store, "relationships")
    total_provenance = _scalar_count(store, "provenance")
    counts_by_type = store.count_entities_by_type()
    counts_by_type_subtype = _count_by_type_subtype(store)

    raw_collisions = find_alias_collisions(store._conn)  # noqa: SLF001
    # Rank by number of conflicting entities (bigger =
    # noisier); tie-break on alias text for determinism.
    ranked = sorted(
        raw_collisions,
        key=lambda c: (-len(c.entities), c.alias),
    )
    top = tuple(
        CollisionSummary(
            alias=c.alias,
            entity_count=len(c.entities),
            entity_types=tuple(sorted({etype for _, _, etype in c.entities})),
        )
        for c in ranked[:top_k_collisions]
    )

    return Snapshot(
        recorded_at=datetime.now(timezone.utc).isoformat(),
        schema_version=SCHEMA_VERSION,
        total_entities=total_entities,
        total_relationships=total_relationships,
        total_provenance=total_provenance,
        counts_by_type=counts_by_type,
        counts_by_type_subtype=counts_by_type_subtype,
        alias_collision_count=len(raw_collisions),
        top_collisions=top,
    )


def write_snapshot(snapshot: Snapshot, path: Path) -> None:
    """Persist ``snapshot`` to ``path`` as indented JSON.

    The file is human-readable by design — it lives in
    source control and a diff should be legible in a PR.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(snapshot.to_dict(), fh, indent=2, sort_keys=True)
        fh.write("\n")


def load_snapshot(path: Path) -> Snapshot:
    """Read a snapshot JSON file into a :class:`Snapshot`."""
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return Snapshot.from_dict(payload)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """Outcome of a baseline-vs-current comparison."""

    passed: bool
    report: str
    breaches: tuple[str, ...]


def _format_counts_diff(
    label: str,
    baseline: dict[str, int],
    current: dict[str, int],
) -> str:
    """Render a one-section diff between two count dicts."""
    lines = [f"{label}:"]
    keys = sorted(set(baseline) | set(current))
    if not keys:
        lines.append("  (empty)")
        return "\n".join(lines)
    for key in keys:
        before = baseline.get(key, 0)
        after = current.get(key, 0)
        if before == after:
            lines.append(f"  {key}: {after}")
        else:
            delta = after - before
            sign = "+" if delta > 0 else ""
            lines.append(f"  {key}: {before} -> {after} ({sign}{delta})")
    return "\n".join(lines)


def compare_snapshots(
    baseline: Snapshot,
    current: Snapshot,
    *,
    max_entity_drop_pct: float = 10.0,
    max_collision_increase: int = 0,
) -> CheckResult:
    """Compare a baseline to a current snapshot.

    :param max_entity_drop_pct: Fail when
        ``(baseline - current) / baseline * 100`` exceeds
        this value. Growth and flat counts always pass.
    :param max_collision_increase: Fail when current has
        more than this many extra alias collisions vs.
        the baseline.
    :return: Structured :class:`CheckResult`; callers
        should branch on ``.passed`` and typically print
        ``.report`` either way.
    """
    breaches: list[str] = []

    # Entity-drop gate. Division by zero is handled by
    # treating "empty baseline + empty current" as a
    # pass; any growth from zero obviously is not a drop.
    entity_delta = current.total_entities - baseline.total_entities
    if baseline.total_entities > 0 and entity_delta < 0:
        drop_pct = abs(entity_delta) / baseline.total_entities * 100.0
        if drop_pct > max_entity_drop_pct:
            breaches.append(
                f"entity drop {drop_pct:.1f}% exceeds threshold "
                f"{max_entity_drop_pct:.1f}% "
                f"({baseline.total_entities} -> "
                f"{current.total_entities})"
            )

    # Alias-collision regression gate.
    collision_delta = (
        current.alias_collision_count - baseline.alias_collision_count
    )
    if collision_delta > max_collision_increase:
        breaches.append(
            f"alias collisions grew by {collision_delta} "
            f"(threshold: {max_collision_increase}); "
            f"{baseline.alias_collision_count} -> "
            f"{current.alias_collision_count}"
        )

    sections: list[str] = [
        "Snapshot comparison:",
        f"  baseline recorded_at: {baseline.recorded_at}",
        f"  current recorded_at:  {current.recorded_at}",
        "",
        "Totals:",
        f"  entities:      {baseline.total_entities} -> "
        f"{current.total_entities}",
        f"  relationships: {baseline.total_relationships} -> "
        f"{current.total_relationships}",
        f"  provenance:    {baseline.total_provenance} -> "
        f"{current.total_provenance}",
        f"  prov density:  {baseline.provenance_density:.2f} -> "
        f"{current.provenance_density:.2f}",
        f"  collisions:    {baseline.alias_collision_count} -> "
        f"{current.alias_collision_count}",
        "",
        _format_counts_diff(
            "Entity counts by type",
            baseline.counts_by_type,
            current.counts_by_type,
        ),
    ]

    if breaches:
        sections.append("")
        sections.append("BREACHES:")
        for msg in breaches:
            sections.append(f"  - {msg}")
    else:
        sections.append("")
        sections.append("All thresholds satisfied.")

    return CheckResult(
        passed=not breaches,
        report="\n".join(sections),
        breaches=tuple(breaches),
    )


__all__ = [
    "CheckResult",
    "CollisionSummary",
    "DEFAULT_TOP_K_COLLISIONS",
    "SCHEMA_VERSION",
    "Snapshot",
    "capture_snapshot",
    "compare_snapshots",
    "load_snapshot",
    "write_snapshot",
]
