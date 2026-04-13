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
    map_company_row,
)
from unstructured_mapping.wikidata.queries import (
    LISTED_COMPANIES_QUERY,
    build_query,
)

__all__ = [
    "LISTED_COMPANIES_QUERY",
    "MappedEntity",
    "SparqlClient",
    "SparqlError",
    "build_query",
    "map_company_row",
]
