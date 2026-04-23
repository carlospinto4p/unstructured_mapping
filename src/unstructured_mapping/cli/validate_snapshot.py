"""Record and check KG quality snapshots for CI gating.

The storage layer already validates per-write invariants
(temporal bounds, alias collision flagging). What it does
*not* do is compare a whole-KG snapshot against a known-
good baseline — the kind of check that catches "my latest
LLM prompt lost 40% of the organisations".

This CLI fills that gap. It has two modes:

- ``--record <path>``: capture a structured summary of
  the current KG (counts by type / subtype, top-K alias
  collisions, provenance density) and write it to a JSON
  file. The file is committable — it serves as the
  golden baseline for future runs.
- ``--check <baseline>``: capture the current KG, load
  the baseline, and emit a textual report of every
  metric that moved. Exits non-zero when a threshold
  is breached; zero otherwise.

Thresholds are kept small on purpose so CI wiring is
trivial. Two knobs cover the common failure modes:

- ``--max-entity-drop-pct``: maximum allowed drop in
  total entity count, expressed as a percentage of the
  baseline. Defaults to 10, i.e. "fail if the KG lost
  more than 10% of its entities".
- ``--max-collision-increase``: maximum allowed
  *increase* in alias collisions (absolute count).
  Defaults to 0, i.e. "any new collision is a
  regression worth inspecting".

Both modes print a human-readable report so the same
tool works as a CI gate and as an interactive "did my
change blow up quality?" check.

Usage::

    # Record a baseline after a known-good run:
    uv run python -m unstructured_mapping.cli.validate_snapshot \\
        --db data/knowledge.db \\
        --record snapshots/baseline.json

    # Check a live KG against it (CI):
    uv run python -m unstructured_mapping.cli.validate_snapshot \\
        --db data/knowledge.db \\
        --check snapshots/baseline.json \\
        --max-entity-drop-pct 5
"""

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    add_db_argument,
)
from unstructured_mapping.cli._db_helpers import open_kg_store
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)
from unstructured_mapping.knowledge_graph.validation import (
    find_alias_collisions,
)

logger = logging.getLogger(__name__)

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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Record and compare KG quality snapshots. "
            "Useful as a CI gate against accidental "
            "regressions (entity loss, new alias "
            "collisions)."
        ),
    )
    add_db_argument(p, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--record",
        type=Path,
        metavar="PATH",
        help="Capture a snapshot and write it to PATH.",
    )
    mode.add_argument(
        "--check",
        type=Path,
        metavar="BASELINE",
        help=(
            "Capture the current KG and compare it to "
            "the baseline JSON at BASELINE. Non-zero "
            "exit on threshold breach."
        ),
    )
    p.add_argument(
        "--max-entity-drop-pct",
        type=float,
        default=10.0,
        help=(
            "Fail --check when entity count drops by "
            "more than this percentage (default: 10)."
        ),
    )
    p.add_argument(
        "--max-collision-increase",
        type=int,
        default=0,
        help=(
            "Fail --check when alias collisions grow by "
            "more than this absolute count "
            "(default: 0)."
        ),
    )
    p.add_argument(
        "--top-k-collisions",
        type=int,
        default=DEFAULT_TOP_K_COLLISIONS,
        help=(
            "Number of alias collisions to record in "
            "the snapshot (default: "
            f"{DEFAULT_TOP_K_COLLISIONS})."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    args = _build_parser().parse_args(argv)
    with open_kg_store(args.db) as store:
        snapshot = capture_snapshot(
            store, top_k_collisions=args.top_k_collisions
        )
        if args.record is not None:
            write_snapshot(snapshot, args.record)
            sys.stdout.write(
                f"Recorded snapshot to {args.record}: "
                f"entities={snapshot.total_entities} "
                f"relationships={snapshot.total_relationships} "
                f"collisions={snapshot.alias_collision_count}\n"
            )
            return
        # --check mode
        baseline = load_snapshot(args.check)
        result = compare_snapshots(
            baseline,
            snapshot,
            max_entity_drop_pct=args.max_entity_drop_pct,
            max_collision_increase=args.max_collision_increase,
        )
        sys.stdout.write(result.report + "\n")
        if not result.passed:
            raise SystemExit(1)


if __name__ == "__main__":
    main()


__all__ = [
    "CheckResult",
    "CollisionSummary",
    "DEFAULT_TOP_K_COLLISIONS",
    "SCHEMA_VERSION",
    "Snapshot",
    "capture_snapshot",
    "compare_snapshots",
    "load_snapshot",
    "main",
    "write_snapshot",
]
