-- =========================================================
-- Query cookbook for the unstructured-mapping KG.
--
-- These are labelled, self-contained queries for analysts
-- exploring a populated KG. Each block has a comment
-- explaining the question the query answers; copy a block
-- into ``sqlite3 data/knowledge.db`` or any SQLite client
-- and tweak the placeholders (``:param`` or dates) as
-- needed.
--
-- Schema reference:
--   entities(entity_id, canonical_name, entity_type,
--            subtype, description, valid_from,
--            valid_until, status, merged_into,
--            created_at, updated_at)
--   entity_aliases(entity_id, alias)
--   provenance(entity_id, document_id, source,
--              mention_text, context_snippet,
--              detected_at, run_id)
--   relationships(source_id, target_id, relation_type,
--                 description, qualifier_id,
--                 relation_kind_id, valid_from,
--                 valid_until, document_id,
--                 discovered_at, run_id, confidence)
--   entity_history / relationship_history — audit trail.
--   ingestion_runs / run_metrics — per-run telemetry.
-- =========================================================


-- ---------------------------------------------------------
-- 1. Most-mentioned entities this week.
--
-- Ranks entities by distinct articles they were mentioned
-- in during the last seven days. Use this to sanity-check
-- which entities the pipeline is actively picking up.
-- ---------------------------------------------------------
SELECT
    e.canonical_name,
    e.entity_type,
    COUNT(DISTINCT p.document_id) AS article_count,
    COUNT(*)                      AS mention_count
FROM entities e
JOIN provenance p
    ON p.entity_id = e.entity_id
WHERE p.detected_at >= datetime('now', '-7 days')
  AND e.status = 'active'
GROUP BY e.entity_id
ORDER BY article_count DESC, mention_count DESC
LIMIT 20;


-- ---------------------------------------------------------
-- 2. Most-mentioned entities of a given type.
--
-- Swap ``'organization'`` for any ``EntityType`` value
-- (person, place, topic, product, legislation, asset,
-- metric, role, relation_kind) to slice by type.
-- ---------------------------------------------------------
SELECT
    e.canonical_name,
    e.subtype,
    COUNT(*) AS mention_count
FROM entities e
JOIN provenance p
    ON p.entity_id = e.entity_id
WHERE e.entity_type = 'organization'
  AND e.status = 'active'
GROUP BY e.entity_id
ORDER BY mention_count DESC
LIMIT 25;


-- ---------------------------------------------------------
-- 3. Entity merge history.
--
-- Shows the audit trail for merges on a single entity.
-- ``merge`` rows come in pairs — one for the deprecated
-- side and one for the surviving side — so you can trace
-- which IDs were absorbed into a canonical entity.
-- Substitute the desired ``entity_id``.
-- ---------------------------------------------------------
SELECT
    h.changed_at,
    h.operation,
    h.canonical_name,
    h.status,
    h.merged_into,
    h.reason
FROM entity_history h
WHERE h.entity_id = :entity_id
  AND h.operation IN ('merge', 'deprecate')
ORDER BY h.history_id;


-- ---------------------------------------------------------
-- 4. Relationships by relation_type.
--
-- Group relationships by their free-form label so you can
-- see the long tail of how the LLM labels edges. Useful
-- when deciding which `relation_type` strings deserve a
-- canonical ``relation_kind`` entity.
-- ---------------------------------------------------------
SELECT
    r.relation_type,
    COUNT(*) AS edge_count,
    AVG(r.confidence) AS avg_confidence
FROM relationships r
GROUP BY r.relation_type
ORDER BY edge_count DESC;


-- ---------------------------------------------------------
-- 5. High-confidence relationships (currently active).
--
-- Returns relationships that are in force today with
-- ``confidence >= 0.8``. Swap the placeholder threshold
-- or date to time-travel.
-- ---------------------------------------------------------
SELECT
    s.canonical_name AS source,
    r.relation_type,
    t.canonical_name AS target,
    r.confidence,
    r.valid_from,
    r.valid_until,
    r.document_id
