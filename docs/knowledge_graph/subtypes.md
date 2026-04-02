# Knowledge Graph — Subtype Conventions

## Purpose

The `subtype` field on `Entity` provides finer classification
within an entity type. It is a **free-form string** — not an
enum — to avoid combinatorial explosion. This document defines
the canonical values so that LLM ingestion, manual curation,
and queries all use consistent terminology.

Subtypes serve two roles:

1. **Structured filtering** — "show me all ASSET/commodity
   entities mentioned this week."
2. **LLM routing hints** — ORGANIZATION/central_bank +
   METRIC/monetary_policy signals a rate-decision story,
   not a corporate earnings story.


## When to set subtype

- Set it when the distinction **matters for queries or LLM
  routing**. An organization that is clearly a company should
  have `subtype="company"`.
- Leave it `None` when the classification is ambiguous or
  irrelevant. Not every entity needs a subtype.
- When in doubt, prefer setting it — it is easier to ignore a
  subtype than to backfill one later.


## Canonical subtypes by entity type


### ORGANIZATION

| Subtype        | Covers                                          | Examples                               |
|----------------|-------------------------------------------------|----------------------------------------|
| company        | For-profit corporations, both public and private | Apple Inc., JPMorgan Chase, SpaceX     |
| central_bank   | Monetary authorities that set interest rates     | Federal Reserve, ECB, Bank of Japan    |
| regulator      | Government agencies that oversee markets/sectors | SEC, FCA, CFTC, FDA                    |
| exchange       | Securities and commodities exchanges             | NYSE, Nasdaq, CME, LSE                 |
| fund           | Investment vehicles: hedge funds, ETFs, pension  | BlackRock, Bridgewater, Vanguard       |
| multilateral   | International organizations and treaty bodies    | IMF, World Bank, WTO, NATO             |
| government     | National or regional government bodies           | US Treasury, UK Parliament             |

#### Deferred: sub-classification of companies

Companies will eventually need further classification —
**public vs private** matters for market analysis (public
companies have tickers, earnings reports, regulatory filings).
Other useful distinctions include sector (tech, energy,
financial) and market cap tier (large-cap, mid-cap,
small-cap).

These are not implemented as nested subtypes. When the need
arises, the recommended approach is:

- Add optional **structured attributes** to Entity (e.g.
  `listing_status`, `sector`) rather than encoding them in
  the subtype string (no `"company.public"` dot notation).
- Alternatively, model these as **relationships**: Company
  → Exchange (listed_on), Company → Sector (classified_as).

This keeps `subtype` as a single flat token for fast filtering
while richer classification lives in purpose-built fields or
relationships.


### ASSET

| Subtype   | Covers                                            | Examples                               |
|-----------|---------------------------------------------------|----------------------------------------|
| equity    | Individual stocks and shares                      | AAPL, TSLA, NVDA                       |
| bond      | Fixed-income securities: government and corporate | US 10-Year Treasury, German Bund       |
| commodity | Physical goods traded on exchanges                | Gold, WTI crude oil, wheat, copper     |
| currency  | Fiat currencies and forex pairs                   | EUR/USD, USD/JPY, GBP                  |
| crypto    | Cryptocurrencies and digital assets               | Bitcoin, Ethereum, Solana              |
| index     | Market indices and benchmarks                     | S&P 500, Dow Jones, FTSE 100, VIX     |
| etf       | Exchange-traded funds — fund vehicles that trade   | SPY, QQQ, IWM, GLD, ARKK              |
|           | on exchanges like stocks but track an index,       |                                        |
|           | sector, or strategy. Distinct from equity (not an  |                                        |
|           | individual stock) and index (tradeable, not just   |                                        |
|           | a benchmark)                                       |                                        |
| derivative| Futures, options, swaps                           | ES futures, SPX options                |

#### Tickers and external identifiers

Tickers (e.g. "AAPL") are stored as **aliases**, not in a
dedicated field. This is intentional:

