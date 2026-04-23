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
from unstructured_mapping.wikidata import TYPE_REGISTRY
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
    for kind, handler in TYPE_REGISTRY.items():
        sparql = build_query(handler.query, limit=5)
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
        assert f"wd:{qid}" in template, f"template missing wd:{qid}"


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


def test_exchange_query_excludes_ats_and_market_makers():
    """v0.49.13: the exchange query must additionally
    MINUS out alternative trading systems (``Q438711``),
    market makers (``Q1137319``), and foreign-exchange
    companies (``Q5468383``). KCG Americas and similar
    correctly-classified ATSs leak through the bank /
    brokerage filter because they inherit from the ATS
    class, not the bank or brokerage class."""
    from unstructured_mapping.wikidata import queries

    template = queries.EXCHANGES_QUERY
    assert "wd:Q438711" in template
    assert "wd:Q1137319" in template
    assert "wd:Q5468383" in template


def test_exchange_query_applies_curated_blocklist():
    """v0.49.13: the exchange query must also block
    specific mis-tagged offenders that carry only a direct
    ``P31 stock exchange`` assertion and no class hierarchy
    the subclass-walking MINUS can catch. The bootstrap
    blocklist covers FXCM (``Q5973741``) and Convergex
    (``Q93355333``)."""
    from unstructured_mapping.wikidata import queries

    template = queries.EXCHANGES_QUERY
    assert "FILTER(?item NOT IN" in template
    assert "wd:Q5973741" in template
    assert "wd:Q93355333" in template


def test_company_query_excludes_central_banks():
    """The company query must MINUS out central banks
    (``Q66344``). Without this clause Wikidata lets Bank of
    Japan and Swiss National Bank through via the
    business/P414 walk, because they hold listing entries
    for currency/reserve-asset assertions."""
    from unstructured_mapping.wikidata import queries

    template = queries.LISTED_COMPANIES_QUERY
    assert "MINUS" in template
    assert "wd:Q66344" in template


def test_dedupe_mapped_by_qid_merges_aliases_from_duplicates():
    """Multiple rows for one QID produce one entity with merged aliases.

    OPTIONAL joins on ticker/exchange/etc. fan each Wikidata
    item out into several bindings. The dedup step must keep
    the first description/subtype and union the aliases so
    every external ID surfaced across bindings survives.
    """
    from unstructured_mapping.knowledge_graph import (
        Entity,
        EntityType,
    )
    from unstructured_mapping.wikidata import (
        MappedEntity,
        dedupe_mapped_by_qid,
    )

    apple_a = MappedEntity(
        qid="Q312",
        entity=Entity(
            canonical_name="Apple Inc.",
            entity_type=EntityType.ORGANIZATION,
            subtype="company",
            description="Apple is a publicly listed company.",
            aliases=("wikidata:Q312", "ticker:AAPL"),
        ),
    )
    apple_b = MappedEntity(
        qid="Q312",
        entity=Entity(
            canonical_name="Apple Inc.",
            entity_type=EntityType.ORGANIZATION,
            subtype="company",
            description="ignored — first wins",
            aliases=("wikidata:Q312", "isin:US0378331005"),
        ),
    )
    microsoft = MappedEntity(
        qid="Q2283",
        entity=Entity(
            canonical_name="Microsoft",
            entity_type=EntityType.ORGANIZATION,
            subtype="company",
            description="Microsoft is a publicly listed company.",
            aliases=("wikidata:Q2283", "ticker:MSFT"),
        ),
    )

    result = dedupe_mapped_by_qid([apple_a, apple_b, microsoft])
    assert [m.qid for m in result] == ["Q312", "Q2283"]
    apple_out = result[0].entity
    assert apple_out.description == ("Apple is a publicly listed company.")
    assert apple_out.aliases == (
        "wikidata:Q312",
        "ticker:AAPL",
        "isin:US0378331005",
    )


def test_dedupe_mapped_by_qid_preserves_single_rows():
    """Rows with unique QIDs pass through unchanged."""
    from unstructured_mapping.knowledge_graph import (
        Entity,
        EntityType,
    )
    from unstructured_mapping.wikidata import (
        MappedEntity,
        dedupe_mapped_by_qid,
    )

    one = MappedEntity(
        qid="Q1",
        entity=Entity(
            canonical_name="One",
            entity_type=EntityType.ORGANIZATION,
            subtype="company",
            description="d",
            aliases=("wikidata:Q1",),
        ),
    )
    result = dedupe_mapped_by_qid([one])
    assert result == [one]


def test_dedupe_mapped_by_qid_empty_input():
    """Empty input → empty output, no blowups."""
    from unstructured_mapping.wikidata import (
        dedupe_mapped_by_qid,
    )

    assert dedupe_mapped_by_qid([]) == []


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
    assert set(TYPE_REGISTRY) == expected


# -- import_entities --------------------------------------------


def test_import_entities_creates_new_entries(tmp_path: Path):
    mapped = [_mapped("Q1", "Alpha"), _mapped("Q2", "Beta")]
    db = tmp_path / "kg.db"
    with KnowledgeStore(db_path=db) as store:
        created, skipped, counts = wikidata_seed.import_entities(
            mapped, store
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
    assert data["reason"] == "wikidata-seed"
    entry = data["entities"][0]
    assert entry["canonical_name"] == "Alpha"
    assert entry["entity_type"] == "organization"
    assert entry["subtype"] == "company"
    assert "wikidata:Q1" in entry["aliases"]
    assert "ticker:ALP" in entry["aliases"]
