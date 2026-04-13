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
"""

from dataclasses import dataclass

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


# -- Companies --------------------------------------------------


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
        parts.append(
            f"listed on {exchange} under ticker {ticker}"
        )
    elif exchange:
        parts.append(f"listed on {exchange}")
    elif ticker:
        parts.append(f"trading under ticker {ticker}")
    return ", ".join(parts) + "."


def map_company_row(row: dict) -> MappedEntity | None:
    """Convert a listed-company SPARQL row to an Entity."""
    item = _extract_item(row)
    if item is None:
        return None
    qid, label = item

    country = _value(row, "countryLabel")
    exchange = _value(row, "exchangeLabel")
    ticker = _value(row, "ticker")
    isin = _value(row, "isin")

    description = _append_description(
        _company_description(label, country, exchange, ticker),
        _value(row, "description"),
    )

    extras: list[str] = []
    if ticker:
        extras.append(f"ticker:{ticker}")
    if isin:
        extras.append(f"isin:{isin}")

    return _make_mapped(
        qid,
        label,
        EntityType.ORGANIZATION,
        "company",
        description,
        extras,
    )


# -- Central banks ---------------------------------------------


def map_central_bank_row(row: dict) -> MappedEntity | None:
    """Convert a central-bank SPARQL row to an Entity."""
    item = _extract_item(row)
    if item is None:
        return None
    qid, label = item
    country = _value(row, "countryLabel")

    if country:
        description = (
            f"{label} is the central bank of {country}. "
            "Sets monetary policy and influences the "
            "country's currency."
        )
    else:
        description = f"{label} is a central bank."
    description = _append_description(
        description, _value(row, "description")
    )

    return _make_mapped(
        qid,
        label,
        EntityType.ORGANIZATION,
        "central_bank",
        description,
    )


# -- Regulators ------------------------------------------------


def map_regulator_row(row: dict) -> MappedEntity | None:
    """Convert a financial-regulator SPARQL row to an Entity."""
    item = _extract_item(row)
    if item is None:
        return None
    qid, label = item
    country = _value(row, "countryLabel")

    if country:
        description = (
            f"{label} is a financial regulatory authority "
            f"in {country}."
        )
    else:
        description = (
            f"{label} is a financial regulatory authority."
        )
    description = _append_description(
        description, _value(row, "description")
    )

    return _make_mapped(
        qid,
        label,
        EntityType.ORGANIZATION,
        "regulator",
        description,
    )


# -- Exchanges -------------------------------------------------


def map_exchange_row(row: dict) -> MappedEntity | None:
    """Convert a stock-exchange SPARQL row to an Entity."""
    item = _extract_item(row)
    if item is None:
        return None
    qid, label = item
    country = _value(row, "countryLabel")
    mic = _value(row, "mic")

    if country:
        description = (
            f"{label} is a stock exchange based in "
            f"{country}."
        )
    else:
        description = f"{label} is a stock exchange."
    description = _append_description(
        description, _value(row, "description")
    )

    extras: list[str] = []
    if mic:
        extras.append(f"mic:{mic}")

    return _make_mapped(
        qid,
        label,
        EntityType.ORGANIZATION,
        "exchange",
        description,
        extras,
    )


# -- Currencies (ASSET/currency) --------------------------------


def map_currency_row(row: dict) -> MappedEntity | None:
    """Convert a fiat-currency SPARQL row to an Entity."""
    item = _extract_item(row)
    if item is None:
        return None
    qid, label = item
    iso = _value(row, "iso")
    country = _value(row, "countryLabel")

    parts = [f"{label} is a fiat currency"]
    if iso:
        parts.append(f"with ISO 4217 code {iso}")
    if country:
        parts.append(f"issued by {country}")
    description = _append_description(
        ", ".join(parts) + ".",
        _value(row, "description"),
    )

    extras: list[str] = []
    if iso:
        extras.append(f"iso:{iso}")

    return _make_mapped(
        qid,
        label,
        EntityType.ASSET,
        "currency",
        description,
        extras,
    )


# -- Indices (ASSET/index) --------------------------------------


def map_index_row(row: dict) -> MappedEntity | None:
    """Convert a stock-market-index SPARQL row to an Entity."""
    item = _extract_item(row)
    if item is None:
        return None
    qid, label = item
    exchange = _value(row, "exchangeLabel")
    country = _value(row, "countryLabel")

    parts = [f"{label} is a stock market index"]
    if exchange:
        parts.append(f"tracked on {exchange}")
    if country:
        parts.append(f"in {country}")
    description = _append_description(
        ", ".join(parts) + ".",
        _value(row, "description"),
    )

    return _make_mapped(
        qid, label, EntityType.ASSET, "index", description
    )


# -- Crypto (ASSET/crypto) --------------------------------------


def map_crypto_row(row: dict) -> MappedEntity | None:
    """Convert a cryptocurrency SPARQL row to an Entity."""
    item = _extract_item(row)
    if item is None:
        return None
    qid, label = item
    symbol = _value(row, "symbol")

    if symbol:
        description = (
            f"{label} is a cryptocurrency trading under "
            f"symbol {symbol}."
        )
    else:
        description = f"{label} is a cryptocurrency."
    description = _append_description(
        description, _value(row, "description")
    )

    extras: list[str] = []
    if symbol:
        extras.append(f"symbol:{symbol}")

    return _make_mapped(
        qid,
        label,
        EntityType.ASSET,
        "crypto",
        description,
        extras,
    )
