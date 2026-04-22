"""Map Wikidata SPARQL rows to knowledge-graph entities.

Mappers take a single SPARQL binding row (a ``dict`` of
``varname -> {"type": ..., "value": ...}``) and return a
:class:`MappedEntity` pairing a ready-to-persist
:class:`Entity` with the source Wikidata QID.

The QID is returned separately rather than buried in the
aliases so the seed loader can dedup against prior imports
cheaply. It is *also* included in the entity aliases with a
``wikidata:`` prefix so the information survives even when
the KG is queried without the loader's help.

External-identifier alias convention
------------------------------------

External IDs are encoded as prefixed aliases until the
dedicated ``external_ids`` table lands (see the backlog):

- ``wikidata:Q312`` — the Wikidata QID (always present)
- ``ticker:AAPL`` — stock-exchange tickers
- ``isin:US0378331005`` — ISINs
- ``mic:XNAS`` — Market Identifier Codes for exchanges
- ``iso:USD`` — ISO 4217 currency codes
- ``symbol:BTC`` — crypto tickers / symbols

Plain human-readable aliases (e.g. ``"Apple"``, ``"The Fed"``)
remain unprefixed so entity detection in free text continues
to work unchanged.

Descriptions
------------

Phase 1 uses template descriptions built from the structured
Wikidata fields. This is deliberately thin — the intent is
to give the LLM enough context to disambiguate, not to
produce a polished profile. A later phase will optionally
enrich descriptions through an LLM call.

Factory shape
-------------

Every ``map_*_row`` function is produced by
:func:`_make_row_mapper`: the factory centralises the
shared boilerplate (``_extract_item``, wikidata-description
append, ``_make_mapped``) so each type only declares its
entity-type/subtype pair and a ``build`` function that
turns the raw row into ``(description, extra_aliases)``.
Adding a new type is therefore a registry entry, not a
copy-pasted function body.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace

from unstructured_mapping.knowledge_graph import (
    Entity,
    EntityType,
)


@dataclass(frozen=True, slots=True)
class MappedEntity:
    """A Wikidata row converted into an Entity.

    :param qid: The Wikidata QID (e.g. ``"Q312"``). Used
        by the seed loader to dedup against prior imports
        before falling back to name-based matching.
    :param entity: The ready-to-persist :class:`Entity`.
        Its ``aliases`` tuple already includes the
        ``wikidata:`` prefixed QID alongside any other
        external IDs extracted from the source row.
    """

    qid: str
    entity: Entity


def dedupe_mapped_by_qid(
    mapped: list[MappedEntity],
) -> list[MappedEntity]:
    """Collapse multiple :class:`MappedEntity` rows sharing a QID.

    Wikidata OPTIONAL joins fan out each item into several
    bindings whenever the joined fields (ticker, exchange,
    country, ISIN, MIC, etc.) carry more than one value. The
    v0.35.2 ``SELECT DISTINCT ?item`` LIMIT idiom dedupes QIDs
    inside the subquery, but the OPTIONALs outside re-expand
    them — we saw "Stoxx Europe 600 Index" × 289 of 601 and
    "euro" × 27 in the raw mapped output.

    This post-mapping step keeps the first mapper result per
    QID (description, ``entity_type``, ``subtype`` are
    first-seen-wins) and unions its aliases with every later
    duplicate's aliases, preserving first-seen order. Every
    ticker / ISIN / MIC surfaced by any binding therefore
    survives on a single entity.

    :param mapped: Possibly-duplicated list from the raw
        SPARQL → mapper pass.
    :return: One :class:`MappedEntity` per unique QID, in
        first-seen order.
    """
    first: dict[str, MappedEntity] = {}
    merged_aliases: dict[str, list[str]] = {}
    for m in mapped:
        if m.qid not in first:
            first[m.qid] = m
            merged_aliases[m.qid] = list(m.entity.aliases)
            continue
        existing = merged_aliases[m.qid]
        seen = set(existing)
        for alias in m.entity.aliases:
            if alias not in seen:
                existing.append(alias)
                seen.add(alias)
    result: list[MappedEntity] = []
    for qid, m in first.items():
        aliases = tuple(merged_aliases[qid])
        entity = (
            m.entity
            if aliases == m.entity.aliases
            else replace(m.entity, aliases=aliases)
        )
        result.append(MappedEntity(qid=qid, entity=entity))
    return result


#: Signature of a type-specific builder: receives the
#: resolved label and the raw SPARQL row, returns the
#: structured-fields template description plus the list
#: of external-id aliases (e.g. ``["ticker:AAPL"]``).
#: The factory appends the Wikidata ``description`` field
#: and the ``wikidata:Qxxx`` alias so builders don't need
#: to repeat that boilerplate.
_RowBuilder = Callable[[str, dict], tuple[str, list[str]]]


# -- Shared helpers --------------------------------------------


def _value(row: dict, key: str) -> str | None:
    """Return the ``value`` field of a binding or None."""
    binding = row.get(key)
    if not binding:
        return None
    value = binding.get("value")
    if not value:
        return None
    return str(value)


def _qid_from_uri(uri: str) -> str:
    """Extract the Q-identifier from a Wikidata URI.

    :param uri: A URI such as
        ``http://www.wikidata.org/entity/Q312``.
    :return: The trailing QID (``"Q312"``).
    """
    return uri.rsplit("/", 1)[-1]


def _extract_item(row: dict) -> tuple[str, str] | None:
    """Pull ``(qid, label)`` from a row, or ``None``.

    Returns ``None`` when the row lacks either field, or
    when the label equals the bare QID — Wikidata's
    fallback when no English label exists, and a strong
    signal that the row carries no value for an
    English-language news KG.
    """
    uri = _value(row, "item")
    label = _value(row, "itemLabel")
    if not uri or not label:
        return None
    qid = _qid_from_uri(uri)
    if label == qid:
        return None
    return qid, label


def _append_description(base: str, extra: str | None) -> str:
    """Append the Wikidata description to a template one."""
    if not extra:
        return base
    return f"{base} {extra}"


def _make_mapped(
    qid: str,
    label: str,
    entity_type: EntityType,
    subtype: str,
    description: str,
    extra_aliases: list[str] | None = None,
) -> MappedEntity:
    """Build a :class:`MappedEntity` with prefixed aliases."""
    aliases = [f"wikidata:{qid}"]
    if extra_aliases:
        aliases.extend(extra_aliases)
    return MappedEntity(
        qid=qid,
        entity=Entity(
            canonical_name=label,
            entity_type=entity_type,
            subtype=subtype,
            description=description,
            aliases=tuple(aliases),
        ),
    )


def _make_row_mapper(
    entity_type: EntityType,
    subtype: str,
    build: _RowBuilder,
) -> Callable[[dict], MappedEntity | None]:
    """Return a row mapper for ``(entity_type, subtype)``.

    The returned callable runs the shared row-handling
    boilerplate and delegates description + extra-alias
    construction to ``build``. Declaring a new type is a
    single factory invocation plus a small builder — the
    boilerplate lives here, not in each mapper.

    :param entity_type: The :class:`EntityType` every row
        mapped by this function will carry.
    :param subtype: The KG subtype string (``"company"``,
        ``"central_bank"`` etc.).
    :param build: Receives ``(label, row)`` and returns
        ``(template_description, extra_aliases)``. The
        factory appends the Wikidata ``description`` field
        and the ``wikidata:Qxxx`` alias.
    """

    def mapper(row: dict) -> MappedEntity | None:
        item = _extract_item(row)
        if item is None:
            return None
        qid, label = item
        description, extras = build(label, row)
        description = _append_description(
            description, _value(row, "description")
        )
        return _make_mapped(
            qid,
            label,
            entity_type,
            subtype,
            description,
            extras,
        )

    return mapper


# -- Type-specific builders ------------------------------------


def _company_description(
    name: str,
    country: str | None,
    exchange: str | None,
    ticker: str | None,
) -> str:
    """Build a template description for a listed company."""
    parts = [f"{name} is a publicly listed company"]
    if country:
        parts.append(f"headquartered in {country}")
    if exchange and ticker:
        parts.append(f"listed on {exchange} under ticker {ticker}")
    elif exchange:
        parts.append(f"listed on {exchange}")
    elif ticker:
        parts.append(f"trading under ticker {ticker}")
    return ", ".join(parts) + "."


def _build_company(label: str, row: dict) -> tuple[str, list[str]]:
    country = _value(row, "countryLabel")
    exchange = _value(row, "exchangeLabel")
    ticker = _value(row, "ticker")
    isin = _value(row, "isin")
    description = _company_description(label, country, exchange, ticker)
    extras: list[str] = []
    if ticker:
        extras.append(f"ticker:{ticker}")
    if isin:
        extras.append(f"isin:{isin}")
    return description, extras


def _build_central_bank(label: str, row: dict) -> tuple[str, list[str]]:
    country = _value(row, "countryLabel")
    if country:
        description = (
            f"{label} is the central bank of {country}. "
            "Sets monetary policy and influences the "
            "country's currency."
        )
    else:
        description = f"{label} is a central bank."
    return description, []


def _build_regulator(label: str, row: dict) -> tuple[str, list[str]]:
    country = _value(row, "countryLabel")
    if country:
        description = (
            f"{label} is a financial regulatory authority in {country}."
        )
    else:
        description = f"{label} is a financial regulatory authority."
    return description, []


def _build_exchange(label: str, row: dict) -> tuple[str, list[str]]:
    country = _value(row, "countryLabel")
    mic = _value(row, "mic")
    if country:
        description = f"{label} is a stock exchange based in {country}."
    else:
        description = f"{label} is a stock exchange."
    extras: list[str] = []
    if mic:
        extras.append(f"mic:{mic}")
    return description, extras


def _build_currency(label: str, row: dict) -> tuple[str, list[str]]:
    iso = _value(row, "iso")
    country = _value(row, "countryLabel")
    parts = [f"{label} is a fiat currency"]
    if iso:
        parts.append(f"with ISO 4217 code {iso}")
    if country:
        parts.append(f"issued by {country}")
    description = ", ".join(parts) + "."
    extras: list[str] = []
    if iso:
        extras.append(f"iso:{iso}")
    return description, extras


def _build_index(label: str, row: dict) -> tuple[str, list[str]]:
    exchange = _value(row, "exchangeLabel")
    country = _value(row, "countryLabel")
    parts = [f"{label} is a stock market index"]
    if exchange:
        parts.append(f"tracked on {exchange}")
    if country:
        parts.append(f"in {country}")
    description = ", ".join(parts) + "."
    return description, []


def _build_crypto(label: str, row: dict) -> tuple[str, list[str]]:
    symbol = _value(row, "symbol")
    if symbol:
        description = (
            f"{label} is a cryptocurrency trading under symbol {symbol}."
        )
    else:
        description = f"{label} is a cryptocurrency."
    extras: list[str] = []
    if symbol:
        extras.append(f"symbol:{symbol}")
    return description, extras


# -- Public row mappers ----------------------------------------
#
# Each mapper is a factory call. The public names are
# preserved so existing imports (tests, CLI registry) are
# unaffected. Order mirrors the SPARQL template layout in
# ``queries.py``.

map_company_row = _make_row_mapper(
    EntityType.ORGANIZATION, "company", _build_company
)
map_central_bank_row = _make_row_mapper(
    EntityType.ORGANIZATION,
    "central_bank",
    _build_central_bank,
)
map_regulator_row = _make_row_mapper(
    EntityType.ORGANIZATION, "regulator", _build_regulator
)
map_exchange_row = _make_row_mapper(
    EntityType.ORGANIZATION, "exchange", _build_exchange
)
map_currency_row = _make_row_mapper(
    EntityType.ASSET, "currency", _build_currency
)
map_index_row = _make_row_mapper(EntityType.ASSET, "index", _build_index)
map_crypto_row = _make_row_mapper(EntityType.ASSET, "crypto", _build_crypto)
