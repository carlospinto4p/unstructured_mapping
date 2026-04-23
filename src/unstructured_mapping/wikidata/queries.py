"""SPARQL query templates for the Wikidata seed pipeline.

Each query is parameterised by a ``LIMIT`` clause so the
caller can cap the result size. Queries are kept as module
constants (rather than built dynamically) so the exact
SPARQL sent to Wikidata is auditable and copy-pasteable
into the public query editor for debugging.

Query shape (idiomatic on Wikidata)::

    SELECT ... WHERE {
      { SELECT DISTINCT ?item WHERE { <core filter> } LIMIT N }
      OPTIONAL { ... }
      ...
      SERVICE wikibase:label { ... }
    }

The **inner subquery** picks the N distinct items first,
so the ``LIMIT`` caps entity count — not the cartesian
product of entity × exchange × country × description.
Without this, OPTIONAL joins explode the row count,
``SERVICE wikibase:label`` runs out of budget, and most
rows come back with their QID as the label (which the
mapper then rejects as an un-labelled row). The subquery
pattern fixes that.

Coverage by type:

- Listed companies (``LISTED_COMPANIES_QUERY``).
- Central banks (``CENTRAL_BANKS_QUERY``).
- Financial regulators (``REGULATORS_QUERY``).
- Stock exchanges (``EXCHANGES_QUERY``).
- Fiat currencies (``CURRENCIES_QUERY``).
- Stock market indices (``INDICES_QUERY``).
- Cryptocurrencies (``CRYPTO_QUERY``).

Rating agencies, commodities, flagship legislation, and
named persons are intentionally *not* covered by SPARQL —
see ``docs/seed/wikidata.md`` for the rationale.

Class QIDs are verified against known anchor entities
(Fed, S&P 500, Bitcoin, …). A typo in one of these
constants silently produces an empty (or absurd) import,
so changes to these values require re-running the
anchor probe documented in ``docs/seed/wikidata.md``.
"""

#: Class QIDs used in the filters. The original v0.33.0
#: shipping set contained several guessed values — one
#: produced religious-art rows for "central_bank", another
#: produced record labels for "index". The current values
#: were discovered by probing the ``wdt:P31`` classes of
#: known anchor entities; see the commit history for the
#: discovery script.
_Q_BUSINESS = "Q4830453"  # business
_Q_CENTRAL_BANK = "Q66344"  # central bank
_Q_FIN_REGULATOR = "Q105062392"  # financial regulatory agency
_Q_STOCK_EXCHANGE = "Q11691"  # stock exchange
_Q_CURRENCY = "Q8142"  # currency
_Q_STOCK_INDEX = "Q223371"  # stock market index
_Q_CRYPTOCURRENCY = "Q13479982"  # cryptocurrency

#: Exclusion QIDs used by the exchange query. Wikidata
#: occasionally tags banks, brokerages, ATSs, market
#: makers, and FX firms with P31 stock-exchange, so the
#: direct-instance filter alone lets Commerzbank, FXCM,
#: KCG Americas, etc. through. The exchange query applies
#: these as MINUS clauses to scrub them back out without
#: touching genuine bourses.
_Q_BANK = "Q22687"  # bank
_Q_BROKERAGE = "Q806735"  # brokerage firm
_Q_ATS = "Q438711"  # alternative trading system
_Q_MARKET_MAKER = "Q1137319"  # market maker
_Q_FX_COMPANY = "Q5468383"  # foreign exchange company

#: Curated blocklist of QIDs that are *mis-tagged* on
#: Wikidata — they carry a direct ``P31 stock exchange``
#: assertion *without* a bank / brokerage / ATS / market
#: maker / FX-company class that a subclass-walking MINUS
#: could catch. Verified individually when first reported
#: (see v0.49.13 for the bootstrap set). Extend this list
#: when a new offender surfaces in a snapshot review rather
#: than widening the class-based MINUS to risk excluding
#: genuine bourses.
_EXCHANGE_BLOCKLIST_QIDS: tuple[str, ...] = (
    "Q5973741",  # FXCM — retail FX broker, tagged only as Q11691.
    "Q93355333",  # Convergex — US broker-dealer, tagged only as Q11691.
)


