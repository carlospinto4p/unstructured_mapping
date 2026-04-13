"""SPARQL query templates for the Wikidata seed pipeline.

Each query is parameterised by a ``LIMIT`` clause so the
caller can cap the result size. Queries are kept as module
constants (rather than built dynamically) so the exact
SPARQL sent to Wikidata is auditable and copy-pasteable
into the public query editor for debugging.

Coverage by type:

- Listed companies (``LISTED_COMPANIES_QUERY``) — ordered
  by market capitalisation.
- Central banks (``CENTRAL_BANKS_QUERY``).
- Financial regulators (``REGULATORS_QUERY``).
- Stock exchanges (``EXCHANGES_QUERY``).
- Fiat currencies (``CURRENCIES_QUERY``).
- Stock market indices (``INDICES_QUERY``).
- Cryptocurrencies (``CRYPTO_QUERY``).

Rating agencies, commodities, flagship legislation, and
named persons are intentionally *not* covered by SPARQL.
Those populations are small and heterogeneous enough that
the curated seed file (``data/seed/financial_entities.json``)
is a better source — see ``docs/seed/wikidata.md`` for the
rationale.

Conventions:

- Each query must ``SELECT`` at least ``?item``, ``?itemLabel``,
  and ``?description``. Mappers assume these bindings exist.
- Optional columns (country, currency, symbol, etc.) are
  typed into the ``OPTIONAL`` block so missing data never
  prunes an otherwise-valid row.
- Labels use the Wikidata label-service hack
  (``SERVICE wikibase:label``) so we get one English label
  per row without nested subqueries.
- Class filters use ``wdt:P31/wdt:P279*`` so subclasses
  (e.g. "national central bank" under "central bank") are
  included without listing each explicitly.
"""

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

_CENTRAL_BANKS_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?description
       ?country ?countryLabel
WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q46825 .
  OPTIONAL {{ ?item wdt:P17 ?country . }}
  OPTIONAL {{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
LIMIT {limit}
"""

_REGULATORS_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?description
       ?country ?countryLabel
WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q17278032 .
  OPTIONAL {{ ?item wdt:P17 ?country . }}
  OPTIONAL {{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
LIMIT {limit}
"""

_EXCHANGES_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?description
       ?country ?countryLabel ?mic
WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q11691 .
  OPTIONAL {{ ?item wdt:P17 ?country . }}
  OPTIONAL {{ ?item wdt:P2283 ?mic . }}
  OPTIONAL {{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
LIMIT {limit}
"""

_CURRENCIES_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?description
       ?iso ?country ?countryLabel
WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q8142 .
  ?item wdt:P498 ?iso .
  OPTIONAL {{ ?item wdt:P17 ?country . }}
  OPTIONAL {{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
LIMIT {limit}
"""

_INDICES_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?description
       ?exchange ?exchangeLabel ?country ?countryLabel
WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q167270 .
  OPTIONAL {{ ?item wdt:P414 ?exchange . }}
  OPTIONAL {{ ?item wdt:P17  ?country . }}
  OPTIONAL {{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
LIMIT {limit}
"""

_CRYPTO_TEMPLATE = """
SELECT DISTINCT ?item ?itemLabel ?description ?symbol
WHERE {{
  ?item wdt:P31/wdt:P279* wd:Q13479982 .
  OPTIONAL {{ ?item wdt:P498 ?symbol . }}
  OPTIONAL {{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en" .
  }}
}}
LIMIT {limit}
"""

#: Phase 1 — equity universe.
LISTED_COMPANIES_QUERY = _LISTED_COMPANIES_TEMPLATE

#: Phase 2 — institutional actors.
CENTRAL_BANKS_QUERY = _CENTRAL_BANKS_TEMPLATE
REGULATORS_QUERY = _REGULATORS_TEMPLATE
EXCHANGES_QUERY = _EXCHANGES_TEMPLATE

#: Phase 3 — asset classes.
CURRENCIES_QUERY = _CURRENCIES_TEMPLATE
INDICES_QUERY = _INDICES_TEMPLATE
CRYPTO_QUERY = _CRYPTO_TEMPLATE


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
