"""Tests for the pipeline.segmentation module."""

from unstructured_mapping.pipeline.segmentation import (
    DocumentSegmenter,
    DocumentType,
    FilingSegmenter,
    NewsSegmenter,
    ResearchSegmenter,
    TranscriptSegmenter,
)


# -- DocumentType -----------------------------------------------


def test_document_type_enum_values():
    assert DocumentType.NEWS.value == "news"
    assert DocumentType.RESEARCH.value == "research"
    assert DocumentType.TRANSCRIPT.value == "transcript"
    assert DocumentType.FILING.value == "filing"


# -- NewsSegmenter ----------------------------------------------


def test_news_segmenter_emits_single_chunk():
    seg = NewsSegmenter()
    chunks = seg.segment("doc1", "A one-paragraph article.")
    assert len(chunks) == 1
    assert chunks[0].document_id == "doc1"
    assert chunks[0].chunk_index == 0
    assert chunks[0].text == "A one-paragraph article."
    assert chunks[0].section_name is None


def test_news_segmenter_empty_text_returns_empty_list():
    assert NewsSegmenter().segment("doc1", "") == []
    assert NewsSegmenter().segment("doc1", "   \n") == []


def test_news_segmenter_preserves_multiline_body():
    text = "Lead paragraph.\n\nSecond paragraph."
    chunks = NewsSegmenter().segment("doc1", text)
    assert len(chunks) == 1
    assert chunks[0].text == text


# -- ResearchSegmenter ------------------------------------------


def test_research_segmenter_splits_on_atx_headings():
    text = (
        "Cover page preamble.\n\n"
        "## Executive Summary\n"
        "The thesis.\n\n"
        "## Valuation\n"
        "DCF and comps.\n\n"
        "## Risks\n"
        "Supplier concentration, regulatory."
    )
    chunks = ResearchSegmenter().segment("r1", text)
    assert [c.section_name for c in chunks] == [
        "Executive Summary",
        "Valuation",
        "Risks",
    ]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert "DCF and comps." in chunks[1].text


def test_research_segmenter_splits_on_setext_headings():
    text = (
        "Valuation\n"
        "=========\n"
        "Body A.\n\n"
        "Risks\n"
        "-----\n"
        "Body B."
    )
    chunks = ResearchSegmenter().segment("r1", text)
    assert [c.section_name for c in chunks] == [
        "Valuation",
        "Risks",
    ]


def test_research_segmenter_no_headings_single_chunk():
    text = "Just body text with no headings at all."
    chunks = ResearchSegmenter().segment("r1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name is None
    assert chunks[0].text == text


def test_research_segmenter_drops_preamble_before_first_heading():
    text = (
        "Report cover boilerplate.\n\n"
        "## Body\n"
        "Real content."
    )
    chunks = ResearchSegmenter().segment("r1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name == "Body"
    assert "cover boilerplate" not in chunks[0].text


def test_research_segmenter_skips_empty_sections():
    text = (
        "## Executive Summary\n"
        "\n"
        "## Valuation\n"
        "Real content."
    )
    chunks = ResearchSegmenter().segment("r1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name == "Valuation"


# -- TranscriptSegmenter ----------------------------------------


def test_transcript_segmenter_splits_on_speaker_turns():
    text = (
        "Operator: Welcome to the Q3 2026 earnings call.\n"
        "Tim Cook - CEO: Thank you. Revenue hit $95B.\n"
        "Luca Maestri - CFO: Margins expanded 200bps."
    )
    chunks = TranscriptSegmenter().segment("t1", text)
    names = [c.section_name for c in chunks]
    assert names == [
        "Operator",
        "Tim Cook - CEO",
        "Luca Maestri - CFO",
    ]
    assert "Revenue hit $95B." in chunks[1].text


def test_transcript_segmenter_emits_qa_divider_chunk():
    text = (
        "Tim Cook - CEO: Prepared remarks.\n"
        "Q&A\n"
        "Analyst: Question about iPhone.\n"
        "Tim Cook - CEO: Answer."
    )
    chunks = TranscriptSegmenter().segment("t1", text)
    names = [c.section_name for c in chunks]
    assert names == [
        "Tim Cook - CEO",
        "Q&A",
        "Analyst",
        "Tim Cook - CEO",
    ]
    qa = next(c for c in chunks if c.section_name == "Q&A")
    assert qa.text == ""


def test_transcript_segmenter_falls_back_to_one_chunk_without_speakers():
    text = "Just narrative text with no speaker labels."
    chunks = TranscriptSegmenter().segment("t1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name is None
    assert chunks[0].text == text


def test_transcript_segmenter_captures_multiline_turn_body():
    text = (
        "Tim Cook - CEO: First line.\n"
        "Continuation of the same turn.\n"
        "Luca Maestri - CFO: New turn."
    )
    chunks = TranscriptSegmenter().segment("t1", text)
    assert len(chunks) == 2
    assert (
        "Continuation of the same turn."
        in chunks[0].text
    )


# -- FilingSegmenter --------------------------------------------


def test_filing_segmenter_splits_on_item_headings():
    text = (
        "Cover page.\n\n"
        "Item 1. Business\n"
        "We design phones.\n\n"
        "Item 1A. Risk Factors\n"
        "Supplier concentration risk.\n\n"
        "Item 7. Management's Discussion\n"
        "Margins expanded."
    )
    chunks = FilingSegmenter().segment("f1", text)
    names = [c.section_name for c in chunks]
    assert names == [
        "Item 1. Business",
        "Item 1A. Risk Factors",
        "Item 7. Management's Discussion",
    ]
    risks = next(
        c for c in chunks if "Risk" in c.section_name
    )
    assert "Supplier concentration risk." in risks.text


def test_filing_segmenter_normalises_item_suffix_casing():
    text = "item 7b. Quantitative Disclosures\nBody."
    chunks = FilingSegmenter().segment("f1", text)
    assert chunks[0].section_name == (
        "Item 7B. Quantitative Disclosures"
    )


def test_filing_segmenter_no_items_single_chunk():
    text = "A generic business document without Items."
    chunks = FilingSegmenter().segment("f1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name is None


def test_filing_segmenter_ignores_item_inside_long_line():
    # "refer to Item 1A. Risk Factors" is prose, not a
    # heading — long lines are never treated as headings.
    prose = (
        "Operator: " + "x " * 150 + "refer to Item 1A. "
        "Risk Factors in the attached filing."
    )
    text = (
        "Item 1. Business\n"
        "Body.\n"
        + prose
        + "\n"
        "Item 2. Properties\nBody 2."
    )
    chunks = FilingSegmenter().segment("f1", text)
    assert len(chunks) == 2
    assert chunks[0].section_name == "Item 1. Business"
    assert chunks[1].section_name == "Item 2. Properties"


def test_filing_segmenter_drops_preamble():
    text = (
        "Registration Statement\n"
        "Cover information.\n\n"
        "Item 1. Business\nBody."
    )
    chunks = FilingSegmenter().segment("f1", text)
    assert len(chunks) == 1
    assert chunks[0].section_name == "Item 1. Business"
    assert "Cover information." not in chunks[0].text


# -- ABC --------------------------------------------------------


def test_abstract_segmenter_rejects_instantiation():
    import pytest

    with pytest.raises(TypeError):
        DocumentSegmenter()  # type: ignore[abstract]