def _blocklist_filter(qids: tuple[str, ...]) -> str:
    """Render a ``FILTER(?item NOT IN (wd:Q…, wd:Q…))`` clause.

    Produces an empty string when ``qids`` is empty so the
    rendered query stays identical to the class-only form.

    :param qids: Iterable of bare Wikidata QIDs.
    :return: SPARQL fragment, with the same indentation as
        the surrounding ``MINUS`` blocks.
    """
    if not qids:
        return ""
    refs = ", ".join(f"wd:{q}" for q in qids)
    return f"      FILTER(?item NOT IN ({refs})) ."


#: Listed companies — instances of ``business`` (or any
#: subclass) that have a stock-exchange listing (P414).
#: No ORDER BY: earlier versions sorted by market cap
#: (P2226) to prefer the biggest firms, but that forces
#: Wikidata to materialise and sort a huge intermediate
#: result set and regularly times out with HTTP 502. For
#: a curated top-N import, pass specific tickers or QIDs
#: to a future targeted query instead of relying on a
#: SPARQL-wide sort.
#: Central banks hold P414 (stock exchange listing) entries
#: for currency/reserve-asset listings on some exchanges,
#: which the naive ``Q4830453`` (business) subclass-of walk
#: picks up as companies — Bank of Japan and Swiss National
#: Bank regularly turned up in ``company.json`` with no
#: ticker. The MINUS mirrors the bank/brokerage scrub in
#: ``_EXCHANGES_TEMPLATE``.
_LISTED_COMPANIES_TEMPLATE = f"""
SELECT ?item ?itemLabel ?description
       ?ticker ?isin ?exchange ?exchangeLabel
       ?country ?countryLabel
WHERE {{{{
  {{{{
    SELECT DISTINCT ?item ?listing ?exchange WHERE {{{{
      ?item wdt:P31/wdt:P279* wd:{_Q_BUSINESS} .
      ?item p:P414 ?listing .
      ?listing ps:P414 ?exchange .
      MINUS {{{{ ?item wdt:P31/wdt:P279* wd:{_Q_CENTRAL_BANK} . }}}}
    }}}}
    LIMIT {{limit}}
  }}}}
  OPTIONAL {{{{ ?listing pq:P249 ?ticker . }}}}
  OPTIONAL {{{{ ?item wdt:P946 ?isin . }}}}
  OPTIONAL {{{{ ?item wdt:P17  ?country . }}}}
  OPTIONAL {{{{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}}}
  SERVICE wikibase:label {{{{
    bd:serviceParam wikibase:language "en" .
  }}}}
}}}}
"""

_CENTRAL_BANKS_TEMPLATE = f"""
SELECT ?item ?itemLabel ?description
       ?country ?countryLabel
WHERE {{{{
  {{{{
    SELECT DISTINCT ?item WHERE {{{{
      ?item wdt:P31/wdt:P279* wd:{_Q_CENTRAL_BANK} .
    }}}}
    LIMIT {{limit}}
  }}}}
  OPTIONAL {{{{ ?item wdt:P17 ?country . }}}}
  OPTIONAL {{{{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}}}
  SERVICE wikibase:label {{{{
    bd:serviceParam wikibase:language "en" .
  }}}}
}}}}
"""

_REGULATORS_TEMPLATE = f"""
SELECT ?item ?itemLabel ?description
       ?country ?countryLabel
WHERE {{{{
  {{{{
    SELECT DISTINCT ?item WHERE {{{{
      ?item wdt:P31/wdt:P279* wd:{_Q_FIN_REGULATOR} .
    }}}}
    LIMIT {{limit}}
  }}}}
  OPTIONAL {{{{ ?item wdt:P17 ?country . }}}}
  OPTIONAL {{{{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}}}
  SERVICE wikibase:label {{{{
    bd:serviceParam wikibase:language "en" .
  }}}}
}}}}
"""

