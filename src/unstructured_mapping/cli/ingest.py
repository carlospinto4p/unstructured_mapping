"""Batch-ingest scraped articles through the pipeline.

Reads articles from the :class:`ArticleStore` written by
the scrapers and runs them end-to-end through
:class:`Pipeline` to populate the KG. Unlike
:mod:`cli.populate` (a seed loader for curated JSON +
Wikidata snapshots), this CLI actually drives the LLM
pipeline, creating provenance and relationship rows from
real news.

Why a separate CLI
------------------

v0.54.0 added ``article_failures`` + the
``Pipeline.run(resume_run_id=...)`` plumbing so a crashed
batch could be restarted without re-paying LLM tokens for
every article, but there was no user-facing flag to reach
it. The backlog item specified living on ``cli/populate``,
which is a seed loader; wiring ``--resume-run`` there
would be inert. This CLI is the right landing spot.

Usage::

    uv run python -m unstructured_mapping.cli.ingest \\
        --db data/knowledge.db \\
        --articles-db data/articles.db \\
        --source ap --limit 100

    # Resume only the articles that crashed in a prior run:
    uv run python -m unstructured_mapping.cli.ingest \\
        --db data/knowledge.db \\
        --articles-db data/articles.db \\
        --resume-run <run_id>

    # Cold-start bootstrap on an empty KG:
    uv run python -m unstructured_mapping.cli.ingest \\
        --db data/knowledge.db \\
        --articles-db data/articles.db \\
        --cold-start --limit 50

Resume semantics
----------------

When ``--resume-run`` is set, ``--source`` / ``--limit``
are ignored: the CLI pulls the exact set of failed
``document_id`` values from the KG
(:meth:`KnowledgeStore.find_failed_document_ids`), loads
the matching articles from the articles DB, and hands
the batch to :meth:`Pipeline.run` which filters again to
the same set. A fresh ``run_id`` is allocated for the
resumed attempt so the two runs remain separately
auditable via :mod:`cli.run_report` and :mod:`cli.run_diff`.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from unstructured_mapping.cli._argparse_helpers import (
    ARTICLES_DEFAULT_DB,
    add_db_argument,
)
from unstructured_mapping.cli._db_helpers import open_kg_store
from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
)
from unstructured_mapping.knowledge_graph.models import (
    EntityStatus,
)
from unstructured_mapping.pipeline import (
    AliasResolver,
    ClaudeProvider,
    ColdStartEntityDiscoverer,
    LLMEntityResolver,
    LLMProvider,
    LLMRelationshipExtractor,
    NoopDetector,
    OllamaProvider,
    Pipeline,
    PipelineResult,
    RuleBasedDetector,
)
from unstructured_mapping.web_scraping.models import Article
from unstructured_mapping.web_scraping.storage import (
    ArticleStore,
)

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_MODEL = "llama3.1:8b"
_DEFAULT_CLAUDE_MODEL = "claude-haiku-4-5-20251001"
_PROVIDERS = ("ollama", "claude")


def _build_provider(
    provider: str,
    *,
    model: str | None,
    ollama_host: str | None,
) -> LLMProvider:
    """Build the configured :class:`LLMProvider`.

    ``--model`` is optional; when omitted the default for
    the chosen provider is used so a bare
    ``--provider claude`` does not fail.
    """
    if provider == "ollama":
        return OllamaProvider(
            model=model or _DEFAULT_OLLAMA_MODEL,
            host=ollama_host,
        )
    if provider == "claude":
        return ClaudeProvider(model=model or _DEFAULT_CLAUDE_MODEL)
    raise ValueError(f"unknown provider: {provider!r}")


def _load_articles(
    articles_store: ArticleStore,
    *,
    kg_store: KnowledgeStore,
    source: str | None,
    limit: int | None,
    resume_run_id: str | None,
) -> list[Article]:
    """Fetch the articles batch for this invocation.

    Resume mode short-circuits the filters: we load only
    the ids the KG says failed last time. Non-resume mode
    applies ``--source`` / ``--limit`` as normal.
    """
    if resume_run_id is not None:
        failed_ids = kg_store.find_failed_document_ids(resume_run_id)
        if not failed_ids:
            logger.warning(
                "Run %s has no recorded article "
                "failures — nothing to resume.",
                resume_run_id,
            )
            return []
        logger.info(
            "Resuming run %s: loading %d failed article(s).",
            resume_run_id,
            len(failed_ids),
        )
        return articles_store.load(document_ids=failed_ids)
    return articles_store.load(source=source, limit=limit)


def _build_pipeline(
    store: KnowledgeStore,
    *,
    provider: LLMProvider | None,
    cold_start: bool,
    extract_relationships: bool,
) -> Pipeline:
    """Assemble the pipeline for this invocation.

    Three modes:

    * ``cold_start=True`` — empty-KG bootstrap; the LLM
      proposes entities directly. Requires ``provider``.
    * ``cold_start=False`` + ``provider is None`` — alias-
      only resolution (no LLM cascade, no extraction).
      Useful for cheap regression passes that only
      exercise the rule-based detector.
    * ``cold_start=False`` + ``provider is not None`` —
      full steady-state pipeline: detect, alias-resolve,
      LLM-resolve, and (optionally) extract relationships.
    """
    if cold_start:
        if provider is None:
            raise ValueError("Cold-start mode requires an LLM provider.")
        return Pipeline(
            detector=NoopDetector(),
            resolver=AliasResolver(),
            store=store,
            cold_start_discoverer=(ColdStartEntityDiscoverer(provider)),
        )
    active = store.find_entities_by_status(EntityStatus.ACTIVE, limit=100_000)
    llm_resolver = None
    extractor = None
    if provider is not None:
        llm_resolver = LLMEntityResolver(
            provider=provider,
            entity_lookup=store.get_entity,
            entity_batch_lookup=store.get_entities,
        )
        if extract_relationships:
            extractor = LLMRelationshipExtractor(
                provider=provider,
                entity_lookup=store.get_entity,
                name_lookup=store.find_by_name,
                entity_batch_lookup=store.get_entities,
            )
    return Pipeline(
        detector=RuleBasedDetector(active),
        resolver=AliasResolver(),
        store=store,
        llm_resolver=llm_resolver,
        extractor=extractor,
    )


def ingest(
    articles: list[Article],
    store: KnowledgeStore,
    *,
    provider: LLMProvider | None,
    cold_start: bool = False,
    extract_relationships: bool = True,
    resume_run_id: str | None = None,
) -> PipelineResult:
    """Run the pipeline over ``articles`` and return the result.

    :param articles: Pre-loaded article batch. The caller
        owns filtering — this function does not re-query
        the articles DB.
    :param store: Target KG store (will be mutated).
    :param provider: LLM backend. ``None`` is only valid
        when ``cold_start`` is ``False``; it disables the
        LLM cascade entirely.
    :param cold_start: Bootstrap mode for an empty KG.
    :param extract_relationships: When ``True`` and a
        provider is wired, the pipeline runs relationship
        extraction. Ignored in cold-start mode.
    :param resume_run_id: Forwarded to
        :meth:`Pipeline.run`; see that method for semantics.
    :return: The :class:`PipelineResult` for the run.
    """
    pipeline = _build_pipeline(
        store,
        provider=provider,
        cold_start=cold_start,
        extract_relationships=extract_relationships,
    )
    return pipeline.run(articles, resume_run_id=resume_run_id)


def _summarise(result: PipelineResult) -> str:
    """Render a short one-paragraph summary for stdout."""
    skipped = len(result.results) - result.documents_processed
    failed = sum(1 for r in result.results if r.error is not None)
    lines = [
        f"Run {result.run_id}",
        f"  articles submitted:   {len(result.results)}",
        f"  processed:            {result.documents_processed}",
        f"  skipped (idempotent): {skipped - failed}",
        f"  failed:               {failed}",
        f"  provenance rows:      {result.provenances_saved}",
        f"  new entities:         {result.proposals_saved}",
        f"  relationships:        {result.relationships_saved}",
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Batch-ingest scraped articles through the "
            "LLM pipeline; populates the KG with "
            "provenance and relationship rows."
        ),
    )
    add_db_argument(p, required=True)
    p.add_argument(
        "--articles-db",
        type=Path,
        default=ARTICLES_DEFAULT_DB,
        help=(
            f"Path to the scraped-articles SQLite DB "
            f"(default: {ARTICLES_DEFAULT_DB})."
        ),
    )
    p.add_argument(
        "--source",
        default=None,
        help=(
            "Filter articles by source (e.g. 'ap', 'bbc', "
            "'reuters'). Ignored when --resume-run is set."
        ),
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Maximum number of articles to process. "
            "Ignored when --resume-run is set (the failed "
            "set is used as-is)."
        ),
    )
    p.add_argument(
        "--resume-run",
        default=None,
        help=(
            "Resume a prior run by re-processing only the "
            "articles recorded in its article_failures "
            "rows. A fresh run_id is allocated for the "
            "retry so the two attempts remain separately "
            "auditable."
        ),
    )
    p.add_argument(
        "--cold-start",
        action="store_true",
        help=(
            "Bootstrap an empty KG: bypass detection and "
            "resolution and let the LLM propose entities "
            "from raw text. Requires an LLM provider."
        ),
    )
    p.add_argument(
        "--provider",
        choices=_PROVIDERS,
        default="ollama",
        help="LLM provider (default: ollama).",
    )
    p.add_argument(
        "--model",
        default=None,
        help=(
            "Provider model tag. Defaults: "
            f"{_DEFAULT_OLLAMA_MODEL} for ollama, "
            f"{_DEFAULT_CLAUDE_MODEL} for claude."
        ),
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
            "Skip the LLM cascade entirely (alias-resolve "
            "only). Ignored with --cold-start."
        ),
    )
    p.add_argument(
        "--no-extract-relationships",
        action="store_true",
        help=(
            "Skip LLM relationship extraction; still runs "
            "detection and resolution. No effect in "
            "cold-start mode."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Entry point for the ingest CLI."""
    setup_logging()
    args = _build_parser().parse_args(argv)

    if args.cold_start and args.no_llm:
        raise SystemExit("error: --cold-start requires an LLM provider.")

    provider: LLMProvider | None = None
    if args.cold_start or not args.no_llm:
        provider = _build_provider(
            args.provider,
            model=args.model,
            ollama_host=args.ollama_host,
        )

    # Note the CWD so "error: KG database not found at
    # ..." messages resolve relatively for users running
    # from the repo root.
    logger.info("Working directory: %s", os.getcwd())
    with open_kg_store(args.db) as kg_store:
        with ArticleStore(args.articles_db) as articles_store:
            articles = _load_articles(
                articles_store,
                kg_store=kg_store,
                source=args.source,
                limit=args.limit,
                resume_run_id=args.resume_run,
            )
        if not articles:
            logger.info("No articles to process — exiting.")
            return
        logger.info(
            "Submitting %d article(s) to the pipeline "
            "(cold_start=%s, provider=%s).",
            len(articles),
            args.cold_start,
            args.provider if provider is not None else "(none)",
        )
        result = ingest(
            articles,
            kg_store,
            provider=provider,
            cold_start=args.cold_start,
            extract_relationships=not args.no_extract_relationships,
            resume_run_id=args.resume_run,
        )
    sys.stdout.write(_summarise(result) + "\n")


if __name__ == "__main__":
    main()


__all__ = [
    "ingest",
    "main",
]
