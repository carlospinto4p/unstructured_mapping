"""Benchmark cold-start vs KG-driven entity discovery.

Runs a labelled article set through the pipeline in one
or both modes and reports precision / recall / F1 against
the ground-truth labels. The intent is a regression
harness for prompt or provider changes: start with 50-100
labelled articles, grow the set over time, and re-run
before landing any change that might shift discovery
quality.

See ``docs/pipeline/13_cold_start.md`` for what cold-start
does and how it differs from the steady-state pipeline.

Usage::

    uv run python -m unstructured_mapping.cli.benchmark_cold_start \\
        --labelled data/benchmark/articles.json \\
        --mode both \\
        --seed-db data/knowledge.db \\
        --model llama3.1:8b

Labelled file format (JSON)::

    {
      "articles": [
        {
          "document_id": "f0b1...",
          "title": "Apple Q3 earnings",
          "body": "Apple reported ...",
          "source": "reuters",
          "entities": [
            {"canonical_name": "Apple",
             "entity_type": "organization"},
            {"canonical_name": "Tim Cook",
             "entity_type": "person"}
          ]
        }
      ]
    }

Matching: discovered entities are joined to ground-truth
by ``(canonical_name.lower(), entity_type.lower())``. The
match is strict — alias matches are NOT considered here
because the benchmark asks "did the LLM name it the way
we expected?". Alias coverage is a separate concern.
"""

import argparse
import json
import logging
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from unstructured_mapping.cli._logging import setup_logging
from unstructured_mapping.knowledge_graph import (
    EntityType,
    KnowledgeStore,
)
from unstructured_mapping.pipeline import (
    AliasResolver,
    ColdStartEntityDiscoverer,
    LLMEntityResolver,
    NoopDetector,
    OllamaProvider,
    Pipeline,
    RuleBasedDetector,
)
from unstructured_mapping.knowledge_graph.models import (
    EntityStatus,
)
from unstructured_mapping.web_scraping.models import (
    Article,
)

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "llama3.1:8b"
_DEFAULT_MODE = "both"
_MODES = ("cold-start", "kg-driven", "both")


@dataclass(frozen=True, slots=True)
class LabelledEntity:
    """One ground-truth entity attached to an article."""

    canonical_name: str
    entity_type: str


@dataclass(frozen=True, slots=True)
class LabelledArticle:
    """An article plus the entities it *should* surface."""

    article: Article
    expected: tuple[LabelledEntity, ...]


@dataclass(frozen=True, slots=True)
class ArticleScore:
    """Per-article precision / recall."""

    document_id: str
    expected: frozenset[tuple[str, str]]
    discovered: frozenset[tuple[str, str]]

    @property
    def true_positives(self) -> int:
        return len(self.expected & self.discovered)

    @property
    def false_positives(self) -> int:
        return len(self.discovered - self.expected)

    @property
    def false_negatives(self) -> int:
        return len(self.expected - self.discovered)


@dataclass(frozen=True, slots=True)
class ModeReport:
    """Aggregate scorecard for one run mode."""

    mode: str
    articles: tuple[ArticleScore, ...]
    tokens_in: int = 0
    tokens_out: int = 0

    @property
    def precision(self) -> float:
        tp = sum(a.true_positives for a in self.articles)
        fp = sum(a.false_positives for a in self.articles)
        denom = tp + fp
        return tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        tp = sum(a.true_positives for a in self.articles)
        fn = sum(a.false_negatives for a in self.articles)
        denom = tp + fn
        return tp / denom if denom else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Result of one benchmark invocation.

    :param modes: One :class:`ModeReport` per executed run
        mode, in invocation order.
    """

    modes: tuple[ModeReport, ...] = field(default=())


def load_labelled(path: Path) -> list[LabelledArticle]:
    """Parse the labelled-articles JSON file.

    :param path: File path to the labelled set.
    :return: One :class:`LabelledArticle` per entry.
    :raises ValueError: When a record is missing a required
        field or declares an unknown ``entity_type``.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = raw.get("articles", [])
    out: list[LabelledArticle] = []
    for idx, entry in enumerate(entries):
        try:
            doc_id = entry["document_id"]
            body = entry["body"]
        except KeyError as exc:
            raise ValueError(f"Article {idx} missing field: {exc}") from exc
        expected: list[LabelledEntity] = []
        for ent in entry.get("entities", ()):
            try:
                name = ent["canonical_name"]
                etype = ent["entity_type"]
            except KeyError as exc:
                raise ValueError(
                    f"Article {idx} entity missing: {exc}"
                ) from exc
            # Validate against the enum so typos fail fast
            # — a silently wrong label would poison recall.
            EntityType(etype.lower())
            expected.append(
                LabelledEntity(
                    canonical_name=name,
                    entity_type=etype.lower(),
                )
            )
        article = Article(
            title=entry.get("title", ""),
            body=body,
            url=entry.get("url", ""),
            source=entry.get("source", "benchmark"),
            document_id=UUID(doc_id),
        )
        out.append(
            LabelledArticle(
                article=article,
                expected=tuple(expected),
            )
        )
    return out


