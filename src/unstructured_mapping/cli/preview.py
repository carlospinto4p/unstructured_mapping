"""Dry-run preview of the ingestion pipeline.

Runs detection + resolution + (optional) extraction on a
single article without touching the real KG. Useful for:

- Debugging why a mention does not resolve.
- Inspecting what the LLM proposes before committing.
- Smoke-testing a prompt change on a known article.

The CLI works by copying the target KG (``--kg-db``) to a
throwaway SQLite file, running the pipeline against the
copy, dumping proposals / resolved mentions / relationships
as JSON, and leaving the real KG untouched.

Usage::

    uv run python -m unstructured_mapping.cli.preview \\
        --article-file sample.json \\
        --kg-db data/knowledge.db \\
        --model llama3.1:8b

    # Cold-start (no KG needed):
    uv run python -m unstructured_mapping.cli.preview \\
        --text "Apple acquired Pebble for $200M." \\
        --cold-start --model llama3.1:8b

Article file schema (JSON)::

    {
      "title": "Apple buys Pebble",
      "body": "...",
      "url": "https://...",
      "source": "reuters",
      "document_id": "<hex>"   (optional; auto-assigned)
    }
"""

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from unstructured_mapping.cli._argparse_helpers import (
    require_db_unless,
)
from unstructured_mapping.cli._db_helpers import prepare_throwaway_kg
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)
from unstructured_mapping.knowledge_graph.models import (
    EntityStatus,
)
from unstructured_mapping.pipeline import (
    AliasResolver,
    ColdStartEntityDiscoverer,
    LLMEntityResolver,
    LLMRelationshipExtractor,
    NoopDetector,
    OllamaProvider,
    Pipeline,
    RuleBasedDetector,
)
from unstructured_mapping.web_scraping.models import (
    Article,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "llama3.1:8b"


def load_article(*, article_file: Path | None, text: str | None) -> Article:
    """Build an :class:`Article` from CLI inputs.

    Exactly one of ``article_file`` or ``text`` must be
    set. ``article_file`` expects a JSON object with
    ``title`` / ``body`` at minimum; ``text`` is the
    fast path for one-liners and uses placeholder
    metadata.
    """
    if bool(article_file) == bool(text):
        raise ValueError("Provide exactly one of --article-file or --text.")
    if text is not None:
        return Article(
            title="(preview)",
            body=text,
            url="",
            source="preview",
        )
    assert article_file is not None
    data = json.loads(article_file.read_text(encoding="utf-8"))
    if "body" not in data:
        raise ValueError(f"{article_file}: missing required 'body'")
    doc_id = data.get("document_id")
    return Article(
        title=data.get("title", ""),
        body=data["body"],
        url=data.get("url", ""),
        source=data.get("source", "preview"),
        document_id=(UUID(doc_id) if doc_id else uuid4()),
    )


def _collect_preview(store: KnowledgeStore, document_id: str) -> dict:
    """Pull everything the pipeline wrote for this doc.

    The preview runs against a throwaway DB, so every row
    tied to ``document_id`` was produced during *this*
    invocation — safe to emit wholesale without further
    filtering.
    """
    # Provenance → resolved mentions + newly created
    # proposals (both get a provenance row per the
    # orchestrator). The store helper joins to entities
    # so the caller sees canonical name + type without a
    # second fetch.
    pairs = store.find_mentions_with_entities(document_id)
    mentions = [
        {
            "entity_id": entity.entity_id,
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type.value,
            "subtype": entity.subtype,
            "description": entity.description,
            "mention_text": prov.mention_text,
            "context_snippet": prov.context_snippet,
            # Entities created during this very run show
            # up with a created_at inside the run window;
            # the benchmarking CLI shows the same shape.
            "newly_created": entity.created_at is not None,
        }
        for entity, prov in pairs
    ]

    rels = store.find_relationships_by_document(document_id)
    relationships = [
        {
            "source_id": r.source_id,
            "target_id": r.target_id,
            "relation_type": r.relation_type,
            "description": r.description,
            "qualifier_id": r.qualifier_id,
            "valid_from": r.valid_from.isoformat() if r.valid_from else None,
            "valid_until": (
                r.valid_until.isoformat() if r.valid_until else None
            ),
            "confidence": r.confidence,
        }
        for r in rels
    ]
    return {
        "mentions": mentions,
        "relationships": relationships,
    }


def preview(
    article: Article,
    *,
    kg_db: Path | None,
    provider: OllamaProvider | None,
    workdir: Path,
    cold_start: bool,
) -> dict:
    """Run the pipeline once and return a dry-run report.

    :param article: Article to process.
    :param kg_db: Populated KG to use as the read side.
        Required when ``cold_start=False``; copied to a
        throwaway file so the source is never mutated.
        Ignored (and may be ``None``) in cold-start mode.
    :param provider: LLM backend. Required when
        ``cold_start=True`` or when LLM resolution /
        extraction is desired; ``None`` skips LLM stages.
    :param workdir: Directory for the throwaway DB.
    :param cold_start: When True, bypass detection and
        resolution; ask the LLM to propose entities from
        scratch.
    :return: Dict with the preview payload.
    """
    source = kg_db if not cold_start else None
    tmp_db = prepare_throwaway_kg(workdir, "preview.db", source=source)

    with KnowledgeStore(db_path=tmp_db) as store:
        if cold_start:
            if provider is None:
                raise ValueError("Cold-start requires an LLM provider.")
            pipeline = Pipeline(
                detector=NoopDetector(),
                resolver=AliasResolver(),
                store=store,
                cold_start_discoverer=(ColdStartEntityDiscoverer(provider)),
            )
        else:
            active = store.find_entities_by_status(
                EntityStatus.ACTIVE, limit=100_000
            )
            llm_resolver = None
            extractor = None
            if provider is not None:
                llm_resolver = LLMEntityResolver(
                    provider=provider,
                    entity_lookup=store.get_entity,
                    entity_batch_lookup=store.get_entities,
                )
                extractor = LLMRelationshipExtractor(
                    provider=provider,
                    entity_lookup=store.get_entity,
                    name_lookup=store.find_by_name,
                    entity_batch_lookup=store.get_entities,
                )
            pipeline = Pipeline(
                detector=RuleBasedDetector(active),
                resolver=AliasResolver(),
                store=store,
                llm_resolver=llm_resolver,
                extractor=extractor,
            )
        result = pipeline.run([article])
        data = _collect_preview(store, article.document_id.hex)
        metrics = store.get_run_metrics(result.run_id)

    payload = {
        "document_id": article.document_id.hex,
        "mode": "cold-start" if cold_start else "kg-driven",
        "title": article.title,
        "mentions": data["mentions"],
        "relationships": data["relationships"],
        "chunks_processed": (metrics.chunks_processed if metrics else 0),
        "token_usage": (
            {
                "input_tokens": metrics.input_tokens,
                "output_tokens": metrics.output_tokens,
            }
            if metrics
            else None
        ),
    }
    return payload


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Run the pipeline on a single article "
            "without persisting to the real KG; emit "
            "detections + proposals + relationships as "
            "JSON."
        ),
    )
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--article-file",
        type=Path,
        help=(
            "JSON file with title / body / url / "
            "source / optional document_id."
        ),
    )
    src.add_argument(
        "--text",
        help=(
            "Quick-path body string. Title / URL / "
            "source default to preview placeholders."
        ),
    )
    p.add_argument(
        "--kg-db",
        type=Path,
        default=None,
        help=(
            "Populated KG SQLite path. Required unless "
            "--cold-start is set; copied to a temp file "
            "so the source is never mutated."
        ),
    )
    p.add_argument(
        "--cold-start",
        action="store_true",
        help=(
            "Use cold-start mode: empty KG, LLM "
            "proposes entities from the raw text."
        ),
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=f"Ollama model (default: {_DEFAULT_MODEL}).",
    )
    p.add_argument(
        "--ollama-host",
        default=None,
        help="Override the Ollama daemon URL.",
    )
    p.add_argument(
        "--no-llm",
        action="store_true",
        help=(
            "Skip the LLM cascade (detection + alias "
            "resolution only). Ignored with "
            "--cold-start."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        default=None,
        help=("Where to write the JSON report. Defaults to stdout."),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Entry point for the preview CLI."""
    setup_logging()
    args = _build_parser().parse_args(argv)
    require_db_unless(args)
    article = load_article(article_file=args.article_file, text=args.text)
    provider: OllamaProvider | None = None
    if args.cold_start or not args.no_llm:
        provider = OllamaProvider(model=args.model, host=args.ollama_host)
    workdir = Path(tempfile.mkdtemp(prefix="um-preview-"))
    logger.info(
        "Preview workdir: %s (discarded after run)",
        workdir,
    )
    payload = preview(
        article,
        kg_db=args.kg_db,
        provider=provider,
        workdir=workdir,
        cold_start=args.cold_start,
    )
    output = json.dumps(payload, indent=2, default=str)
    if args.output is None:
        sys.stdout.write(output + "\n")
    else:
        args.output.write_text(output, encoding="utf-8")
        logger.info("Wrote %s", args.output)


if __name__ == "__main__":
    main()


__all__ = [
    "load_article",
    "main",
    "preview",
]
