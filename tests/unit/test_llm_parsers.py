"""Tests for pipeline.llm_parsers — LLM response parsing."""

import json

import pytest

from unstructured_mapping.knowledge_graph import EntityType
from unstructured_mapping.pipeline.llm_parsers import (
    Pass1ValidationError,
    Pass2ValidationError,
    parse_pass1_response,
    parse_pass2_response,
)
from unstructured_mapping.pipeline.models import (
    EntityProposal,
    ResolvedMention,
)


# -- Helpers -------------------------------------------------


CANDIDATE_IDS = {"a1b2c3d4", "e5f6g7h8"}


def make_resolved_entry(
    entity_id="a1b2c3d4",
    surface_form="the Fed",
    context_snippet="...the Fed raised rates...",
):
    return {
        "surface_form": surface_form,
        "entity_id": entity_id,
        "new_entity": None,
        "context_snippet": context_snippet,
    }


def make_new_entry(
    surface_form="Jerome Powell",
    canonical_name="Jerome Powell",
    entity_type="person",
    subtype="policymaker",
    description="Chair of the Federal Reserve.",
    aliases=None,
    context_snippet="...Fed Chair Powell announced...",
):
    if aliases is None:
        aliases = ["Powell", "Fed Chair Powell"]
    return {
        "surface_form": surface_form,
        "entity_id": None,
        "new_entity": {
            "canonical_name": canonical_name,
            "entity_type": entity_type,
            "subtype": subtype,
            "description": description,
            "aliases": aliases,
        },
        "context_snippet": context_snippet,
    }


def wrap_entities(entities):
    return json.dumps({"entities": entities})


# -- EntityProposal model -----------------------------------


def test_entity_proposal_fields():
    ep = EntityProposal(
        canonical_name="Test",
        entity_type=EntityType.PERSON,
        description="A test.",
        subtype="analyst",
        aliases=("T",),
        source_chunk=2,
        context_snippet="...Test...",
    )

    assert ep.canonical_name == "Test"
    assert ep.entity_type == EntityType.PERSON
    assert ep.description == "A test."
    assert ep.subtype == "analyst"
    assert ep.aliases == ("T",)
    assert ep.source_chunk == 2
    assert ep.context_snippet == "...Test..."


def test_entity_proposal_defaults():
    ep = EntityProposal(
        canonical_name="X",
        entity_type=EntityType.TOPIC,
        description="Desc.",
    )

    assert ep.subtype is None
    assert ep.aliases == ()
    assert ep.source_chunk == 0
    assert ep.context_snippet == ""


def test_entity_proposal_frozen():
    ep = EntityProposal(
        canonical_name="X",
        entity_type=EntityType.TOPIC,
        description="Desc.",
    )

    with pytest.raises(AttributeError):
        ep.canonical_name = "Y"


# -- Valid responses -----------------------------------------


def test_parse_empty_entities():
    resolved, proposals = parse_pass1_response(
        '{"entities": []}', CANDIDATE_IDS
    )

    assert resolved == ()
    assert proposals == ()


def test_parse_resolved_entity():
    raw = wrap_entities([make_resolved_entry()])
    resolved, proposals = parse_pass1_response(raw, CANDIDATE_IDS)

    assert len(resolved) == 1
    assert isinstance(resolved[0], ResolvedMention)
    assert resolved[0].entity_id == "a1b2c3d4"
    assert resolved[0].surface_form == "the Fed"
    assert proposals == ()


def test_parse_new_entity():
    raw = wrap_entities([make_new_entry()])
    resolved, proposals = parse_pass1_response(raw, CANDIDATE_IDS)

    assert resolved == ()
    assert len(proposals) == 1
    assert isinstance(proposals[0], EntityProposal)
    assert proposals[0].canonical_name == "Jerome Powell"
    assert proposals[0].entity_type == EntityType.PERSON
    assert proposals[0].subtype == "policymaker"
    assert proposals[0].description == ("Chair of the Federal Reserve.")
    assert "Powell" in proposals[0].aliases


def test_parse_mixed_response():
    raw = wrap_entities([make_resolved_entry(), make_new_entry()])
    resolved, proposals = parse_pass1_response(raw, CANDIDATE_IDS)

    assert len(resolved) == 1
    assert len(proposals) == 1


def test_parse_new_entity_type_case_insensitive():
    entry = make_new_entry(entity_type="PERSON")
    raw = wrap_entities([entry])
    _, proposals = parse_pass1_response(raw, CANDIDATE_IDS)

    assert proposals[0].entity_type == EntityType.PERSON


