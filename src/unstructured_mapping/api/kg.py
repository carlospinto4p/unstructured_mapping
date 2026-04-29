"""KG management endpoints: seed population and maintenance."""

import asyncio
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from unstructured_mapping.cli.populate import StageReport, populate
from unstructured_mapping.knowledge_graph import KnowledgeStore

from ._deps import get_kg_path, get_seed_dir

logger = logging.getLogger(__name__)

router = APIRouter()


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
