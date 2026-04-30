"""KG management endpoints: seed population and maintenance."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from unstructured_mapping.cli.audit_aliases import (
    score_collisions,
)
from unstructured_mapping.cli.populate import StageReport, populate
from unstructured_mapping.cli.wikidata_seed import import_entities
from unstructured_mapping.knowledge_graph import KnowledgeStore
from unstructured_mapping.knowledge_graph.validation import (
    find_alias_collisions,
)
from unstructured_mapping.wikidata import (
    TYPE_REGISTRY,
    fetch_mapped,
    write_snapshot,
)

from ._deps import get_kg, get_kg_path, get_seed_dir

logger = logging.getLogger(__name__)

router = APIRouter()

_WIKIDATA_SUBDIR = "wikidata"


# ---------------------------------------------------------------------------
# Populate
# ---------------------------------------------------------------------------


def _run_populate_thread(
    kg_path: Path,
    seed_dir: Path,
) -> list[StageReport]:
    """Blocking populate worker — runs in a thread pool thread.

    Opens its own KnowledgeStore so it does not share SQLite
    connections with the main event loop.
    """
    with KnowledgeStore(db_path=kg_path) as kg:
        return populate(seed_dir, kg)


@router.post("/populate")
async def trigger_populate(
    kg_path: Path = Depends(get_kg_path),
    seed_dir: Path = Depends(get_seed_dir),
) -> JSONResponse:
    """Seed the KG from the curated JSON file and Wikidata snapshots.

    Loads ``data/seed/financial_entities.json`` first (curated
    entities take priority), then replays every snapshot under
    ``data/seed/wikidata/`` in sorted order. Idempotent — rows
    already present are skipped.

    Returns a per-stage summary and totals.
    """
    if not seed_dir.exists():
        raise HTTPException(
            status_code=500,
            detail=f"Seed directory not found: {seed_dir}",
        )

    try:
        reports = await asyncio.to_thread(
            _run_populate_thread, kg_path, seed_dir
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Populate failed")
        raise HTTPException(
            status_code=500, detail=f"Populate failed: {exc}"
        ) from exc

    stages = [
        {
            "name": r.name,
            "created": r.created,
            "skipped": r.skipped,
        }
        for r in reports
    ]
    total_created = sum(r.created for r in reports)
    total_skipped = sum(r.skipped for r in reports)

    logger.info(
        "Populate complete: %d created, %d skipped across %d stages",
        total_created,
        total_skipped,
        len(reports),
    )

    return JSONResponse(
        {
            "stages": stages,
            "total_created": total_created,
            "total_skipped": total_skipped,
        }
    )


# ---------------------------------------------------------------------------
# Wikidata refresh
# ---------------------------------------------------------------------------


class WikidataRefreshRequest(BaseModel):
    types: list[str] | None = None
    limit: int = 100


def _run_wikidata_refresh_thread(
    kg_path: Path,
    seed_dir: Path,
    types: list[str],
    limit: int,
) -> list[dict]:
    """Fetch fresh data from Wikidata and update snapshots + KG.

    Runs in a thread so it does not block the event loop during
    the network calls to the Wikidata SPARQL endpoint.
    """
    wikidata_dir = seed_dir / _WIKIDATA_SUBDIR
    wikidata_dir.mkdir(parents=True, exist_ok=True)
    reports: list[dict] = []

    with KnowledgeStore(db_path=kg_path) as kg:
        for kind in types:
            try:
                mapped = fetch_mapped(kind, limit)
                snapshot_path = wikidata_dir / f"{kind}.json"
                write_snapshot(mapped, snapshot_path)
                created, skipped, _ = import_entities(mapped, kg)
                reports.append(
                    {
                        "type": kind,
                        "fetched": len(mapped),
                        "created": created,
                        "skipped": skipped,
                        "error": None,
                    }
                )
            except Exception as exc:
                logger.exception("Wikidata refresh failed for type %r", kind)
                reports.append(
                    {
                        "type": kind,
                        "fetched": 0,
                        "created": 0,
                        "skipped": 0,
                        "error": str(exc),
                    }
                )

    return reports


@router.post("/wikidata-refresh")
async def wikidata_refresh(
    body: WikidataRefreshRequest,
    kg_path: Path = Depends(get_kg_path),
    seed_dir: Path = Depends(get_seed_dir),
) -> JSONResponse:
    """Re-fetch entity data from Wikidata and update KG + snapshots.

    Queries the Wikidata SPARQL endpoint for each requested entity
    type, overwrites the local snapshot JSON file, and imports any
    new rows into the KG (existing rows are skipped). Useful for
    refreshing data that may have changed since the last snapshot.

    ``types`` defaults to every type in the registry
    (central_bank, company, crypto, currency, exchange, index,
    regulator). ``limit`` caps rows per type (default 100).

    Network calls are made to Wikidata — this endpoint may take
    30–120 seconds depending on the number of types.
    """
    all_types = sorted(TYPE_REGISTRY)
    requested = body.types or all_types

    unknown = [t for t in requested if t not in TYPE_REGISTRY]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown Wikidata types: {unknown}. Valid types: {all_types}"
            ),
        )

    reports = await asyncio.to_thread(
        _run_wikidata_refresh_thread,
        kg_path,
        seed_dir,
        requested,
        body.limit,
    )

    total_created = sum(r["created"] for r in reports)
    total_skipped = sum(r["skipped"] for r in reports)
    logger.info(
        "Wikidata refresh complete: %d types, %d created, %d skipped",
        len(reports),
        total_created,
        total_skipped,
    )

    return JSONResponse(
        {
            "types": reports,
            "total_created": total_created,
            "total_skipped": total_skipped,
        }
    )


# ---------------------------------------------------------------------------
# Alias audit
# ---------------------------------------------------------------------------


@router.get("/alias-audit")
def alias_audit(
    min_mentions: int = 0,
    kg: KnowledgeStore = Depends(get_kg),
) -> JSONResponse:
    """Report aliases shared by multiple entities, ranked by prevalence.

    Useful for detecting canonical-name drift after bulk ingestion.
    Same-type collisions are flagged as probable duplicates with a
    suggested merge target (the most-mentioned entity).

    ``min_mentions`` filters out collisions below the total mention
    threshold (default 0 = show all).
    """
    raw = find_alias_collisions(kg._conn)  # noqa: SLF001
    scored = score_collisions(kg, raw)
    if min_mentions > 0:
        scored = [c for c in scored if c.total_mentions >= min_mentions]

    collisions = []
    for c in scored:
        merge_target_id = c.merge_target.entity_id if c.merge_target else None
        collisions.append(
            {
                "alias": c.alias,
                "total_mentions": c.total_mentions,
                "same_type": c.same_type,
                "entities": [
                    {
                        "entity_id": e.entity_id,
                        "canonical_name": e.canonical_name,
                        "entity_type": e.entity_type,
                        "mention_count": e.mention_count,
                        "is_merge_target": e.entity_id == merge_target_id,
                    }
                    for e in c.entities
                ],
            }
        )

    return JSONResponse({"total": len(collisions), "collisions": collisions})
