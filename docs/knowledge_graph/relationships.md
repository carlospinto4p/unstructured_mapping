# Knowledge Graph — Relationship Patterns

## Purpose

The relationship model uses free-form `relation_type` strings
because the space of possible relationships in news is
unbounded. This document defines **canonical patterns** so that
LLM prompts, manual curation, and queries use consistent
terminology.

These are conventions, not enforced values. The `relation_type`
string is LLM-generated and kept as-is; the `relation_kind_id`
FK provides canonical grouping when synonyms need to resolve
to the same kind (see `design.md`).


## Notation

Patterns are written as:

```
SOURCE_TYPE/subtype → relation_type → TARGET_TYPE/subtype
```

Where `(qualified by ROLE)` indicates the `qualifier_id` FK
is set. Subtypes are shown when they narrow the pattern;
omitted when any subtype applies.


## Market structure

| Pattern | Example |
|---------|---------|
| `ASSET/equity → issued_by → ORGANIZATION/company` | AAPL → issued_by → Apple Inc. |
| `ASSET/bond → issued_by → ORGANIZATION/government` | US 10-Year Treasury → issued_by → US Treasury |
| `ASSET/etf → tracks → ASSET/index` | SPY → tracks → S&P 500 |
| `ORGANIZATION/company → listed_on → ORGANIZATION/exchange` | Apple Inc. → listed_on → Nasdaq |
| `ORGANIZATION/fund → managed_by → ORGANIZATION/fund_manager` | PIMCO Total Return → managed_by → PIMCO |
| `ASSET/etf → managed_by → ORGANIZATION/fund_manager` | iShares Core S&P 500 → managed_by → BlackRock |
| `ASSET/derivative → derived_from → ASSET` | ES futures → derived_from → S&P 500 |


## People and roles

These use `qualifier_id` pointing to a ROLE entity.

| Pattern | Example |
|---------|---------|
| `PERSON/executive → works_at → ORGANIZATION/company` (qualified by ROLE) | Tim Cook → works_at → Apple Inc. (CEO) |
| `PERSON/policymaker → works_at → ORGANIZATION/central_bank` (qualified by ROLE) | Jerome Powell → works_at → Federal Reserve (Chair) |
| `PERSON/politician → leads → ORGANIZATION/government` (qualified by ROLE) | Joe Biden → leads → US Government (President) |
| `PERSON/analyst → employed_by → ORGANIZATION/fund_manager` | Analyst X → employed_by → Goldman Sachs |
| `PERSON/investor → founded → ORGANIZATION/fund_manager` | Warren Buffett → founded → Berkshire Hathaway |


## Analyst coverage

Analyst initiations, upgrades, and downgrades are major
catalysts for individual stocks.

| Pattern | Example |
|---------|---------|
| `PERSON/analyst → covers → ASSET/equity` | Jane Smith → covers → AAPL |
| `PERSON/analyst → covers → ORGANIZATION/company` | Mike Chen → covers → Tesla Inc. |
| `ORGANIZATION/rating_agency → covers → ORGANIZATION/company` | Moody's → covers → Ford Motor |

Use temporal bounds for coverage initiation and
termination. Rating actions (upgrades, downgrades) are
modeled in the Credit ratings section with the `rating`
RELATION_KIND — analyst coverage here refers to the
ongoing coverage relationship, not individual actions.


## Products

Products appear as standalone entities in news (launches,
recalls, regulatory approvals, groundings). These patterns
link products to their manufacturers and regulators.

| Pattern | Example |
|---------|---------|
| `PRODUCT → manufactured_by → ORGANIZATION/company` | iPhone → manufactured_by → Apple Inc. |
| `PRODUCT → manufactured_by → ORGANIZATION/company` | Ozempic → manufactured_by → Novo Nordisk |
| `ORGANIZATION/regulator → approved → PRODUCT/pharma` | FDA → approved → Ozempic (valid_from=2017-12-05) |
| `ORGANIZATION/regulator → grounded → PRODUCT/hardware` | FAA → grounded → Boeing 737 MAX (valid_from=2019-03-13, valid_until=2020-11-18) |
| `PRODUCT → competes_with → PRODUCT` | ChatGPT → competes_with → Gemini |
| `PRODUCT → runs_on → PRODUCT/hardware` | iOS → runs_on → iPhone |

Use temporal bounds for regulatory actions (approvals,
bans, recalls). The `product` RELATION_KIND normalizes
`manufactured_by`, `produced_by`, and `made_by` to the
same canonical kind.


## Sector events

