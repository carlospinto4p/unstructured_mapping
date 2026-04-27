"""Shared test fixtures for unstructured_mapping unit tests."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeStore,
    Provenance,
)
from unstructured_mapping.pipeline.llm_provider import (
    LLMProvider,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    Mention,
    ResolvedMention,
)
from unstructured_mapping.web_scraping.models import Article


def make_provenance(
    entity_id: str,
    *,
    document_id: str,
    source: str = "test",
    mention_text: str = "mention",
    context_snippet: str = "...plenty of context around...",
    detected_at: datetime | None = None,
) -> Provenance:
    """Build a :class:`Provenance` for KG tests.

    Shared between alias and provenance-audit CLI tests —
    both used to ship near-identical local helpers.
    """
    return Provenance(
        entity_id=entity_id,
        document_id=document_id,
        source=source,
        mention_text=mention_text,
        context_snippet=context_snippet,
        detected_at=detected_at or datetime.now(timezone.utc),
    )


def add_mentions_to_store(
    store: KnowledgeStore,
    entity_id: str,
    count: int,
    *,
    source: str = "test",
) -> None:
    """Save ``count`` synthetic provenances for an entity.

    Each row gets a unique ``document_id`` so the test's
    mention count matches regardless of dedup rules.
    """
    detected = datetime.now(timezone.utc)
    store.save_provenances(
        [
            make_provenance(
                entity_id,
                document_id=f"doc-{entity_id}-{i}",
                source=source,
                mention_text="x",
                context_snippet="x",
                detected_at=detected,
            )
            for i in range(count)
        ]
    )


def make_entity(**kwargs):
    """Flexible entity factory — all fields via kwargs.

    Defaults to a minimal ``PERSON`` entity. KG-level
    tests use this when they need arbitrary entity
    configurations.
    """
    defaults = {
        "canonical_name": "Test Entity",
        "entity_type": EntityType.PERSON,
        "description": "A test entity.",
    }
    defaults.update(kwargs)
    return Entity(**defaults)


def make_org(
    name: str,
    *,
    aliases: tuple[str, ...] = (),
    entity_id: str | None = None,
) -> Entity:
    """Build a minimal ``ORGANIZATION`` entity.

    Convenience wrapper around :func:`make_entity` for
    pipeline tests, which almost always want an org
    with a name and optional aliases. ``entity_id``
    defaults to a slug of ``name`` so IDs are stable
    and readable in assertions.
    """
    return Entity(
        canonical_name=name,
        entity_type=EntityType.ORGANIZATION,
        description=f"Test entity {name}",
        aliases=aliases,
        entity_id=(
            entity_id
            if entity_id is not None
            else name.lower().replace(" ", "_")
        ),
    )


def make_chunk(
    text: str = "The Fed raised rates.",
    *,
    doc_id: str = "doc1",
    chunk_index: int = 0,
    section_name: str | None = None,
) -> Chunk:
    """Build a minimal :class:`Chunk` for pipeline tests."""
    return Chunk(
        document_id=doc_id,
        chunk_index=chunk_index,
        text=text,
        section_name=section_name,
    )


def make_mention(
    form: str,
    start: int,
    end: int,
    candidates: tuple[str, ...] = (),
) -> Mention:
    """Build a :class:`Mention` for detection/resolution tests."""
    return Mention(
        surface_form=form,
        span_start=start,
        span_end=end,
        candidate_ids=candidates,
    )


def make_resolved(
    entity_id: str,
    surface_form: str,
    snippet: str = "...context...",
) -> ResolvedMention:
    """Build a :class:`ResolvedMention` for pipeline tests."""
    return ResolvedMention(
        entity_id=entity_id,
        surface_form=surface_form,
        context_snippet=snippet,
    )


def write_seed_file(path: Path, entities: list[dict]) -> Path:
    """Write a seed-compatible JSON file for loader tests.

    Shared between seed-loader tests (``test_cli_seed.py``)
    and orchestrator tests (``test_cli_populate.py``) so
    both exercise the same on-disk format. Creates missing
    parent directories so callers can pass nested paths.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "entities": entities}),
        encoding="utf-8",
    )
    return path


def make_article(
    body: str = "Apple and Microsoft both grew.",
    title: str = "Tech news",
    source: str = "bbc",
) -> Article:
    """Build an :class:`Article` for orchestrator tests."""
    return Article(
        title=title,
        body=body,
        url=f"https://example.com/{title}",
        source=source,
    )


class FakeProvider(LLMProvider):
    """Reusable fake LLM provider for tests.

    Supports single or multiple responses (popped in
    order). Captures all calls for assertion.

    :param response: A single response string or a list
        of strings (popped in order; last one repeats).
    :param supports_json_mode: Whether the provider
        claims to support JSON mode.
    """

    provider_name = "fake"
    model_name = "fake-1"
    context_window = 4096

    def __init__(
        self,
        response: str | list[str] = "{}",
        *,
        supports_json_mode: bool = True,
    ):
        self._responses = (
            [response] if isinstance(response, str) else list(response)
        )
        self._supports_json_mode = supports_json_mode
        self.calls: list[tuple[str, str | None, bool]] = []

    @property
    def supports_json_mode(self) -> bool:
        return self._supports_json_mode

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
    ) -> str:
        self.calls.append((prompt, system, json_mode))
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


# -- shared CLI test fixtures -----------------------------------


@pytest.fixture
def seed_file(tmp_path: Path) -> Path:
    """Single seed file with two entities for seed-loader tests."""
    return write_seed_file(
        tmp_path / "seed.json",
        [
            {
                "canonical_name": "Federal Reserve",
                "entity_type": "organization",
                "subtype": "central_bank",
                "description": "US central bank.",
                "aliases": ["Fed", "FOMC"],
            },
            {
                "canonical_name": "Gold",
                "entity_type": "asset",
                "subtype": "commodity",
                "description": "Precious metal.",
            },
        ],
    )


@pytest.fixture
def seed_dir(tmp_path: Path) -> Path:
    """Seed directory with curated + Wikidata sub-dirs."""
    base = tmp_path / "seed"
    write_seed_file(
        base / "financial_entities.json",
        [
            {
                "canonical_name": "Federal Reserve",
                "entity_type": "organization",
                "subtype": "central_bank",
                "description": "US central bank.",
                "aliases": ["Fed"],
            }
        ],
    )
    write_seed_file(
        base / "wikidata" / "currency.json",
        [
            {
                "canonical_name": "US dollar",
                "entity_type": "asset",
                "subtype": "currency",
                "description": "USD.",
            }
        ],
    )
    write_seed_file(
        base / "wikidata" / "company.json",
        [
            {
                "canonical_name": "Apple Inc.",
                "entity_type": "organization",
                "subtype": "company",
                "description": "Tech.",
            }
        ],
    )
    return base


@pytest.fixture
def articles_db(tmp_path: Path):
    """Two articles from different sources for filter tests."""
    from unstructured_mapping.web_scraping.storage import (
        ArticleStore,
    )

    db = tmp_path / "articles.db"
    ap_article = make_article(body="AP body", title="AP story", source="ap")
    bbc_article = make_article(
        body="BBC body", title="BBC story", source="bbc"
    )
    with ArticleStore(db) as store:
        store.save([ap_article, bbc_article])
    return db, ap_article, bbc_article


@pytest.fixture
def kg_db(tmp_path: Path) -> Path:
    """Pre-initialised KG database file."""
    db = tmp_path / "kg.db"
    # Pre-create the file so open_kg_store does not reject it.
    with KnowledgeStore(db_path=db):
        pass
    return db
