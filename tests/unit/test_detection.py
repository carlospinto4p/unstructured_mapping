"""Tests for pipeline entity detection."""

import pytest

from unstructured_mapping.knowledge_graph.models import (
    Entity,
    EntityType,
)
from unstructured_mapping.pipeline.models import (
    Chunk,
    Mention,
)
from unstructured_mapping.pipeline.detection import (
    RuleBasedDetector,
    _build_trie,
    _is_word_boundary,
    _scan_trie,
)


# -- Helpers --


def make_entity(
    name: str,
    aliases: tuple[str, ...] = (),
    entity_id: str = "",
) -> Entity:
    """Create a minimal entity for detection tests."""
    return Entity(
        canonical_name=name,
        entity_type=EntityType.ORGANIZATION,
        description=f"Test entity {name}",
        aliases=aliases,
        entity_id=entity_id or name.lower().replace(
            " ", "_"
        ),
    )


def make_chunk(
    text: str,
    doc_id: str = "doc1",
) -> Chunk:
    """Create a minimal chunk for testing."""
    return Chunk(
        document_id=doc_id,
        chunk_index=0,
        text=text,
    )


# -- Chunk model tests --


def test_chunk_defaults():
    c = Chunk(
        document_id="d1", chunk_index=0, text="hello"
    )
    assert c.section_name is None
    assert c.token_estimate == 0


def test_chunk_frozen():
    c = make_chunk("text")
    with pytest.raises(AttributeError):
        c.text = "other"  # type: ignore[misc]


# -- Mention model tests --


def test_mention_defaults():
    m = Mention(
        surface_form="Fed", span_start=0, span_end=3
    )
    assert m.candidate_ids == ()


def test_mention_with_candidates():
    m = Mention(
        surface_form="Apple",
        span_start=10,
        span_end=15,
        candidate_ids=("id1", "id2"),
    )
    assert len(m.candidate_ids) == 2


def test_mention_frozen():
    m = Mention(
        surface_form="x", span_start=0, span_end=1
    )
    with pytest.raises(AttributeError):
        m.span_start = 5  # type: ignore[misc]


# -- Word boundary tests --


def test_boundary_at_start():
    assert _is_word_boundary("hello", 0)


def test_boundary_at_end():
    assert _is_word_boundary("hello", 5)


def test_boundary_space_before():
    assert _is_word_boundary("a b", 2)


def test_no_boundary_inside_word():
    assert not _is_word_boundary("hello", 2)


def test_boundary_punctuation():
    assert _is_word_boundary("a.b", 1)


# -- Trie / scan tests --


def test_build_trie_empty():
    root = _build_trie({})
    assert root.children == {}


def test_scan_single_alias():
    root = _build_trie({"apple": {"id1"}})
    mentions = _scan_trie(root, "I bought Apple stock")
    assert len(mentions) == 1
    assert mentions[0].surface_form == "Apple"
    assert mentions[0].span_start == 9
    assert mentions[0].span_end == 14
    assert mentions[0].candidate_ids == ("id1",)


def test_scan_case_insensitive():
    root = _build_trie({"fed": {"id1"}})
    mentions = _scan_trie(root, "The FED raised rates")
    assert len(mentions) == 1
    assert mentions[0].surface_form == "FED"


def test_scan_preserves_original_case():
    root = _build_trie({"apple inc.": {"id1"}})
    text = "Shares of APPLE INC. rose"
    mentions = _scan_trie(root, text)
    assert len(mentions) == 1
    assert mentions[0].surface_form == "APPLE INC."


def test_scan_word_boundary_prevents_partial():
    root = _build_trie({"app": {"id1"}})
    mentions = _scan_trie(root, "The application crashed")
    assert len(mentions) == 0


def test_scan_word_boundary_allows_punctuation():
    root = _build_trie({"fed": {"id1"}})
    mentions = _scan_trie(root, "The Fed, raising rates")
    assert len(mentions) == 1
    assert mentions[0].surface_form == "Fed"


def test_scan_multiple_aliases_same_entity():
    root = _build_trie({
        "federal reserve": {"id1"},
        "the fed": {"id1"},
    })
    text = "The Fed is the Federal Reserve"
    mentions = _scan_trie(root, text)
    assert len(mentions) == 2
    forms = {m.surface_form for m in mentions}
    assert "The Fed" in forms or "the Fed" in forms
    assert "Federal Reserve" in forms


def test_scan_overlapping_aliases():
    root = _build_trie({
        "apple": {"id1", "id2"},
    })
    mentions = _scan_trie(root, "Buy Apple now")
    assert len(mentions) == 1
    assert set(mentions[0].candidate_ids) == {
        "id1", "id2"
    }


def test_scan_multiple_occurrences():
    root = _build_trie({"oil": {"id1"}})
    text = "Oil prices and oil demand"
    mentions = _scan_trie(root, text)
    assert len(mentions) == 2
    assert mentions[0].span_start < mentions[1].span_start


def test_scan_empty_text():
    root = _build_trie({"fed": {"id1"}})
    mentions = _scan_trie(root, "")
    assert mentions == []