TOPIC/sector_event entities represent recurring events
that cluster articles and drive volatility windows.

| Pattern | Example |
|---------|---------|
| `TOPIC/sector_event → triggers → METRIC` | Fed meeting → triggers → federal funds rate |
| `TOPIC/sector_event → affects → TOPIC/sector` | Tech earnings season → affects → Technology |
| `TOPIC/sector_event → affects → ASSET` | OPEC+ meeting → affects → WTI crude oil |
| `ORGANIZATION → hosts → TOPIC/sector_event` | Federal Reserve → hosts → Fed meeting |


## Regulation and policy

| Pattern | Example |
|---------|---------|
| `ORGANIZATION/regulator → regulates → ORGANIZATION/company` | SEC → regulates → Coinbase |
| `ORGANIZATION/regulator → enforces → LEGISLATION/regulation` | SEC → enforces → Dodd-Frank Act |
| `ORGANIZATION/central_bank → sets → METRIC/monetary_policy` | Federal Reserve → sets → federal funds rate |
| `LEGISLATION/sanction → targets → ORGANIZATION/company` | Russia sanctions → targets → Gazprom |
| `LEGISLATION/sanction → targets → PLACE/country` | Russia sanctions → targets → Russia |
| `LEGISLATION → sponsored_by → ORGANIZATION/government` | Dodd-Frank Act → sponsored_by → US Congress |
| `LEGISLATION → applies_to → PLACE/country` | GDPR → applies_to → European Union |


## Economic indicators

| Pattern | Example |
|---------|---------|
| `METRIC → issued_by → ORGANIZATION` | CPI → issued_by → Bureau of Labor Statistics |
| `METRIC → measures → PLACE/country` | US GDP → measures → United States |
| `METRIC/monetary_policy → set_by → ORGANIZATION/central_bank` | ECB deposit rate → set_by → ECB |


## Corporate actions and events

Events are modeled as relationships with temporal bounds
(`valid_from`, `valid_until`), not as separate entity types.

| Pattern | Example |
|---------|---------|
| `ORGANIZATION/company → acquired → ORGANIZATION/company` | Microsoft → acquired → Activision Blizzard (valid_from=2023-10-13) |
| `ORGANIZATION/company → merged_with → ORGANIZATION/company` | T-Mobile → merged_with → Sprint |
| `ORGANIZATION/company → spun_off → ORGANIZATION/company` | GE → spun_off → GE Vernova |
| `PERSON/executive → appointed_at → ORGANIZATION/company` (qualified by ROLE) | New CEO → appointed_at → Company (CEO, valid_from=2024-01-15) |
| `PERSON/executive → departed_from → ORGANIZATION/company` (qualified by ROLE) | Old CEO → departed_from → Company (CEO, valid_until=2024-01-14) |
| `ORGANIZATION/company → ipo_on → ORGANIZATION/exchange` | ARM Holdings → ipo_on → Nasdaq (valid_from=2023-09-14) |


## Credit ratings

Rating actions are major market-moving events. The agency is
the source; the rated entity is the target.

| Pattern | Example |
|---------|---------|
| `ORGANIZATION/rating_agency → rated → ORGANIZATION/company` | S&P → rated → Apple Inc. |
| `ORGANIZATION/rating_agency → rated → PLACE/country` | Moody's → rated → France |
| `ORGANIZATION/rating_agency → upgraded → ORGANIZATION/company` | Fitch → upgraded → Ford Motor (valid_from=2024-06-01) |
| `ORGANIZATION/rating_agency → downgraded → PLACE/country` | S&P → downgraded → United States (valid_from=2011-08-05) |
| `ORGANIZATION/rating_agency → affirmed → ASSET/bond` | Moody's → affirmed → US 10-Year Treasury |

Use temporal bounds to capture when a rating action occurred.
The KG does not store the actual rating value (AAA, Baa1) —
that is quantitative data belonging in external tables.


## Competitive and supply chain

| Pattern | Example |
|---------|---------|
| `ORGANIZATION/company → competes_with → ORGANIZATION/company` | Nvidia → competes_with → AMD |
| `ORGANIZATION/company → supplies → ORGANIZATION/company` | TSMC → supplies → Apple Inc. |
| `ORGANIZATION/company → partners_with → ORGANIZATION/company` | Microsoft → partners_with → OpenAI |
| `ORGANIZATION/company → invests_in → ORGANIZATION/company` | SoftBank → invests_in → ARM Holdings |

