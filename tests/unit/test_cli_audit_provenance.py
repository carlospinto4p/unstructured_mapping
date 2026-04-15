"""Tests for the provenance quality audit CLI."""

import csv
from datetime import datetime, timedelta, timezone

from tests.unit.conftest import make_org
from unstructured_mapping.cli import audit_provenance
from unstructured_mapping.cli.audit_provenance import (
    find_narrow_spread,
    find_short_snippets,
    find_thin_mentions,
)
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
    Provenance,
)


def _mention(
    entity_id: str,
    doc_id: str,
    snippet: str = "...plenty of context around...",
    at: datetime | None = None,
    text: str = "mention",
) -> Provenance:
    return Provenance(
        entity_id=entity_id,
        document_id=doc_id,
        source="test",
        mention_text=text,
        context_snippet=snippet,
        detected_at=at or datetime.now(timezone.utc),
    )


# -- short snippets -------------------------------------


def test_find_short_snippets_flags_low_token_rows(
    tmp_path,
):
    db = tmp_path / "kg.db"
    apple = make_org("Apple", entity_id="apple")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_provenances(
            [
                _mention(
                    "apple",
                    "doc-short",
                    snippet="tiny",
                ),
                _mention(
                    "apple",
                    "doc-long",
                    snippet=(
                        "this context snippet is long "
                        "enough to pass the token bar"
                    ),
                ),
            ]
        )
        findings = find_short_snippets(store, min_tokens=5)
    assert len(findings) == 1
    assert findings[0].document_id == "doc-short"
    assert findings[0].token_estimate < 5


# -- thin mentions --------------------------------------


def test_find_thin_mentions_counts_distinct_pairs(
    tmp_path,
):
    db = tmp_path / "kg.db"
    apple = make_org("Apple", entity_id="apple")
    msft = make_org("Microsoft", entity_id="msft")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(apple)
        store.save_entity(msft)
        store.save_provenances(
            [
                _mention("apple", "doc-a"),
                _mention("apple", "doc-b"),
                _mention("msft", "doc-a"),
            ]
        )
        thin = find_thin_mentions(store, min_mentions=2)
    # Apple has 2 mentions (not thin); Microsoft has 1.
    thin_names = {f.canonical_name for f in thin}
    assert thin_names == {"Microsoft"}


def test_find_thin_mentions_includes_zero_mention(
    tmp_path,
):
    """Entities with no provenance show up at the top of
    the thin-mentions list — that's the whole point of
    the LEFT JOIN."""
    db = tmp_path / "kg.db"
    orphan = make_org("Orphan", entity_id="orphan")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(orphan)
        thin = find_thin_mentions(store, min_mentions=1)
    assert len(thin) == 1
    assert thin[0].mention_count == 0


# -- narrow temporal spread ------------------------------


def test_find_narrow_spread_flags_sub_day_clusters(
    tmp_path,
):
    db = tmp_path / "kg.db"
    bounce = make_org("Bounce Inc", entity_id="bounce")
    durable = make_org("Durable Corp", entity_id="durable")
    t0 = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(bounce)
        store.save_entity(durable)
        store.save_provenances(
            [
                # One-shot event: same hour, different
                # articles → spans minutes.
                _mention(
                    "bounce",
                    "doc-1",
                    at=t0,
                    text="m1",
                ),
                _mention(
                    "bounce",
                    "doc-2",
                    at=t0 + timedelta(minutes=20),
                    text="m2",
                ),
                # Durable: mentioned across 30 days.
                _mention(
                    "durable",
                    "doc-a",
                    at=t0,
                    text="m1",
                ),
                _mention(
                    "durable",
                    "doc-b",
                    at=t0 + timedelta(days=30),
                    text="m2",
                ),
            ]
        )
        narrow = find_narrow_spread(store, min_days=1)
    names = {f.canonical_name for f in narrow}
    assert names == {"Bounce Inc"}


def test_find_narrow_spread_skips_single_mention(
    tmp_path,
):
    """Single-mention entities are handled by the
    thin-mentions report; the narrow-spread report
    ignores them so the signal is not dominated by
    zero-second spans."""
    db = tmp_path / "kg.db"
    lonely = make_org("Lonely", entity_id="lonely")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(lonely)
        store.save_provenances([_mention("lonely", "doc-1")])
        narrow = find_narrow_spread(store, min_days=1)
    assert narrow == []


# -- CSV export -----------------------------------------


def test_main_csv_export_contains_all_finding_types(
    tmp_path,
):
    db = tmp_path / "kg.db"
    short = make_org("Short", entity_id="short")
    thin = make_org("Thin", entity_id="thin")
    bounce = make_org("Bounce", entity_id="bounce")
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(short)
        store.save_entity(thin)
        store.save_entity(bounce)
        store.save_provenances(
            [
                _mention(
                    "short",
                    "doc-1",
                    snippet="x",
                    at=t0,
                ),
                _mention(
                    "bounce",
                    "doc-1",
                    at=t0,
                    text="m1",
                ),
                _mention(
                    "bounce",
                    "doc-2",
                    at=t0 + timedelta(minutes=5),
                    text="m2",
                ),
            ]
        )

    out_csv = tmp_path / "audit.csv"
    audit_provenance.main(
        [
            "--db",
            str(db),
            "--min-tokens",
            "5",
            "--min-mentions",
            "2",
            "--min-days",
            "1",
            "--csv",
            str(out_csv),
        ]
    )
    with out_csv.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    types = {r["finding_type"] for r in rows}
    assert types == {
        "short_snippet",
        "thin_mentions",
        "narrow_spread",
    }