def _discovered_for_document(
    store: KnowledgeStore, document_id: str
) -> frozenset[tuple[str, str]]:
    """Pull discovered entities for one document.

    Projects the ``(Entity, Provenance)`` pairs returned
    by the store into the case-insensitive
    ``(canonical_name, entity_type)`` tuples the
    benchmark scores against. De-duplicates because a
    KG-driven run may resolve the same entity on more
    than one mention in a single article.
    """
    pairs = store.find_mentions_with_entities(document_id)
    return frozenset(
        (
            entity.canonical_name.lower(),
            entity.entity_type.value.lower(),
        )
        for entity, _prov in pairs
    )


def _expected_set(
    labelled: LabelledArticle,
) -> frozenset[tuple[str, str]]:
    return frozenset(
        (e.canonical_name.lower(), e.entity_type) for e in labelled.expected
    )


def _score_articles(
    labelled: list[LabelledArticle],
    store: KnowledgeStore,
) -> tuple[ArticleScore, ...]:
    scores: list[ArticleScore] = []
    for la in labelled:
        doc_id = la.article.document_id.hex
        discovered = _discovered_for_document(store, doc_id)
        scores.append(
            ArticleScore(
                document_id=doc_id,
                expected=_expected_set(la),
                discovered=discovered,
            )
        )
    return tuple(scores)


def _run_cold_start(
    labelled: list[LabelledArticle],
    provider: OllamaProvider,
    db_path: Path,
) -> ModeReport:
    """Cold-start mode: empty KG, LLM proposes everything."""
    articles = [la.article for la in labelled]
    with KnowledgeStore(db_path=db_path) as store:
        pipeline = Pipeline(
            detector=NoopDetector(),
            resolver=AliasResolver(),
            store=store,
            cold_start_discoverer=(ColdStartEntityDiscoverer(provider)),
        )
        result = pipeline.run(articles)
        metrics = store.get_run_metrics(result.run_id)
        scores = _score_articles(labelled, store)
    return ModeReport(
        mode="cold-start",
        articles=scores,
        tokens_in=metrics.input_tokens if metrics else 0,
        tokens_out=(metrics.output_tokens if metrics else 0),
    )


def _run_kg_driven(
    labelled: list[LabelledArticle],
    provider: OllamaProvider,
    db_path: Path,
) -> ModeReport:
    """KG-driven mode: seeded KG, detector + LLM cascade."""
    articles = [la.article for la in labelled]
    with KnowledgeStore(db_path=db_path) as store:
        # Steady-state: rule-based detection over the
        # active KG plus the LLM cascade for unresolved
        # and ambiguous mentions. Relationship extraction
        # is deliberately skipped — the benchmark scores
        # entity coverage only.
        active = store.find_entities_by_status(
            EntityStatus.ACTIVE, limit=100_000
        )
        pipeline = Pipeline(
            detector=RuleBasedDetector(active),
            resolver=AliasResolver(),
            store=store,
            llm_resolver=LLMEntityResolver(
                provider=provider,
                entity_lookup=store.get_entity,
                entity_batch_lookup=store.get_entities,
            ),
        )
        result = pipeline.run(articles)
        metrics = store.get_run_metrics(result.run_id)
        scores = _score_articles(labelled, store)
    return ModeReport(
        mode="kg-driven",
        articles=scores,
        tokens_in=metrics.input_tokens if metrics else 0,
        tokens_out=(metrics.output_tokens if metrics else 0),
    )