def test_scan_no_matches():
    root = _build_trie({"fed": {"id1"}})
    mentions = _scan_trie(root, "The weather is nice")
    assert mentions == []


def test_scan_adjacent_mentions():
    root = _build_trie({
        "new": {"id1"},
        "york": {"id2"},
    })
    text = "In New York today"
    mentions = _scan_trie(root, text)
    assert len(mentions) == 2


def test_scan_sorted_by_span_start():
    root = _build_trie({
        "beta": {"id2"},
        "alpha": {"id1"},
    })
    text = "beta and alpha"
    mentions = _scan_trie(root, text)
    assert mentions[0].surface_form == "beta"
    assert mentions[1].surface_form == "alpha"


def test_scan_nested_aliases_longer_first():
    """At the same start position, longer match first."""
    root = _build_trie({
        "new york": {"id1"},
        "new": {"id2"},
    })
    text = "In New York today"
    mentions = _scan_trie(root, text)
    # Both match at position 3; longer one first
    ny = [m for m in mentions if "York" in m.surface_form]
    n = [m for m in mentions if m.surface_form == "New"]
    assert len(ny) == 1
    assert len(n) == 1
    # Same start → longer first (negative span_end sort)
    ny_idx = mentions.index(ny[0])
    n_idx = mentions.index(n[0])
    assert ny_idx < n_idx


# -- RuleBasedDetector tests --


def test_detector_from_entities():
    entities = [
        make_entity("Apple Inc.", aliases=("Apple", "AAPL")),
        make_entity("Microsoft", aliases=("MSFT",)),
    ]
    detector = RuleBasedDetector(entities)
    # canonical + aliases: 3 + 2 = 5 unique
    assert detector.alias_count == 5


def test_detector_detect_basic():
    entities = [
        make_entity(
            "Federal Reserve",
            aliases=("the Fed", "Fed"),
            entity_id="fed1",
        ),
    ]
    detector = RuleBasedDetector(entities)
    chunk = make_chunk(
        "The Fed raised rates on Wednesday."
    )
    mentions = detector.detect(chunk)
    assert len(mentions) >= 1
    fed_mentions = [
        m for m in mentions if "Fed" in m.surface_form
    ]
    assert len(fed_mentions) >= 1
    assert "fed1" in fed_mentions[0].candidate_ids


def test_detector_detect_multiple_entities():
    entities = [
        make_entity("Apple Inc.", aliases=("Apple",),
                entity_id="apple"),
        make_entity("Google", aliases=("Alphabet",),
                entity_id="goog"),
    ]
    detector = RuleBasedDetector(entities)
    chunk = make_chunk("Apple and Google announced a deal.")
    mentions = detector.detect(chunk)
    ids = {
        cid
        for m in mentions
        for cid in m.candidate_ids
    }
    assert "apple" in ids
    assert "goog" in ids


def test_detector_detect_empty_chunk():
    entities = [make_entity("Test")]
    detector = RuleBasedDetector(entities)
    assert detector.detect(make_chunk("")) == ()


def test_detector_detect_no_entities():
    detector = RuleBasedDetector([])
    assert detector.alias_count == 0
    assert detector.detect(make_chunk("Some text")) == ()


def test_detector_duplicate_aliases_across_entities():
    """Same alias on two entities produces both IDs."""
    e1 = make_entity(
        "Apple Inc.", aliases=("Apple",),
        entity_id="corp",
    )
    e2 = Entity(
        canonical_name="Apple",
        entity_type=EntityType.ASSET,
        description="AAPL stock",
        entity_id="stock",
    )
    detector = RuleBasedDetector([e1, e2])
    chunk = make_chunk("Buy Apple now")
    mentions = detector.detect(chunk)
    apple = [
        m for m in mentions
        if m.surface_form == "Apple"
    ]
    assert len(apple) == 1
    assert set(apple[0].candidate_ids) == {
        "corp", "stock"
    }


def test_detector_returns_tuple():
    entities = [make_entity("Test", entity_id="t1")]
    detector = RuleBasedDetector(entities)
    result = detector.detect(make_chunk("Test run"))
    assert isinstance(result, tuple)


def test_detector_ignores_empty_alias():
    """Empty string alias should not be indexed."""
    e = Entity(
        canonical_name="Valid",
        entity_type=EntityType.ORGANIZATION,
        description="test",
        aliases=("", "alias"),
        entity_id="v1",
    )
    detector = RuleBasedDetector([e])
    # "valid" + "alias" = 2 (empty skipped)
    assert detector.alias_count == 2


def test_detector_multiword_alias():
    entities = [
        make_entity(
            "Bank of England",
            aliases=("BoE",),
            entity_id="boe",
        ),
    ]
    detector = RuleBasedDetector(entities)
    chunk = make_chunk(
        "The Bank of England held rates steady."
    )
    mentions = detector.detect(chunk)
    boe = [
        m for m in mentions
        if "Bank of England" in m.surface_form
    ]
    assert len(boe) == 1
    assert boe[0].candidate_ids == ("boe",)
