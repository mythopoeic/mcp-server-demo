"""Seam 1 tests — `compress_spreadsheet` tool function against real .xlsx files.

Per the PRD's testing decisions: assert external behavior of the tool function,
not the library's internals or MCP transport plumbing.
"""

from pathlib import Path

import pytest

from sheet_compressor_mcp.tools import compress_spreadsheet

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
HERO_XLSX = str(EXAMPLES / "northstar-auto-q3-2025.xlsx")
LEDGER_XLSX = str(EXAMPLES / "sample-orders.xlsx")


def test_compress_spreadsheet_hero_default_anchor_shape():
    result = compress_spreadsheet(HERO_XLSX)

    assert result["encoding"] == "anchor"
    assert isinstance(result["compressed"], str) and result["compressed"]
    assert isinstance(result["tokenEstimate"], int) and result["tokenEstimate"] > 0
    assert isinstance(result["rawBaselineTokens"], int) and result["rawBaselineTokens"] > 0
    assert result["savingsRatio"] is not None


def test_compress_spreadsheet_hero_anchor_preserves_a_known_value():
    # The hero file is the Northstar Auto Q3 2025 sheet — title text in A1
    # should survive into the anchor encoding (value-preserving per ADR-0002).
    result = compress_spreadsheet(HERO_XLSX, encoding="anchor")
    assert "Northstar Auto" in result["compressed"]


def test_compress_spreadsheet_accepts_all_three_encodings():
    for enc in ("anchor", "invertedIndex", "formatAggregation"):
        result = compress_spreadsheet(HERO_XLSX, encoding=enc)
        assert result["encoding"] == enc
        assert isinstance(result["compressed"], str)
        assert result["tokenEstimate"] > 0


def test_compress_spreadsheet_sheet_arg_selects_worksheet_by_name():
    # The hero workbook's sole sheet is named "Q3 Sales" — selecting it by
    # name must succeed and match the default-sheet result.
    default_result = compress_spreadsheet(HERO_XLSX)
    named_result = compress_spreadsheet(HERO_XLSX, sheet="Q3 Sales")
    assert named_result["compressed"] == default_result["compressed"]


def test_compress_spreadsheet_rejects_unknown_encoding():
    with pytest.raises((KeyError, ValueError)):
        compress_spreadsheet(HERO_XLSX, encoding="not-a-real-encoding")


def test_compress_spreadsheet_bundled_ledger_anchor():
    # The generic order ledger is the proven Resource sample; anchor must
    # preserve a known header so a reader can land on cell values.
    result = compress_spreadsheet(LEDGER_XLSX, encoding="anchor")
    assert result["encoding"] == "anchor"
    assert "Order ID" in result["compressed"]
    assert result["rawBaselineTokens"] > 0
    assert result["tokenEstimate"] > 0