- A single `ticker` field would be too narrow — assets
  often have different tickers on different exchanges
  (`AAPL` on Nasdaq, `APC.F` on Frankfurt, `0R2V.L` on
  London).
- Non-ticker assets ("US 10-Year Treasury", "Gold") and
  rolling futures (`GCQ24`, `GCZ24`) don't fit a single
  ticker field.
- Aliases are sufficient for entity detection in text.

For structured joins with price feeds and external data,
the planned `external_ids` table (see post-population
backlog) will provide `(entity_id, id_scheme, external_id)`
tuples — e.g. `("ticker:nasdaq", "AAPL")`,
`("isin", "US0378331005")`, `("figi", "BBG000B9XRY4")`.
This handles multi-exchange tickers, ISINs, FIGIs, and
non-ticker instruments cleanly.


### METRIC

| Subtype         | Covers                                         | Examples                               |
|-----------------|-------------------------------------------------|----------------------------------------|
| inflation       | Price-level indicators                          | CPI, PPI, PCE deflator                |
| employment      | Labor market indicators                         | Unemployment rate, nonfarm payrolls, jobless claims |
| growth          | Economic output and activity                    | GDP, industrial production, PMI        |
| monetary_policy | Central bank rates and targets                  | Federal funds rate, ECB deposit rate   |
| sentiment       | Confidence and expectations surveys             | Consumer confidence, Michigan sentiment, VIX Index |
| trade           | International trade flows                       | Trade balance, current account deficit |
| housing         | Real estate and construction indicators         | Housing starts, Case-Shiller index     |
| earnings        | Company-level financial metrics reported in      | EPS, revenue, net income, operating    |
|                 | earnings releases and filings. The most          | margin, guidance, same-store sales     |
|                 | market-moving data for individual stocks         |                                        |

#### What the KG stores vs what it doesn't

The KG stores enough about a metric to **detect it in text
and link it to other entities**. It does not store operational
metadata:

- **Issuing body** — modeled as a relationship
  (`METRIC → issued_by → ORGANIZATION`), not a field.
  E.g. CPI → issued_by → Bureau of Labor Statistics.
- **Release schedule and frequency** — out of scope.
  The KG is an index into the news, not an economic
  calendar. Schedules belong in dedicated tables that
  can be joined via `entity_id` or the future
  `external_ids` table.
- **Expected vs actual values** — per-release data, not
  entity metadata. Belongs in a time-series store or
  ingestion layer, not the KG.

