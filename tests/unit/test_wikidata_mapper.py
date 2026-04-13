"""Tests for the Wikidata → Entity mapper."""

from unstructured_mapping.knowledge_graph import EntityType
from unstructured_mapping.wikidata.mapper import (
    map_central_bank_row,
    map_company_row,
    map_crypto_row,
    map_currency_row,
    map_exchange_row,
    map_index_row,
    map_regulator_row,
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


# -- central bank ----------------------------------------------


def test_map_central_bank_row_sets_subtype_and_country():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q53776", "uri"
        ),
        "itemLabel": _binding("Federal Reserve System"),
        "countryLabel": _binding("United States"),
    }
    result = map_central_bank_row(row)
    assert result is not None
    assert result.entity.entity_type is EntityType.ORGANIZATION
    assert result.entity.subtype == "central_bank"
    assert "United States" in result.entity.description
    assert result.entity.aliases == ("wikidata:Q53776",)


def test_map_central_bank_row_without_country_still_maps():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q1", "uri"
        ),
        "itemLabel": _binding("Some Bank"),
    }
    result = map_central_bank_row(row)
    assert result is not None
    assert "central bank" in result.entity.description.lower()


# -- regulator -------------------------------------------------


def test_map_regulator_row_sets_subtype_regulator():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q913975", "uri"
        ),
        "itemLabel": _binding(
            "Securities and Exchange Commission"
        ),
        "countryLabel": _binding("United States"),
    }
    result = map_regulator_row(row)
    assert result is not None
    assert result.entity.subtype == "regulator"
    assert "United States" in result.entity.description


# -- exchange --------------------------------------------------


def test_map_exchange_row_includes_mic_as_alias():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q13677", "uri"
        ),
        "itemLabel": _binding("New York Stock Exchange"),
        "countryLabel": _binding("United States"),
        "mic": _binding("XNYS"),
    }
    result = map_exchange_row(row)
    assert result is not None
    assert result.entity.subtype == "exchange"
    assert "mic:XNYS" in result.entity.aliases


def test_map_exchange_row_without_mic_has_no_mic_alias():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q1", "uri"
        ),
        "itemLabel": _binding("Some Exchange"),
    }
    result = map_exchange_row(row)
    assert result is not None
    assert not any(
        a.startswith("mic:") for a in result.entity.aliases
    )


# -- currency --------------------------------------------------


def test_map_currency_row_uses_asset_type_and_iso_alias():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q4917", "uri"
        ),
        "itemLabel": _binding("United States dollar"),
        "iso": _binding("USD"),
        "countryLabel": _binding("United States"),
    }
    result = map_currency_row(row)
    assert result is not None
    assert result.entity.entity_type is EntityType.ASSET
    assert result.entity.subtype == "currency"
    assert "iso:USD" in result.entity.aliases
    assert "USD" in result.entity.description


# -- index -----------------------------------------------------


def test_map_index_row_uses_asset_index_subtype():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q242345", "uri"
        ),
        "itemLabel": _binding("S&P 500"),
        "exchangeLabel": _binding("NYSE"),
        "countryLabel": _binding("United States"),
    }
    result = map_index_row(row)
    assert result is not None
    assert result.entity.entity_type is EntityType.ASSET
    assert result.entity.subtype == "index"
    assert "NYSE" in result.entity.description


# -- crypto ----------------------------------------------------


def test_map_crypto_row_includes_symbol_alias():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q131723", "uri"
        ),
        "itemLabel": _binding("Bitcoin"),
        "symbol": _binding("BTC"),
    }
    result = map_crypto_row(row)
    assert result is not None
    assert result.entity.entity_type is EntityType.ASSET
    assert result.entity.subtype == "crypto"
    assert "symbol:BTC" in result.entity.aliases
    assert "BTC" in result.entity.description


def test_map_crypto_row_without_symbol_still_maps():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q1", "uri"
        ),
        "itemLabel": _binding("Something Coin"),
    }
    result = map_crypto_row(row)
    assert result is not None
    assert not any(
        a.startswith("symbol:") for a in result.entity.aliases
    )


# -- reject rules apply to every mapper ------------------------


def test_every_mapper_rejects_missing_item():
    row = {"itemLabel": _binding("X")}
    for mapper in (
        map_central_bank_row,
        map_regulator_row,
        map_exchange_row,
        map_currency_row,
        map_index_row,
        map_crypto_row,
    ):
        assert mapper(row) is None


def test_every_mapper_rejects_qid_only_label():
    row = {
        "item": _binding(
            "http://www.wikidata.org/entity/Q42", "uri"
        ),
        "itemLabel": _binding("Q42"),
    }
    for mapper in (
        map_central_bank_row,
        map_regulator_row,
        map_exchange_row,
        map_currency_row,
        map_index_row,
        map_crypto_row,
    ):
        assert mapper(row) is None
