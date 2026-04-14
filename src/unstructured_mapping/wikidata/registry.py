"""Registry of supported Wikidata entity categories.

Maps each public ``--type`` value (``company``,
``central_bank``, ``regulator``, ``exchange``, ``currency``,
``index``, ``crypto``) to the SPARQL template and row
mapper that handle it.

Lives in the ``wikidata`` package — not in the CLI — so any
non-CLI consumer (tests, scripts, future batch importers)
can enumerate supported types without reaching into a CLI
internal. Adding a new category is a single entry here plus
the query/mapper additions in the neighbouring modules.
"""

from collections.abc import Callable
from dataclasses import dataclass

from unstructured_mapping.wikidata.mapper import (
    MappedEntity,
    map_central_bank_row,
    map_company_row,
    map_crypto_row,
    map_currency_row,
    map_exchange_row,
    map_index_row,
    map_regulator_row,
)
from unstructured_mapping.wikidata.queries import (
    CENTRAL_BANKS_QUERY,
    CRYPTO_QUERY,
    CURRENCIES_QUERY,
    EXCHANGES_QUERY,
    INDICES_QUERY,
    LISTED_COMPANIES_QUERY,
    REGULATORS_QUERY,
)


@dataclass(frozen=True, slots=True)
class TypeHandler:
    """SPARQL template + row mapper for one category.

    :param query: Parameterised SPARQL template. Pass to
        :func:`wikidata.build_query` with a concrete limit
        before sending to the endpoint.
    :param mapper: Converts a single SPARQL binding row
        into a :class:`MappedEntity` (or ``None`` when the
        row lacks a usable label).
    """

    query: str
    mapper: Callable[[dict], MappedEntity | None]


#: Canonical registry. Keys are the public type names
#: accepted by the Wikidata seed CLI.
TYPE_REGISTRY: dict[str, TypeHandler] = {
    "company": TypeHandler(
        LISTED_COMPANIES_QUERY, map_company_row
    ),
    "central_bank": TypeHandler(
        CENTRAL_BANKS_QUERY, map_central_bank_row
    ),
    "regulator": TypeHandler(
        REGULATORS_QUERY, map_regulator_row
    ),
    "exchange": TypeHandler(
        EXCHANGES_QUERY, map_exchange_row
    ),
    "currency": TypeHandler(
        CURRENCIES_QUERY, map_currency_row
    ),
    "index": TypeHandler(
        INDICES_QUERY, map_index_row
    ),
    "crypto": TypeHandler(
        CRYPTO_QUERY, map_crypto_row
    ),
}
