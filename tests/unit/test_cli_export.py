"""Tests for the ``cli.export`` CLI.

Covers the three filter branches (type / subtype / since),
the two output formats (``jsonl`` / ``json-ld``), the
relationship and provenance opt-ins, and the ``main``
stdout contract.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from unstructured_mapping.cli.export import (
    SUPPORTED_FORMATS,
    export_kg,
    main,
)
from unstructured_mapping.knowledge_graph import (
    KnowledgeStore,
    Provenance,
    Relationship,
)
from unstructured_mapping.knowledge_graph.models import (
    EntityType,
)

from .conftest import make_entity


@pytest.fixture
def populated_kg(tmp_path):
    """Two orgs + one policymaker, one relationship, one
    provenance row per entity, suitable for exercising
    every filter branch and both opt-in streams."""
    db = tmp_path / "kg.db"
    apple = make_entity(
        canonical_name="Apple",
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
        aliases=("AAPL",),
    )
    msft = make_entity(
        canonical_name="Microsoft",
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
    )
    powell = make_entity(
        canonical_name="Powell",
        entity_type=EntityType.PERSON,
        subtype="policymaker",
    )
    with KnowledgeStore(db_path=db) as store:
        for e in (apple, msft, powell):
            store.save_entity(e)
        store.save_relationship(
            Relationship(
                source_id=apple.entity_id,
                target_id=msft.entity_id,
                relation_type="partners_with",
                description="ctx",
            )
        )
        for entity in (apple, msft, powell):
            store.save_provenance(
                Provenance(
                    entity_id=entity.entity_id,
                    document_id=f"doc-{entity.entity_id[:6]}",
                    source="t",
                    mention_text=entity.canonical_name,
                    context_snippet="ctx",
                )
            )
    return db, {"apple": apple, "msft": msft, "powell": powell}


def test_supported_formats_declares_both():
    assert "jsonl" in SUPPORTED_FORMATS
    assert "json-ld" in SUPPORTED_FORMATS


def test_export_jsonl_writes_entities_only_by_default(populated_kg, tmp_path):
    db, _ = populated_kg
    out = tmp_path / "out"
    with KnowledgeStore(db_path=db) as store:
        counts = export_kg(store, out, fmt="jsonl")

    assert counts == {"entities": 3}
    assert (out / "entities.jsonl").exists()
    assert not (out / "relationships.jsonl").exists()
    assert not (out / "provenance.jsonl").exists()


def test_export_jsonl_respects_type_filter(populated_kg, tmp_path):
    db, _ = populated_kg
    out = tmp_path / "out"
    with KnowledgeStore(db_path=db) as store:
        counts = export_kg(
            store,
            out,
            fmt="jsonl",
            entity_type=EntityType.ORGANIZATION,
        )

    assert counts["entities"] == 2
    lines = (
        (out / "entities.jsonl")
        .read_text(encoding="utf-8")
        .strip()
        .splitlines()
    )
    records = [json.loads(line) for line in lines]
    assert {r["canonical_name"] for r in records} == {"Apple", "Microsoft"}
    # Aliases + enum values must be JSON-safe.
    apple_row = next(r for r in records if r["canonical_name"] == "Apple")
    assert apple_row["entity_type"] == "organization"
    assert apple_row["aliases"] == ["AAPL"]


def test_export_jsonl_subtype_narrows_within_type(populated_kg, tmp_path):
    db, _ = populated_kg
    out = tmp_path / "out"
    with KnowledgeStore(db_path=db) as store:
        counts = export_kg(
            store,
            out,
            fmt="jsonl",
            entity_type=EntityType.ORGANIZATION,
            subtype="company",
        )

    assert counts["entities"] == 2


def test_export_jsonl_since_filter_matches_recent_entities(
    populated_kg, tmp_path
):
    db, _ = populated_kg
    out = tmp_path / "out"
    far_future = datetime(2099, 1, 1, tzinfo=timezone.utc)
    with KnowledgeStore(db_path=db) as store:
        counts = export_kg(store, out, fmt="jsonl", since=far_future)

    assert counts["entities"] == 0


def test_export_jsonl_with_relationships_and_provenance(
    populated_kg, tmp_path
):
    db, _ = populated_kg
    out = tmp_path / "out"
    with KnowledgeStore(db_path=db) as store:
        counts = export_kg(
            store,
            out,
            fmt="jsonl",
            with_relationships=True,
            with_provenance=True,
        )

    assert counts["entities"] == 3
    assert counts["relationships"] == 1
    assert counts["provenance"] == 3


def test_export_jsonld_wraps_graph_with_context(populated_kg, tmp_path):
    db, _ = populated_kg
    out = tmp_path / "out"
    with KnowledgeStore(db_path=db) as store:
        counts = export_kg(store, out, fmt="json-ld")

    assert counts["entities"] == 3
    path = out / "entities.jsonld"
    assert path.exists()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert "@context" in doc
    assert "@vocab" in doc["@context"]
    # The @context alias renames "entities" onto @graph,
    # so the payload sits under that key.
    assert isinstance(doc["entities"], list)
    assert len(doc["entities"]) == 3


def test_export_unsupported_format_raises(populated_kg, tmp_path):
    db, _ = populated_kg
    out = tmp_path / "out"
    with KnowledgeStore(db_path=db) as store:
        with pytest.raises(ValueError, match="unsupported"):
            export_kg(store, out, fmt="xml")  # type: ignore[arg-type]


def test_main_requires_type_when_subtype_is_given(populated_kg, tmp_path):
    db, _ = populated_kg
    out = tmp_path / "out"
    with pytest.raises(SystemExit, match="--subtype requires --type"):
        main(
            [
                "--db",
                str(db),
                "--output-dir",
                str(out),
                "--subtype",
                "company",
            ]
        )


def test_main_writes_jsonl_and_prints_summary(populated_kg, tmp_path, capsys):
    db, _ = populated_kg
    out = tmp_path / "out"
    main(
        [
            "--db",
            str(db),
            "--output-dir",
            str(out),
            "--type",
            "organization",
        ]
    )
    captured = capsys.readouterr()
    assert "entities=2" in captured.out
    assert (out / "entities.jsonl").exists()


def test_main_writes_jsonld_with_relationships(
    populated_kg, tmp_path, capsys
):
    db, _ = populated_kg
    out = tmp_path / "out"
    main(
        [
            "--db",
            str(db),
            "--output-dir",
            str(out),
            "--format",
            "json-ld",
            "--with-relationships",
        ]
    )
    captured = capsys.readouterr()
    assert "relationships=1" in captured.out
    rel_path: Path = out / "relationships.jsonld"
    assert rel_path.exists()
    doc = json.loads(rel_path.read_text(encoding="utf-8"))
    assert "@context" in doc
    assert len(doc["relationships"]) == 1
