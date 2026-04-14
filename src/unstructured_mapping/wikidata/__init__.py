"""Wikidata seed pipeline.

Bootstraps the knowledge graph with financial entities from
Wikidata. The pipeline queries the Wikidata SPARQL endpoint,
maps each result row to an :class:`Entity` (with aliases
carrying external identifiers such as tickers and QIDs), and
hands the batch to the CLI loader for dedup and persistence.

The scope is narrow by design: only entities that are
plausibly market-moving or financially relevant are imported.
See ``docs/seed/wikidata.md`` for the scope rationale and the
external-identifier alias convention.
"""

from unstructured_mapping.wikidata.client import (
    SparqlClient,
    SparqlError,
)
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
    build_query,
)
from unstructured_mapping.wikidata.registry import (
    TYPE_REGISTRY,
    TypeHandler,
)

__all__ = [
    "CENTRAL_BANKS_QUERY",
    "CRYPTO_QUERY",
    "CURRENCIES_QUERY",
    "EXCHANGES_QUERY",
    "INDICES_QUERY",
    "LISTED_COMPANIES_QUERY",
    "MappedEntity",
    "REGULATORS_QUERY",
    "SparqlClient",
    "SparqlError",
    "TYPE_REGISTRY",
    "TypeHandler",
    "build_query",
    "map_central_bank_row",
    "map_company_row",
    "map_crypto_row",
    "map_currency_row",
    "map_exchange_row",
    "map_index_row",
    "map_regulator_row",
]
