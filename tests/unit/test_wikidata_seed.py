"""Tests for the Wikidata seed CLI."""

import json
from pathlib import Path

import pytest

from unstructured_mapping.cli import wikidata_seed
from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
    KnowledgeStore,
)
from unstructured_mapping.wikidata.mapper import (
    MappedEntity,
)
from unstructured_mapping.wikidata.queries import (
    LISTED_COMPANIES_QUERY,
    build_query,
)


def _mapped(qid: str, name: str, aliases=()) -> MappedEntity:
    return MappedEntity(
        qid=qid,
        entity=Entity(
            canonical_name=name,
            entity_type=EntityType.ORGANIZATION,
            subtype="company",
            description=f"{name} is a company.",
            aliases=tuple([f"wikidata:{qid}", *aliases]),
        ),
    )


# -- build_query ------------------------------------------------


def test_build_query_substitutes_limit():
    sparql = build_query(LISTED_COMPANIES_QUERY, limit=42)
    assert "LIMIT 42" in sparql


def test_build_query_rejects_non_positive_limit():
    with pytest.raises(ValueError):
        build_query(LISTED_COMPANIES_QUERY, limit=0)


def test_all_registered_types_build_valid_queries():
    for kind, (template, _mapper) in (
        wikidata_seed._TYPE_HANDLERS.items()
    ):
        sparql = build_query(template, limit=5)
        assert "LIMIT 5" in sparql, kind
        assert "?item" in sparql, kind
        assert "?itemLabel" in sparql, kind


def test_queries_reference_expected_class_qids():
    """Class QIDs are load-bearing — a typo produces empty
    or absurd results. Pin them so a change that drifts
    away from a verified value fails CI."""
    from unstructured_mapping.wikidata import queries

    expected = {
        queries.LISTED_COMPANIES_QUERY: "Q4830453",
        queries.CENTRAL_BANKS_QUERY: "Q66344",
        queries.REGULATORS_QUERY: "Q105062392",
        queries.EXCHANGES_QUERY: "Q11691",
        queries.CURRENCIES_QUERY: "Q8142",
        queries.INDICES_QUERY: "Q223371",
        queries.CRYPTO_QUERY: "Q13479982",
    }
    for template, qid in expected.items():
        assert f"wd:{qid}" in template, (
            f"template missing wd:{qid}"
        )


def test_queries_use_subquery_limit_pattern():
    """Each template must cap the inner SELECT DISTINCT,
    not the outer SELECT. Putting LIMIT on the outer
    SELECT counts post-join rows and makes the label
    service drop most items to bare-QID fallback.
    """
    from unstructured_mapping.wikidata import queries

    templates = [
        queries.LISTED_COMPANIES_QUERY,
        queries.CENTRAL_BANKS_QUERY,
        queries.REGULATORS_QUERY,
        queries.EXCHANGES_QUERY,
        queries.CURRENCIES_QUERY,
        queries.INDICES_QUERY,
        queries.CRYPTO_QUERY,
    ]
    for tmpl in templates:
        assert "SELECT DISTINCT ?item" in tmpl
        # The {limit} placeholder must appear after the
        # inner DISTINCT block (i.e. inside the subquery).
        distinct_pos = tmpl.find("SELECT DISTINCT")
        limit_pos = tmpl.find("{limit}")
        assert 0 <= distinct_pos < limit_pos, (
            "LIMIT must follow the inner SELECT DISTINCT"
        )


def test_exchange_query_excludes_banks_and_brokerages():
    """v0.37.1: the exchange query must MINUS out banks
    (``Q22687``) and brokerage firms (``Q806735``).
    Without these clauses Wikidata lets Commerzbank, FXCM,
    Convergex, OTP banka etc. through because they hold
    a direct P31 stock-exchange assertion."""
    from unstructured_mapping.wikidata import queries

    template = queries.EXCHANGES_QUERY
    assert "MINUS" in template
    assert "wd:Q22687" in template
    assert "wd:Q806735" in template


def test_registered_types_cover_expected_set():
    expected = {
        "company",
        "central_bank",
        "regulator",
        "exchange",
        "currency",
        "index",
        "crypto",
    }
    assert (
        set(wikidata_seed._TYPE_HANDLERS) == expected
    )


# -- import_entities --------------------------------------------


def test_import_entities_creates_new_entries(tmp_path: Path):
    mapped = [_mapped("Q1", "Alpha"), _mapped("Q2", "Beta")]
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        created, skipped, counts = (
            wikidata_seed.import_entities(mapped, store)
        )
    assert created == 2
    assert skipped == 0
    assert counts["company"] == 2


def test_import_entities_dedups_by_wikidata_qid(
    tmp_path: Path,
):
    db = tmp_path / "kg.db"
    mapped = _mapped("Q1", "Alpha")
    with KnowledgeStore(db_path=db) as store:
        store.save_entity(mapped.entity)
        created, skipped, _ = wikidata_seed.import_entities(
            [_mapped("Q1", "Alpha Renamed")], store
        )
    # Same QID alias → already_imported skips even though
    # the canonical_name changed.
    assert created == 0
    assert skipped == 1


def test_import_entities_dedups_by_name_and_type(
    tmp_path: Path,
):
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        # Pre-existing curated entry (no Wikidata QID)
        store.save_entity(
            Entity(
                canonical_name="Apple Inc.",
                entity_type=EntityType.ORGANIZATION,
                subtype="company",
                description="Curated.",
            )
        )
        created, skipped, _ = wikidata_seed.import_entities(
            [_mapped("Q312", "Apple Inc.")], store
        )
    assert created == 0
    assert skipped == 1


def test_import_entities_dry_run_does_not_write(
    tmp_path: Path,
):
    db = tmp_path / "kg.db"
    mapped = [_mapped("Q1", "Alpha")]
    with KnowledgeStore(db_path=db) as store:
        created, skipped, _ = wikidata_seed.import_entities(
            mapped, store, dry_run=True
        )
        assert created == 1
        assert skipped == 0
        assert store.find_by_alias("wikidata:Q1") == []


def test_import_entities_tags_history_with_wikidata_reason(
    tmp_path: Path,
):
    db = tmp_path / "kg.db"
    mapped = [_mapped("Q1", "Alpha")]
    with KnowledgeStore(db_path=db) as store:
        wikidata_seed.import_entities(mapped, store)
        saved = store.find_by_alias("wikidata:Q1")[0]
        history = store.get_entity_history(saved.entity_id)
        assert history[0].reason == "wikidata-seed"


# -- snapshot ---------------------------------------------------


def test_write_snapshot_produces_seed_compatible_file(
    tmp_path: Path,
):
    mapped = [
        _mapped("Q1", "Alpha", aliases=("ticker:ALP",)),
    ]
    path = tmp_path / "snapshot.json"
    wikidata_seed._write_snapshot(mapped, path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    entry = data["entities"][0]
    assert entry["canonical_name"] == "Alpha"
    assert entry["entity_type"] == "organization"
    assert entry["subtype"] == "company"
    assert "wikidata:Q1" in entry["aliases"]
    assert "ticker:ALP" in entry["aliases"]