#: Stock exchanges use *direct* instance-of (no P279*
#: subclass expansion) to exclude clearing houses,
#: brokerages, and other adjacent entities that inherit
#: from the exchange class. The inner ``MINUS`` blocks
#: additionally scrub banks, brokerage firms, alternative
#: trading systems, market makers, and foreign-exchange
#: companies that Wikidata directly tags as P31 stock
#: exchange (Commerzbank, KCG Americas, OTP banka, …).
#: The trailing ``FILTER(?item NOT IN ...)`` is a last-
#: mile blocklist for firms that are mis-tagged on
#: Wikidata and carry no class hierarchy a subclass walk
#: can catch (FXCM, Convergex). See v0.37.1 / v0.49.13.
_EXCHANGES_TEMPLATE = f"""
SELECT ?item ?itemLabel ?description
       ?country ?countryLabel ?mic
WHERE {{{{
  {{{{
    SELECT DISTINCT ?item WHERE {{{{
      ?item wdt:P31 wd:{_Q_STOCK_EXCHANGE} .
      MINUS {{{{ ?item wdt:P31/wdt:P279* wd:{_Q_BANK} . }}}}
      MINUS {{{{ ?item wdt:P31/wdt:P279* wd:{_Q_BROKERAGE} . }}}}
      MINUS {{{{ ?item wdt:P31/wdt:P279* wd:{_Q_ATS} . }}}}
      MINUS {{{{ ?item wdt:P31/wdt:P279* wd:{_Q_MARKET_MAKER} . }}}}
      MINUS {{{{ ?item wdt:P31/wdt:P279* wd:{_Q_FX_COMPANY} . }}}}
{_blocklist_filter(_EXCHANGE_BLOCKLIST_QIDS)}
    }}}}
    LIMIT {{limit}}
  }}}}
  OPTIONAL {{{{ ?item wdt:P17 ?country . }}}}
  OPTIONAL {{{{ ?item wdt:P2283 ?mic . }}}}
  OPTIONAL {{{{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}}}
  SERVICE wikibase:label {{{{
    bd:serviceParam wikibase:language "en" .
  }}}}
}}}}
"""

_CURRENCIES_TEMPLATE = f"""
SELECT ?item ?itemLabel ?description
       ?iso ?country ?countryLabel
WHERE {{{{
  {{{{
    SELECT DISTINCT ?item ?iso WHERE {{{{
      ?item wdt:P31/wdt:P279* wd:{_Q_CURRENCY} .
      ?item wdt:P498 ?iso .
    }}}}
    LIMIT {{limit}}
  }}}}
  OPTIONAL {{{{ ?item wdt:P17 ?country . }}}}
  OPTIONAL {{{{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}}}
  SERVICE wikibase:label {{{{
    bd:serviceParam wikibase:language "en" .
  }}}}
}}}}
"""

_INDICES_TEMPLATE = f"""
SELECT ?item ?itemLabel ?description
       ?exchange ?exchangeLabel ?country ?countryLabel
WHERE {{{{
  {{{{
    SELECT DISTINCT ?item WHERE {{{{
      ?item wdt:P31/wdt:P279* wd:{_Q_STOCK_INDEX} .
    }}}}
    LIMIT {{limit}}
  }}}}
  OPTIONAL {{{{ ?item wdt:P414 ?exchange . }}}}
  OPTIONAL {{{{ ?item wdt:P17  ?country . }}}}
  OPTIONAL {{{{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}}}
  SERVICE wikibase:label {{{{
    bd:serviceParam wikibase:language "en" .
  }}}}
}}}}
"""

#: Crypto uses direct instance-of (no P279*) to exclude
#: crypto exchanges, which the wide subclass tree would
#: otherwise pull in alongside actual cryptocurrencies.
_CRYPTO_TEMPLATE = f"""
SELECT ?item ?itemLabel ?description ?symbol
WHERE {{{{
  {{{{
    SELECT DISTINCT ?item WHERE {{{{
      ?item wdt:P31 wd:{_Q_CRYPTOCURRENCY} .
    }}}}
    LIMIT {{limit}}
  }}}}
  OPTIONAL {{{{ ?item wdt:P498 ?symbol . }}}}
  OPTIONAL {{{{
    ?item schema:description ?description .
    FILTER(LANG(?description) = "en")
  }}}}
  SERVICE wikibase:label {{{{
    bd:serviceParam wikibase:language "en" .
  }}}}
}}}}
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
