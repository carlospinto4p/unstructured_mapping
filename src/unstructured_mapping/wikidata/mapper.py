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

- ``wikidata:Q312`` — the Wikidata QID
- ``ticker:AAPL`` — stock-exchange tickers
- ``isin:US0378331005`` — ISINs

Plain human-readable aliases (e.g. ``"Apple"``) remain
unprefixed so entity detection in free text continues to
work unchanged.

Descriptions
------------

Phase 1 uses template descriptions built from the structured
Wikidata fields (country, exchange, ticker). This is
deliberately thin — the intent is to give the LLM enough
context to disambiguate, not to produce a polished company
profile. A later phase will optionally enrich descriptions
through an LLM call.
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
        ``wikidata:`` prefixed QID alongside tickers,
        ISINs, and any human-readable labels.
    """

    qid: str
    entity: Entity


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


def _company_description(
    name: str,
    country: str | None,
    exchange: str | None,
    ticker: str | None,
) -> str:
    """Build a template description for a listed company.

    The description is intentionally short and factual.
    It exists to help the LLM disambiguate mentions — not
    to serve as a company profile.
    """
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
    """Convert a listed-company SPARQL row to an Entity.

    :param row: A binding dict from the
        ``LISTED_COMPANIES_QUERY`` result. Must contain
        ``item`` and ``itemLabel``; all other fields are
        optional.
    :return: A :class:`MappedEntity`, or ``None`` if the
        row is missing required fields or the label is
        just the bare QID (Wikidata's fallback when no
        English label exists — those rows carry no
        signal for English-language news).
    """
    item_uri = _value(row, "item")
    label = _value(row, "itemLabel")
    if not item_uri or not label:
        return None
    qid = _qid_from_uri(item_uri)
    if label == qid:
        return None

    country = _value(row, "countryLabel")
    exchange = _value(row, "exchangeLabel")
    ticker = _value(row, "ticker")
    isin = _value(row, "isin")
    wikidata_description = _value(row, "description")

    description = _company_description(
        label, country, exchange, ticker
    )
    if wikidata_description:
        description = (
            f"{description} {wikidata_description}"
        )

    aliases: list[str] = [f"wikidata:{qid}"]
    if ticker:
        aliases.append(f"ticker:{ticker}")
    if isin:
        aliases.append(f"isin:{isin}")

    entity = Entity(
        canonical_name=label,
        entity_type=EntityType.ORGANIZATION,
        subtype="company",
        description=description,
        aliases=tuple(aliases),
    )
    return MappedEntity(qid=qid, entity=entity)