def test_parse_new_entity_no_subtype():
    entry = make_new_entry(subtype=None)
    entry["new_entity"]["subtype"] = None
    raw = wrap_entities([entry])
    _, proposals = parse_pass1_response(raw, CANDIDATE_IDS)

    assert proposals[0].subtype is None


def test_parse_chunk_index_propagated():
    raw = wrap_entities([make_new_entry()])
    _, proposals = parse_pass1_response(raw, CANDIDATE_IDS, chunk_index=3)

    assert proposals[0].source_chunk == 3


def test_parse_context_snippet_on_proposal():
    raw = wrap_entities(
        [make_new_entry(context_snippet="...surrounding text...")]
    )
    _, proposals = parse_pass1_response(raw, CANDIDATE_IDS)

    assert proposals[0].context_snippet == ("...surrounding text...")


def test_parse_multiple_resolved():
    entries = [
        make_resolved_entry(entity_id="a1b2c3d4"),
        make_resolved_entry(
            entity_id="e5f6g7h8",
            surface_form="Powell",
        ),
    ]
    raw = wrap_entities(entries)
    resolved, _ = parse_pass1_response(raw, CANDIDATE_IDS)

    assert len(resolved) == 2


def test_parse_filters_empty_aliases():
    entry = make_new_entry(aliases=["Good", "", "Fine"])
    raw = wrap_entities([entry])
    _, proposals = parse_pass1_response(raw, CANDIDATE_IDS)

    assert proposals[0].aliases == ("Good", "Fine")


# -- Rule 1: entities must be an array -------------------


def test_rule1_missing_entities_key():
    with pytest.raises(Pass1ValidationError, match="Missing"):
        parse_pass1_response("{}", CANDIDATE_IDS)


def test_rule1_entities_not_array():
    with pytest.raises(Pass1ValidationError, match="must be an array"):
        parse_pass1_response(
            '{"entities": "not an array"}',
            CANDIDATE_IDS,
        )


def test_rule1_invalid_json():
    with pytest.raises(Pass1ValidationError, match="Invalid JSON"):
        parse_pass1_response("not json at all", CANDIDATE_IDS)


def test_rule1_not_a_json_object():
    with pytest.raises(Pass1ValidationError, match="Expected a JSON object"):
        parse_pass1_response("[1, 2, 3]", CANDIDATE_IDS)


def test_rule1_entity_not_a_dict():
    raw = json.dumps({"entities": ["not a dict"]})
    with pytest.raises(Pass1ValidationError, match="expected an object"):
        parse_pass1_response(raw, CANDIDATE_IDS)


# -- Rule 2: required fields ----------------------------