The `description` field should include enough context for
the LLM to recognize the metric in text (e.g. "Released
monthly by the BLS; measures average price changes for
urban consumers").


### PERSON

| Subtype      | Covers                                          | Examples                               |
|--------------|-------------------------------------------------|----------------------------------------|
| executive    | Corporate officers and board members             | Tim Cook, Jamie Dimon                  |
| policymaker  | Central bankers, finance ministers                | Jerome Powell, Christine Lagarde       |
| analyst      | Market analysts, economists, strategists         | Nouriel Roubini                        |
| politician   | Elected officials and government leaders         | Joe Biden, Ursula von der Leyen       |
| investor     | Notable investors and fund managers              | Warren Buffett, Cathie Wood            |


### LEGISLATION

| Subtype         | Covers                                         | Examples                               |
|-----------------|-------------------------------------------------|----------------------------------------|
| regulation      | Regulatory frameworks and rules                 | GDPR, Basel III, MiFID II              |
| tax_law         | Tax legislation and reform                      | Tax Cuts and Jobs Act, Pillar Two      |
| trade_agreement | Bilateral and multilateral trade deals          | USMCA, RCEP                            |
| sanction        | Economic sanctions and restrictions             | Russia sanctions, Iran sanctions       |
| monetary_act    | Laws governing central bank mandates            | Federal Reserve Act, ECB statute       |


### PLACE

| Subtype       | Covers                                          | Examples                               |
|---------------|-------------------------------------------------|----------------------------------------|
| country       | Sovereign nations                                | United States, China, Germany          |
| economic_zone | Trade blocs and monetary unions                  | Eurozone, ASEAN, BRICS                 |
| market        | Financial centers and exchange locations          | Wall Street, City of London, Shanghai  |
| region        | Sub-national regions with economic significance  | Silicon Valley, Shenzhen, Ruhr Valley  |


### PRODUCT

| Subtype    | Covers                                           | Examples                               |
|------------|--------------------------------------------------|----------------------------------------|
| hardware   | Physical technology products                     | iPhone, Boeing 737 MAX                 |
| software   | Software products and platforms                  | ChatGPT, Windows, Bloomberg Terminal   |
| pharma     | Pharmaceutical products                          | Ozempic, Humira                        |
| service    | Named commercial services                        | AWS, Google Cloud, Stripe              |


### TOPIC

| Subtype       | Covers                                           | Examples                                |
|---------------|--------------------------------------------------|-----------------------------------------|
| sector        | Industry sectors and verticals, mapping to       | Technology, energy, healthcare,         |
|               | standard classifications (GICS, ICB)             | financials, real estate                 |
| macro_theme   | Recurring macro-economic narratives that drive    | Inflation, recession fears, rate hikes, |
|               | market regimes and cross-asset movements         | trade war, debt ceiling, de-dollarization|
| geopolitical  | International tensions and geopolitical dynamics  | NATO expansion, South China Sea,        |
|               | that move commodities, defense stocks, and        | Russia-Ukraine, Middle East tensions    |
|               | safe-haven assets                                |                                         |
| sector_event  | Recurring sector-specific events that cluster     | Tech earnings season, bank stress tests,|
|               | articles and drive volatility windows             | OPEC+ meeting, Fed meeting              |

TOPIC subtypes are intentionally broad — "inflation" could
arguably be both a `macro_theme` and adjacent to METRIC. When
the classification is ambiguous, prefer the more specific type
(METRIC for "CPI", TOPIC/macro_theme for "inflation fears") or
leave subtype as `None`.


### ROLE and RELATION_KIND

No subtypes. These are meta-types used for structured querying
and synonym resolution. Their classification is inherently flat.


## Dual-nature entities

Some real-world things span multiple entity types. The KG
handles this by creating **separate entities for each role**,
linked by a relationship. This is not duplication — each
entity serves a different purpose in queries and analysis.

### Pattern

When something is both a measurable indicator and a tradeable
instrument (or a benchmark and a fund), create two entities:

| Indicator / benchmark entity | Tradeable entity | Relationship |
|------------------------------|-----------------|--------------|
| VIX Index (METRIC/sentiment) | VIX Futures (ASSET/derivative) | derived_from |
| S&P 500 (ASSET/index) | SPY (ASSET/etf) | tracks |
| Gold spot price (ASSET/commodity) | GLD (ASSET/etf) | tracks |
| Federal funds rate (METRIC/monetary_policy) | Fed funds futures (ASSET/derivative) | derived_from |
| US 10-Year yield (METRIC/monetary_policy) | TLT (ASSET/etf) | tracks |

### When to split vs keep as one entity

- **Split** when the two roles serve different query
  populations. A quant tracking volatility indicators
  queries METRIC; a trader managing a VIX futures position
  queries ASSET. Merging them forces every query to filter
  out the irrelevant role.
- **Keep as one** when the entity is unambiguously one type
  and the other role is incidental. "Gold" in news almost
  always means the commodity — create one ASSET/commodity
  entity. Only split if GLD or gold futures appear as
  distinct entities in your corpus.
- The `description` field on each entity should note the
  relationship: "VIX Index — CBOE volatility index measuring
  S&P 500 expected volatility. See also VIX Futures (ASSET)."


## Adding new subtypes

1. Add the value to the relevant table in this document.
2. Include a short description and examples.
3. No code changes needed — `subtype` is a free-form string.
4. Update LLM prompts that reference the canonical list.
