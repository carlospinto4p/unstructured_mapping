"""SPARQL query templates for the Wikidata seed pipeline.

Each query is parameterised by a ``LIMIT`` clause so the
caller can cap the result size. Queries are kept as module
constants (rather than built dynamically) so the exact
SPARQL sent to Wikidata is auditable and copy-pasteable
into the public query editor for debugging.

Phase 1 covers listed companies. Additional query templates
for central banks, regulators, indices, and currencies will
be added in later phases — see ``docs/seed/wikidata.md``
for the full scope plan.

Conventions:

- Each query must ``SELECT`` at least ``?item``, ``?itemLabel``,
  and ``?description``. Mappers assume these bindings exist.
- Company-specific queries add ``?ticker``, ``?isin``,
  ``?exchangeLabel``, and ``?countryLabel`` when available.
- Labels use the Wikidata label-service hack
  (``SERVICE wikibase:label``) so we get one English label
  per row without nested subqueries.
"""

#: Listed companies ordered by market capitalisation
#: (property P2226). We constrain to entities that are
#: instances of (P31) "business" / "public company" /
#: "enterprise" (Q4830453 — business) or any of its
#: subclasses, and that have a stock-exchange listing
#: (P414). Ordering by market cap DESC gives the most
#: impactful subset first, which matters when the caller
#: uses ``--limit``.
_LISTED_COMPANIES_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?description
       ?ticker ?isin ?exchange ?exchangeLabel
       ?country ?countryLabel ?marketCap
WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q4830453 .
  ?item p:P414 ?listing .
  ?listing ps:P414 ?exchange .
  OPTIONAL {{ ?listing pq:P249 ?ticker . }}
  OPTIONAL {{ ?item wdt:P946 ?isin . }}
  OPTIONAL {{ ?item wdt:P17  ?country . }}
  OPTIONAL {{ ?item wdt:P2226 ?marketCap . }}
  OPTIONAL {{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
ORDER BY DESC(?marketCap)
LIMIT {limit}
"""

#: Default query for phase 1. Substitute ``{limit}`` via
#: :func:`build_query` to avoid hand-formatting at call sites.
LISTED_COMPANIES_QUERY = _LISTED_COMPANIES_TEMPLATE


def build_query(template: str, *, limit: int) -> str:
    """Render a query template with a concrete ``LIMIT``.

    :param template: A SPARQL template containing a
        single ``{limit}`` placeholder.
    :param limit: Positive integer row cap. Values above
        a few thousand risk endpoint timeouts — callers
        should paginate instead of requesting huge sets.
    :return: The fully-formed SPARQL query string.
    :raises ValueError: If ``limit`` is non-positive.
    """
    if limit <= 0:
        raise ValueError("limit must be positive")
    return template.format(limit=limit)
