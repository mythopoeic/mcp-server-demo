"""Pure tool functions wrapping the upstream sheet-compressor library.

These are the MCP server's "core" primitives — they make no LLM calls and have
no MCP-transport dependency. The MCP server module (``server.py``) registers
them with FastMCP; tests exercise them directly (Seam 1 in the PRD).
"""

from __future__ import annotations

from sheet_compressor import compress
from sheet_compressor.adapters.xlsx import read_sheet

ENCODINGS = ("anchor", "invertedIndex", "formatAggregation")


def compress_spreadsheet(
    xlsx_path: str,
    encoding: str = "anchor",
    sheet: str | None = None,
) -> dict:
    """Compress an .xlsx sheet into a compact, LLM-readable encoding.

    Default ``anchor`` is value-preserving and ships with a reader prompt per
    ADR-0002 — pick ``invertedIndex`` for sparse/repetitive sheets and
    ``formatAggregation`` only when you don't need the cell values back.
    """
    if encoding not in ENCODINGS:
        raise ValueError(
            f"Unknown encoding {encoding!r}; expected one of {ENCODINGS}"
        )

    options = {"sheet": sheet} if sheet is not None else None
    grid = read_sheet(xlsx_path, options)
    result = compress(grid)
    enc = result["encodings"][encoding]
    raw_tokens = result["rawBaseline"]["tokenEstimate"]
    enc_tokens = enc["tokenEstimate"]

    return {
        "encoding": encoding,
        "compressed": enc["string"],
        "tokenEstimate": enc_tokens,
        "rawBaselineTokens": raw_tokens,
        "savingsRatio": round(raw_tokens / enc_tokens, 1) if enc_tokens else None,
    }