def test_rule2_missing_surface_form():
    entry = make_resolved_entry()
    del entry["surface_form"]
    with pytest.raises(Pass1ValidationError, match="surface_form"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


def test_rule2_missing_context_snippet():
    entry = make_resolved_entry()
    del entry["context_snippet"]
    with pytest.raises(Pass1ValidationError, match="context_snippet"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


def test_rule2_empty_surface_form():
    entry = make_resolved_entry(surface_form="")
    with pytest.raises(Pass1ValidationError, match="surface_form"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


# -- Rule 3: exactly one of entity_id / new_entity ------


def test_rule3_both_present():
    entry = make_resolved_entry()
    entry["new_entity"] = {
        "canonical_name": "X",
        "entity_type": "person",
        "description": "Y",
        "aliases": [],
    }
    with pytest.raises(Pass1ValidationError, match="got both"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


def test_rule3_neither_present():
    entry = {
        "surface_form": "test",
        "entity_id": None,
        "new_entity": None,
        "context_snippet": "...test...",
    }
    with pytest.raises(Pass1ValidationError, match="got neither"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


def test_rule3_empty_entity_id_and_no_new():
    entry = {
        "surface_form": "test",
        "entity_id": "",
        "new_entity": None,
        "context_snippet": "...test...",
    }
    with pytest.raises(Pass1ValidationError, match="got neither"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


# -- Rule 4: valid EntityType ---------------------------


def test_rule4_invalid_entity_type():
    entry = make_new_entry(entity_type="dinosaur")
    with pytest.raises(Pass1ValidationError, match="not a valid entity type"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


def test_rule4_missing_canonical_name():
    entry = make_new_entry()
    del entry["new_entity"]["canonical_name"]
    with pytest.raises(Pass1ValidationError, match="canonical_name"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


def test_rule4_missing_description():
    entry = make_new_entry()
    del entry["new_entity"]["description"]
    with pytest.raises(Pass1ValidationError, match="description"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


def test_rule4_aliases_not_array():
    entry = make_new_entry()
    entry["new_entity"]["aliases"] = "not an array"
    with pytest.raises(
        Pass1ValidationError, match="aliases.*must be an array"
    ):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


# -- Rule 5: entity_id in candidate set -----------------


def test_rule5_hallucinated_id():
    entry = make_resolved_entry(entity_id="not_a_real_id")
    with pytest.raises(Pass1ValidationError, match="not in the candidate"):
        parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)


def test_rule5_valid_id_accepted():
    entry = make_resolved_entry(entity_id="a1b2c3d4")
    resolved, _ = parse_pass1_response(wrap_entities([entry]), CANDIDATE_IDS)

    assert resolved[0].entity_id == "a1b2c3d4"


def test_rule5_empty_candidate_set_rejects_any_id():
    entry = make_resolved_entry(entity_id="a1b2c3d4")
    with pytest.raises(Pass1ValidationError, match="not in the candidate"):
        parse_pass1_response(wrap_entities([entry]), set())


# ====================================================
# Pass 2 — Relationship extraction
# ====================================================

KNOWN_IDS_P2: set[str] = {"id-fed", "id-powell"}
NAME_TO_ID_P2: dict[str, str] = {
    "Federal Reserve": "id-fed",
    "Jerome Powell": "id-powell",
}


def _wrap_rels(rels: list[dict]) -> str:
    return json.dumps({"relationships": rels})


def _rel(
    source: str = "id-fed",
    target: str = "id-powell",
    relation_type: str = "appointed",
    snippet: str = "...appointed...",
    **kwargs: object,
) -> dict:
    d: dict = {
        "source": source,
        "target": target,
        "relation_type": relation_type,
        "context_snippet": snippet,
    }
    d.update(kwargs)
    return d


# -- Pass 2: happy path --


def test_p2_parse_empty_relationships():
    result = parse_pass2_response(_wrap_rels([]), KNOWN_IDS_P2, NAME_TO_ID_P2)
    assert result == ()


def test_p2_parse_resolved_by_id():
    result = parse_pass2_response(
        _wrap_rels([_rel()]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert len(result) == 1
    assert result[0].source_id == "id-fed"
    assert result[0].target_id == "id-powell"
    assert result[0].relation_type == "appointed"


def test_p2_parse_resolved_by_name():
    result = parse_pass2_response(
        _wrap_rels(
            [
                _rel(
                    source="Federal Reserve",
                    target="Jerome Powell",
                )
            ]
        ),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert len(result) == 1
    assert result[0].source_id == "id-fed"
    assert result[0].target_id == "id-powell"


def test_p2_parse_multiple():
    rels = [
        _rel(relation_type="appointed"),
        _rel(
            source="id-powell",
            target="id-fed",
            relation_type="chairs",
        ),
    ]
    result = parse_pass2_response(
        _wrap_rels(rels), KNOWN_IDS_P2, NAME_TO_ID_P2
    )
    assert len(result) == 2


# -- Pass 2: date parsing --


def test_p2_full_date():
    result = parse_pass2_response(
        _wrap_rels([_rel(valid_from="2024-03-20")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].valid_from is not None
    assert result[0].valid_from.year == 2024
    assert result[0].valid_from.month == 3
    assert result[0].valid_from.day == 20


def test_p2_partial_date_year_month():
    result = parse_pass2_response(
        _wrap_rels([_rel(valid_from="2024-03")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].valid_from is not None
    assert result[0].valid_from.year == 2024
    assert result[0].valid_from.month == 3


def test_p2_partial_date_year_only():
    result = parse_pass2_response(
        _wrap_rels([_rel(valid_from="2024")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].valid_from is not None
    assert result[0].valid_from.year == 2024


def test_p2_bad_date_becomes_none():
    result = parse_pass2_response(
        _wrap_rels([_rel(valid_from="not-a-date")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].valid_from is None


def test_p2_null_date_stays_none():
    result = parse_pass2_response(
        _wrap_rels([_rel(valid_from=None)]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].valid_from is None


# -- Pass 2: soft drops (rules 3, 5) --


def test_p2_unresolvable_source_dropped():
    result = parse_pass2_response(
        _wrap_rels([_rel(source="nonexistent")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert len(result) == 0


def test_p2_unresolvable_target_dropped():
    result = parse_pass2_response(
        _wrap_rels([_rel(target="nonexistent")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert len(result) == 0


def test_p2_self_ref_dropped():
    result = parse_pass2_response(
        _wrap_rels([_rel(source="id-fed", target="id-fed")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert len(result) == 0


def test_p2_self_ref_by_name_dropped():
    result = parse_pass2_response(
        _wrap_rels(
            [
                _rel(
                    source="id-fed",
                    target="Federal Reserve",
                )
            ]
        ),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert len(result) == 0


# -- Pass 2: structural errors (rules 1-2) --


def test_p2_rule1_missing_relationships_key():
    with pytest.raises(Pass2ValidationError, match="relationships"):
        parse_pass2_response(
            '{"entities": []}',
            KNOWN_IDS_P2,
            NAME_TO_ID_P2,
        )


def test_p2_rule1_relationships_not_array():
    with pytest.raises(Pass2ValidationError, match="array"):
        parse_pass2_response(
            '{"relationships": "nope"}',
            KNOWN_IDS_P2,
            NAME_TO_ID_P2,
        )


def test_p2_rule1_invalid_json():
    with pytest.raises(Pass2ValidationError, match="Invalid JSON"):
        parse_pass2_response("not json", KNOWN_IDS_P2, NAME_TO_ID_P2)


def test_p2_rule1_not_object():
    with pytest.raises(Pass2ValidationError, match="JSON object"):
        parse_pass2_response("[1, 2]", KNOWN_IDS_P2, NAME_TO_ID_P2)


def test_p2_rule2_missing_source():
    entry = _rel()
    del entry["source"]
    with pytest.raises(Pass2ValidationError, match="source"):
        parse_pass2_response(
            _wrap_rels([entry]),
            KNOWN_IDS_P2,
            NAME_TO_ID_P2,
        )


def test_p2_rule2_missing_target():
    entry = _rel()
    del entry["target"]
    with pytest.raises(Pass2ValidationError, match="target"):
        parse_pass2_response(
            _wrap_rels([entry]),
            KNOWN_IDS_P2,
            NAME_TO_ID_P2,
        )


def test_p2_rule2_missing_relation_type():
    entry = _rel()
    del entry["relation_type"]
    with pytest.raises(Pass2ValidationError, match="relation_type"):
        parse_pass2_response(
            _wrap_rels([entry]),
            KNOWN_IDS_P2,
            NAME_TO_ID_P2,
        )


def test_p2_rule2_missing_context_snippet():
    entry = _rel()
    del entry["context_snippet"]
    with pytest.raises(Pass2ValidationError, match="context_snippet"):
        parse_pass2_response(
            _wrap_rels([entry]),
            KNOWN_IDS_P2,
            NAME_TO_ID_P2,
        )


def test_p2_rule2_entry_not_object():
    with pytest.raises(Pass2ValidationError, match="expected an object"):
        parse_pass2_response(
            '{"relationships": ["not_an_object"]}',
            KNOWN_IDS_P2,
            NAME_TO_ID_P2,
        )


# -- Pass 2: qualifier --


def test_p2_qualifier_resolved():
    known = {"id-fed", "id-powell", "id-chair"}
    names = {
        **NAME_TO_ID_P2,
        "Chair": "id-chair",
    }
    result = parse_pass2_response(
        _wrap_rels([_rel(qualifier="id-chair")]),
        known,
        names,
    )
    assert result[0].qualifier_id == "id-chair"


def test_p2_qualifier_unresolvable_is_none():
    result = parse_pass2_response(
        _wrap_rels([_rel(qualifier="nonexistent")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].qualifier_id is None


def test_p2_qualifier_null_is_none():
    result = parse_pass2_response(
        _wrap_rels([_rel(qualifier=None)]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].qualifier_id is None


# -- Pass 2: confidence parsing --


def test_p2_confidence_in_range_kept():
    result = parse_pass2_response(
        _wrap_rels([_rel(confidence=0.8)]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].confidence == 0.8


def test_p2_confidence_missing_is_none():
    """Relationship without `confidence` → None."""
    result = parse_pass2_response(
        _wrap_rels([_rel()]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].confidence is None


def test_p2_confidence_out_of_range_is_clamped():
    over = parse_pass2_response(
        _wrap_rels([_rel(confidence=1.5)]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    under = parse_pass2_response(
        _wrap_rels([_rel(confidence=-0.2)]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert over[0].confidence == 1.0
    assert under[0].confidence == 0.0


def test_p2_confidence_non_numeric_is_none():
    """Strings or booleans → None so invalid LLM output
    does not contaminate the metric."""
    result = parse_pass2_response(
        _wrap_rels([_rel(confidence="very high")]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert result[0].confidence is None
    bool_result = parse_pass2_response(
        _wrap_rels([_rel(confidence=True)]),
        KNOWN_IDS_P2,
        NAME_TO_ID_P2,
    )
    assert bool_result[0].confidence is None
