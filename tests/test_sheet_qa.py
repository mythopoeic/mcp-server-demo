"""Seam 1 tests — `sheet_qa` prompt function.

Per the PRD's testing decisions: assert external behavior of the prompt
function. The returned string must compose the reader explainer with the
sheetQA task template, with both placeholders substituted.
"""

import pytest

from sheet_compressor import prompts

from sheet_compressor_mcp.tools import sheet_qa


SAMPLE_ENCODING = "A1,Order ID|B1,Qty\nA2,O-1|B2,3"
SAMPLE_QUESTION = "How many units does order O-1 have?"


def test_sheet_qa_default_includes_anchor_reader_and_filled_task():
    out = sheet_qa(SAMPLE_ENCODING, SAMPLE_QUESTION)

    # Anchor reader explainer is present (a distinctive phrase from it).
    assert "anchor-skeleton" in out
    # Encoding text is substituted in.
    assert SAMPLE_ENCODING in out
    # Question is substituted in.
    assert SAMPLE_QUESTION in out
    # No unfilled placeholders remain.
    assert "{ENCODING}" not in out
    assert "{QUESTION}" not in out


def test_sheet_qa_reader_precedes_task():
    out = sheet_qa(SAMPLE_ENCODING, SAMPLE_QUESTION)
    reader_marker = prompts.readers.anchor[:60]
    task_marker = "Answer the question below"
    assert reader_marker in out
    assert task_marker in out
    assert out.index(reader_marker) < out.index(task_marker)


def test_sheet_qa_supports_inverted_index_reader():
    out = sheet_qa(SAMPLE_ENCODING, SAMPLE_QUESTION, encoding="invertedIndex")
    assert prompts.readers.invertedIndex[:60] in out
    # Make sure we did NOT compose the anchor reader.
    assert "anchor-skeleton" not in out


def test_sheet_qa_supports_format_aggregation_reader():
    out = sheet_qa(SAMPLE_ENCODING, SAMPLE_QUESTION, encoding="formatAggregation")
    assert prompts.readers.formatAggregation[:60] in out


def test_sheet_qa_rejects_unknown_encoding():
    with pytest.raises(ValueError):
        sheet_qa(SAMPLE_ENCODING, SAMPLE_QUESTION, encoding="not-a-real-encoding")


def test_sheet_qa_preserves_braces_in_user_inputs():
    # If a user's question contains literal braces (e.g. a code snippet),
    # those must survive into the output verbatim — no double-substitution.
    tricky_question = "What does {x} mean in cell B7?"
    tricky_encoding = "A1,{ENCODING}|B1,value"  # try to confuse the substitutor
    out = sheet_qa(tricky_encoding, tricky_question)
    assert tricky_question in out
    assert tricky_encoding in out
