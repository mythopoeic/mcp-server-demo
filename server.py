"""MCP server entry point — registers tools with FastMCP and runs over stdio.

This module is intentionally thin: it imports the pure tool functions from
``sheet_compressor_mcp`` and binds them to MCP. Tests target the underlying
functions directly (Seam 1), so this file does not need its own test coverage.
"""

from mcp.server.fastmcp import FastMCP

from sheet_compressor_mcp.tools import (
    EXAMPLE_SHEETS,
    compress_spreadsheet as _compress_spreadsheet,
    example_sheet as _example_sheet,
    sheet_qa as _sheet_qa,
)

mcp = FastMCP("sheet-compressor")


@mcp.tool()
def compress_spreadsheet(xlsx_path: str, encoding: str = "anchor", sheet: str | None = None) -> dict:
    """Compress an .xlsx into a compact, LLM-legible encoding.

    Args:
        xlsx_path: Path to the .xlsx file.
        encoding: One of ``anchor`` (default, value-preserving),
            ``invertedIndex`` (sparse/repetitive sheets), or
            ``formatAggregation`` (large numeric blocks; lossy).
        sheet: Optional worksheet name; defaults to the workbook's active sheet.

    Returns:
        ``{encoding, compressed, tokenEstimate, rawBaselineTokens, savingsRatio}``.
    """
    return _compress_spreadsheet(xlsx_path, encoding=encoding, sheet=sheet)


@mcp.resource(
    "sheet://examples/{name}",
    name="example_sheet",
    description=(
        "Bundled example sheet in compressed anchor encoding — fetch this to "
        "see the encoding format before sending your own data. Known names: "
        + ", ".join(sorted(EXAMPLE_SHEETS))
    ),
    mime_type="text/plain",
)
def example_sheet(name: str) -> str:
    """Serve a bundled example sheet, anchor-encoded.

    Unknown ``name`` raises ``ValueError`` so the MCP client gets a clear error
    instead of a server crash.
    """
    return _example_sheet(name)


@mcp.prompt()
def sheet_qa(encoding_text: str, question: str, encoding: str = "anchor") -> str:
    """Ready-to-run prompt: reader explainer + sheetQA task, filled in.

    Args:
        encoding_text: The compressed sheet string (e.g. from ``compress_spreadsheet``).
        question: The natural-language question to ask about the sheet.
        encoding: Which reader explainer to prepend — ``anchor`` (default),
            ``invertedIndex``, or ``formatAggregation``. Must match how
            ``encoding_text`` was produced.
    """
    return _sheet_qa(encoding_text, question, encoding=encoding)


if __name__ == "__main__":
    mcp.run()