def benchmark(
    labelled: list[LabelledArticle],
    *,
    provider: OllamaProvider,
    seed_db: Path | None,
    mode: str,
    workdir: Path,
) -> BenchmarkReport:
    """Run the benchmark and return the aggregated report.

    :param labelled: Parsed labelled articles.
    :param provider: LLM backend — only Ollama is wired in
        the default CLI, but any :class:`LLMProvider` works
        from Python.
    :param seed_db: Populated KG to copy for the kg-driven
        run. Required when ``mode`` is ``"kg-driven"`` or
        ``"both"``; ignored otherwise. Copied to a
        throwaway path so the source file is never
        mutated.
    :param mode: One of ``"cold-start"``, ``"kg-driven"``,
        ``"both"``.
    :param workdir: Directory where temporary benchmark
        databases are created.
    """
    if mode not in _MODES:
        raise ValueError(f"mode must be one of {_MODES}: {mode!r}")
    reports: list[ModeReport] = []
    if mode in ("cold-start", "both"):
        cs_db = workdir / "cold_start.db"
        if cs_db.exists():
            cs_db.unlink()
        reports.append(_run_cold_start(labelled, provider, cs_db))
    if mode in ("kg-driven", "both"):
        if seed_db is None:
            raise ValueError("kg-driven mode requires --seed-db")
        if not seed_db.exists():
            raise FileNotFoundError(seed_db)
        kg_db = workdir / "kg_driven.db"
        # Copy so the live KG is never written to by a
        # benchmark run — provenance from labelled
        # articles would otherwise leak into real data.
        shutil.copyfile(seed_db, kg_db)
        reports.append(_run_kg_driven(labelled, provider, kg_db))
    return BenchmarkReport(modes=tuple(reports))


def _log_report(report: BenchmarkReport) -> None:
    """Emit a per-mode and per-article summary."""
    for mr in report.modes:
        logger.info(
            "Mode %-10s  precision=%.3f recall=%.3f "
            "f1=%.3f  (tokens_in=%d, tokens_out=%d)",
            mr.mode,
            mr.precision,
            mr.recall,
            mr.f1,
            mr.tokens_in,
            mr.tokens_out,
        )
        for a in mr.articles:
            logger.info(
                "  %s  TP=%d FP=%d FN=%d",
                a.document_id[:12],
                a.true_positives,
                a.false_positives,
                a.false_negatives,
            )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Benchmark cold-start vs KG-driven entity "
            "discovery against a labelled article set."
        ),
    )
    p.add_argument(
        "--labelled",
        type=Path,
        required=True,
        help="Path to the labelled-articles JSON file.",
    )
    p.add_argument(
        "--mode",
        choices=_MODES,
        default=_DEFAULT_MODE,
        help=(f"Which pipeline mode(s) to run. Default: {_DEFAULT_MODE}."),
    )
    p.add_argument(
        "--seed-db",
        type=Path,
        default=None,
        help=(
            "Populated KG SQLite path. Required for "
            "'kg-driven' and 'both'. Copied to a temp "
            "file; never mutated."
        ),
    )
    p.add_argument(
        "--model",
        default=_DEFAULT_MODEL,
        help=(f"Ollama model tag (default: {_DEFAULT_MODEL})."),
    )
    p.add_argument(
        "--ollama-host",
        default=None,
        help="Override the Ollama daemon URL.",
    )
    p.add_argument(
        "--workdir",
        type=Path,
        default=None,
        help=(
            "Where to place temporary benchmark DBs. "
            "Defaults to a system temp directory that "
            "is preserved so runs can be inspected."
        ),
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Entry point for the cold-start benchmark CLI."""
    setup_logging()
    args = _build_parser().parse_args(argv)
    sqlite3.register_converter(  # ensure consistent text
        "TEXT", lambda b: b.decode("utf-8")
    )
    labelled = load_labelled(args.labelled)
    logger.info(
        "Loaded %d labelled articles from %s",
        len(labelled),
        args.labelled,
    )
    provider = OllamaProvider(model=args.model, host=args.ollama_host)
    workdir = args.workdir or Path(tempfile.mkdtemp(prefix="um-benchmark-"))
    workdir.mkdir(parents=True, exist_ok=True)
    logger.info("Benchmark workdir: %s", workdir)
    report = benchmark(
        labelled,
        provider=provider,
        seed_db=args.seed_db,
        mode=args.mode,
        workdir=workdir,
    )
    _log_report(report)


if __name__ == "__main__":
    main()


__all__ = [
    "ArticleScore",
    "BenchmarkReport",
    "LabelledArticle",
    "LabelledEntity",
    "ModeReport",
    "benchmark",
    "load_labelled",
    "main",
]
