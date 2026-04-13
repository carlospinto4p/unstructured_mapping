"""Tests for the Wikidata → Entity mapper."""

from unstructured_mapping.knowledge_graph import EntityType
from unstructured_mapping.wikidata.mapper import (
    map_company_row,
)


def _binding(value: str, type_: str = "literal") -> dict:
    return {"type": type_, "value": value}


def _company_row(**overrides) -> dict:
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q312", "uri"
        ),
        "itemLabel": _binding("Apple Inc."),
        "description": _binding(
            "American multinational technology company"
        ),
        "ticker": _binding("AAPL"),
        "isin": _binding("US0378331005"),
        "exchange": _binding(
            "http://www.wikidata.org/entity/Q82059", "uri"
        ),
        "exchangeLabel": _binding("Nasdaq"),
        "country": _binding(
            "http://www.wikidata.org/entity/Q30", "uri"
        ),
        "countryLabel": _binding("United States"),
    }
    row.update(overrides)
    return row


# -- happy path -------------------------------------------------


def test_map_company_row_returns_organization_entity():
    result = map_company_row(_company_row())
    assert result is not None
    assert result.qid == "Q312"
    entity = result.entity
    assert entity.canonical_name == "Apple Inc."
    assert entity.entity_type is EntityType.ORGANIZATION
    assert entity.subtype == "company"


def test_map_company_row_prefixes_external_ids_as_aliases():
    result = map_company_row(_company_row())
    aliases = set(result.entity.aliases)
    assert "wikidata:Q312" in aliases
    assert "ticker:AAPL" in aliases
    assert "isin:US0378331005" in aliases


def test_map_company_row_description_includes_country_and_ticker():
    result = map_company_row(_company_row())
    desc = result.entity.description
    assert "United States" in desc
    assert "Nasdaq" in desc
    assert "AAPL" in desc
    assert "multinational technology" in desc


# -- missing / optional fields ---------------------------------


def test_map_company_row_without_ticker_omits_ticker_alias():
    row = _company_row()
    row.pop("ticker")
    result = map_company_row(row)
    assert not any(
        a.startswith("ticker:") for a in result.entity.aliases
    )


def test_map_company_row_without_isin_omits_isin_alias():
    row = _company_row()
    row.pop("isin")
    result = map_company_row(row)
    assert not any(
        a.startswith("isin:") for a in result.entity.aliases
    )


def test_map_company_row_without_optional_fields_still_maps():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q5", "uri"
        ),
        "itemLabel": _binding("Example Corp"),
    }
    result = map_company_row(row)
    assert result is not None
    assert result.entity.canonical_name == "Example Corp"
    assert result.entity.aliases == ("wikidata:Q5",)


# -- reject rows that don't carry signal ------------------------


def test_map_company_row_returns_none_when_label_is_qid():
    # Wikidata returns the bare QID as label when no English
    # label exists — such rows carry no signal for the KG.
    row = _company_row(itemLabel=_binding("Q312"))
    assert map_company_row(row) is None


def test_map_company_row_returns_none_when_item_missing():
    row = _company_row()
    row.pop("item")
    assert map_company_row(row) is None


def test_map_company_row_returns_none_when_label_missing():
    row = _company_row()
    row.pop("itemLabel")
    assert map_company_row(row) is None