FROM relationships r
JOIN entities s ON s.entity_id = r.source_id
JOIN entities t ON t.entity_id = r.target_id
WHERE r.confidence IS NOT NULL
  AND r.confidence >= 0.8
  AND (r.valid_from = '' OR r.valid_from IS NULL
       OR r.valid_from <= datetime('now'))
  AND (r.valid_until IS NULL
       OR r.valid_until >= datetime('now'))
ORDER BY r.confidence DESC;


-- ---------------------------------------------------------
-- 6. Provenance timeline for a single entity.
--
-- Chronological list of every mention of ``:entity_id``
-- with its source and snippet. Great for "when did this
-- story break?" / "what's new since last week?" queries.
-- ---------------------------------------------------------
SELECT
    p.detected_at,
    p.source,
    p.document_id,
    p.mention_text,
    p.context_snippet
FROM provenance p
WHERE p.entity_id = :entity_id
ORDER BY p.detected_at;


-- ---------------------------------------------------------
-- 7. Co-mentioned entities within the same article.
--
-- Counts how often each entity co-appears with
-- ``:entity_id`` in a single article's provenance.
-- Useful for "who travels with this topic?" analyses.
-- ---------------------------------------------------------
SELECT
    co.canonical_name,
    co.entity_type,
    COUNT(DISTINCT p1.document_id) AS co_articles
FROM provenance p1
JOIN provenance p2
    ON p1.document_id = p2.document_id
    AND p1.entity_id  != p2.entity_id
JOIN entities co
    ON co.entity_id = p2.entity_id
WHERE p1.entity_id = :entity_id
GROUP BY co.entity_id
ORDER BY co_articles DESC
LIMIT 20;


-- ---------------------------------------------------------
-- 8. Per-run scorecard summary.
--
-- Latest 20 ingestion runs with their quality counters
-- and token spend. Helpful when bisecting a regression
-- in resolver recall or tracking LLM cost.
-- ---------------------------------------------------------
SELECT
    r.run_id,
    r.started_at,
    r.status,
    m.chunks_processed,
    m.mentions_detected,
    m.mentions_resolved_alias,
    m.mentions_resolved_llm,
    m.proposals_saved,
    m.relationships_saved,
    m.input_tokens,
    m.output_tokens,
    m.wall_clock_seconds,
    m.provider_name,
    m.model_name
FROM ingestion_runs r
LEFT JOIN run_metrics m ON m.run_id = r.run_id
ORDER BY r.started_at DESC
LIMIT 20;


-- ---------------------------------------------------------
-- 9. Aliases shared across multiple entities (collisions).
--
-- Case-insensitive alias collision report. This mirrors
-- what ``cli/audit_aliases.py`` surfaces, but directly at
-- the SQL level so you can filter by entity type or
-- prefix.
-- ---------------------------------------------------------
SELECT
    a.alias,
    COUNT(DISTINCT a.entity_id) AS collision_size,
    GROUP_CONCAT(
        e.canonical_name || ' [' || e.entity_type || ']',
        ' | '
    ) AS entities
FROM entity_aliases a
JOIN entities e ON e.entity_id = a.entity_id
GROUP BY a.alias COLLATE NOCASE
HAVING collision_size > 1
ORDER BY collision_size DESC, a.alias;


-- ---------------------------------------------------------
-- 10. Entities proposed by a specific run.
--
-- Joins ``provenance.run_id`` against ``entities`` to
-- list every new entity a given run introduced. Useful
-- for spot-checking cold-start or prompt changes.
-- ---------------------------------------------------------
SELECT
    e.canonical_name,
    e.entity_type,
    e.subtype,
    p.document_id,
    p.mention_text
FROM provenance p
JOIN entities e ON e.entity_id = p.entity_id
WHERE p.run_id = :run_id
ORDER BY e.canonical_name;
