"""MCP server entry point — registers tools with FastMCP and runs over stdio.

This module is intentionally thin: it imports the pure tool functions from
``sheet_compressor_mcp`` and binds them to MCP. Tests target the underlying
functions directly (Seam 1), so this file does not need its own test coverage.
"""

from mcp.server.fastmcp import FastMCP

from sheet_compressor_mcp.tools import compress_spreadsheet as _compress_spreadsheet

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


if __name__ == "__main__":
    mcp.run()
