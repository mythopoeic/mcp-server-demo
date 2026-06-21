# `sheet-compressor` MCP Server

An MCP server that wraps the [`sheet-compressor`][lib] library, exposing it to
Claude Desktop / Claude Code over stdio. This issue (#2) is the first tracer
bullet: project scaffold + the `compress_spreadsheet` tool, working
end-to-end against the bundled ledger and the automotive hero file.

See [`docs/PRD.md`](docs/PRD.md) for the full product spec and
[`CONTEXT.md`](CONTEXT.md) for the domain vocabulary.

[lib]: https://github.com/mythopoeic/sheet-compressor

## Install

Python 3.10+.

```bash
pip install "mcp[cli]" sheet-compressor openpyxl
```

## Run

Over stdio (what an MCP client launches):

```bash
python server.py
```

Register with Claude Desktop:

```bash
mcp install server.py
```

Or hand-edit `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sheet-compressor": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

Restart Claude Desktop and the `compress_spreadsheet` tool will appear.

## Demo

Attach `examples/northstar-auto-q3-2025.xlsx` in Claude Desktop and ask:

> Use the spreadsheet tool to compress this and tell me which region had the most orders.

Claude will call `compress_spreadsheet`, read the compact anchor encoding, and
answer from the cell values. The tool's return surfaces the token figures.

## Tool

```
compress_spreadsheet(xlsx_path: str,
                     encoding: str = "anchor",
                     sheet: str | None = None) -> dict
```

Returns `{encoding, compressed, tokenEstimate, rawBaselineTokens, savingsRatio}`.

- `encoding` ∈ `{anchor, invertedIndex, formatAggregation}`. Default `anchor`
  is value-preserving and ships with a reader prompt — see
  [ADR-0002](docs/adr/0002-default-to-anchor-encoding-not-format-aggregation.md).
- `sheet` selects a worksheet by name in a multi-sheet workbook.

## Resource

```
sheet://examples/{name}
```

Returns the bundled example sheet in the default `anchor` encoding so a client
can see the format before sending its own data. Known names: `sample-orders`
(the generic order ledger). Unknown names return a clear `ValueError`.

## Tests

```bash
python -m pytest tests/
```

Tests run at Seam 1 (the tool function) against both the bundled
`examples/sample-orders.xlsx` ledger and the automotive hero file, and at
Seam 2 (`extract_orders` against a fake LLM provider) — fully deterministic,
no network. The upstream `sheet-compressor` library is left unmodified.

## Eval harness

```bash
python -m sheet_compressor_mcp.evals
```

Golden cases over the hero file, scored against the **real** LLM provider
(per `.env` — Bedrock primary, Anthropic-direct fallback). Network-dependent
and **separate** from the unit suite. Prints `[PASS]` / `[FAIL]` per
expectation with a final `N/M expectations passed` summary, and exits non-zero
if any expectation failed (so a CI script can gate on it). The shipped suite
checks coverage (all four regions present, ≥100 orders extracted), schema
fidelity (every order has every required field; regions/makes drawn from the
sheet's known sets), and totals consistency (`total_revenue` == sum of order
`total`s).

## Layout

```
server.py                 # MCP registration (FastMCP, stdio)
sheet_compressor_mcp/
  tools.py                # pure tool functions — tested directly
  extract.py              # extract_orders stretch tool
  llm.py                  # LLM provider abstraction (Bedrock + Anthropic)
  evals.py                # golden-case eval harness (real-provider)
examples/
  build_hero_file.py      # generator for the automotive hero file
  northstar-auto-q3-2025.xlsx
  build_ledger.py         # generator for the bundled generic ledger
  sample-orders.xlsx
tests/
  test_compress_spreadsheet.py
  test_example_sheet.py
  test_sheet_qa.py
  test_extract_orders.py
  test_evals.py
```
