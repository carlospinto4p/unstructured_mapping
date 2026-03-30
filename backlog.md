## Backlog

### 2026 March 30th

#### Web scraping — unstructured corpus

- [ ] Create `web_scraping` module with base scraper interface
- [ ] Implement Reuters scraper (first source)
- [ ] Implement AP News scraper
- [ ] Implement BBC News scraper

#### Knowledge graph — entity store

- [ ] Define KG data model:
    - Unique identifiers for entities
    - Entity types (person, org, location, event, concept, ...)
    - Descriptions and hints
    - Temporal dimension: datetime range the entity existed / was valid (point-in-time KG)
    - Relationships (graph structure)
    - Provenance: source/origin of the entity, traces to all texts where it appears
    - Embeddings per entity (for similarity / resolution)
- [ ] Build Wikipedia/Wikidata seed pipeline to populate the KG
- [ ] Design storage layer for the KG (graph DB or equivalent)