The KG tracks *that* an ownership or investment relationship
exists, not the percentage or stake size — those belong in
external tables joined via `entity_id`. For example, "BlackRock
owns a stake in Apple" is in scope; "BlackRock owns 7.2% of
Apple" stores the 7.2% externally.


## Corporate structure

Holding company and subsidiary relationships are critical
for earnings consolidation, regulatory exposure, and
understanding which brands belong to which parent.

| Pattern | Example |
|---------|---------|
| `ORGANIZATION/company → subsidiary_of → ORGANIZATION/company` | Google → subsidiary_of → Alphabet |
| `ORGANIZATION/company → parent_of → ORGANIZATION/company` | Berkshire Hathaway → parent_of → GEICO |

Use temporal bounds when ownership changes (e.g. an
acquisition creates a new subsidiary_of relationship with
`valid_from`). For `spun_off` and `merged_with`, see
Corporate actions and events above.


## Location

Geographic links drive regulatory jurisdiction analysis
and geopolitical exposure filtering.

| Pattern | Example |
|---------|---------|
| `ORGANIZATION/company → headquartered_in → PLACE/country` | Apple Inc. → headquartered_in → United States |
| `ORGANIZATION/company → headquartered_in → PLACE/market` | HSBC → headquartered_in → City of London |
| `ORGANIZATION/exchange → located_in → PLACE/country` | NYSE → located_in → United States |


## Membership

Bloc and cartel membership drives coordinated policy
actions, commodity supply decisions, and macro analysis.

| Pattern | Example |
|---------|---------|
| `ORGANIZATION/company → member_of → ORGANIZATION/multilateral` | Saudi Aramco → member_of → OPEC |
| `PLACE/country → member_of → PLACE/economic_zone` | Germany → member_of → Eurozone |
| `PLACE/country → member_of → ORGANIZATION/multilateral` | Japan → member_of → G7 |


## Sector and topic linkage

| Pattern | Example |
|---------|---------|
| `ORGANIZATION/company → classified_as → TOPIC/sector` | Apple Inc. → classified_as → Technology |
| `ASSET/equity → belongs_to → TOPIC/sector` | AAPL → belongs_to → Technology |
| `TOPIC/macro_theme → affects → ASSET` | Inflation → affects → Gold |
| `TOPIC/geopolitical → affects → ASSET/commodity` | Middle East tensions → affects → WTI crude oil |


## Using RELATION_KIND for normalization

Many patterns have synonymous `relation_type` strings. For
example, "works_at", "employed_by", and "serves_as" all
describe employment. Create a RELATION_KIND entity with
aliases and link via `relation_kind_id`:

```
Entity(canonical_name="employment",
       entity_type=RELATION_KIND,
       aliases=("works_at", "employed_by", "serves_as"))
```

This enables querying "all employment relationships"
regardless of the surface form the LLM generated.

Recommended RELATION_KIND entities for financial analysis:

| Kind           | Aliases                                          |
|----------------|--------------------------------------------------|
| employment     | works_at, employed_by, serves_as                 |
| ownership      | owns, holds_stake_in, acquired                   |
| regulation     | regulates, oversees, supervises                  |
| issuance       | issued_by, published_by, released_by             |
| competition    | competes_with, rivals                            |
| supply         | supplies, provides_to, vendor_of                 |
| investment     | invests_in, funds, backs                         |
| sanction       | targets, sanctioned, restricted                  |
| appointment    | appointed_at, named_to, elected_to               |
| departure      | departed_from, resigned_from, fired_from         |
| rating         | rated, upgraded, downgraded, affirmed             |
| corporate_structure | subsidiary_of, parent_of, controlled_by,    |
|                     | spun_off, merged_with, founded               |
| location       | headquartered_in, located_in, based_in            |
| membership     | member_of, joined                                  |
| governance     | leads, governs                                     |
| market_structure | listed_on, ipo_on, managed_by, tracks,            |
|                  | derived_from                                       |
| policy         | enforces, sets, set_by, sponsored_by, applies_to  |
| classification | classified_as, belongs_to, measures*,              |
|                | categorized_as                                     |
| causality      | affects                                              |
| partnership    | partners_with, collaborates_with, allied_with      |
| analyst_coverage | covers, initiates_coverage, drops_coverage        |
| product        | manufactured_by, produced_by, made_by,               |
|                | approved, grounded, recalled                         |
| event_trigger  | triggers, hosts, schedules                          |

\* `measures` is a semantic stretch — `METRIC → measures →
PLACE` describes geographic scope, not classification — but
creating a dedicated kind for a single alias adds overhead
without practical benefit.
