# `sheet-compressor` MCP Server

An MCP server that wraps the [`sheet-compressor`][lib] library, exposing it to
Claude Desktop / Claude Code over stdio. It demonstrates all three MCP
primitives — **Tool**, **Resource**, **Prompt** — plus a stretch **`extract_orders`**
tool that makes one Claude call on Bedrock to return schema-valid order JSON.

See [`docs/PRD.md`](docs/PRD.md) for the full spec, [`CONTEXT.md`](CONTEXT.md)
for the domain vocabulary, and [`PRODUCTION.md`](PRODUCTION.md) for the
enterprise path (transport, deploy, governance, observability, CI gates).

[lib]: https://github.com/mythopoeic/sheet-compressor

## Install

Python 3.10+.

```bash
pip install -r requirements.txt
cp .env.example .env   # adjust LLM_PROVIDER / AWS_REGION / model ids
```

`extract_orders` needs AWS credentials in the standard chain
(`~/.aws/credentials`, SSO, instance role) or — if you flip
`LLM_PROVIDER=anthropic` — `ANTHROPIC_API_KEY` in your environment. The Core
primitives (`compress_spreadsheet`, `example_sheet`, `sheet_qa`) make **no**
LLM calls and need no credentials.

## Register

### Claude Desktop

```bash
mcp install server.py
```

Or hand-edit `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sheet-compressor": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"],
      "env": {
        "LLM_PROVIDER": "bedrock",
        "AWS_REGION": "us-east-1",
        "BEDROCK_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      }
    }
  }
}
```

Restart Claude Desktop and the tool, resource, and prompt appear in the
client.

### Claude Code

Add a `.mcp.json` at the repo root (or `~/.claude/mcp.json` for global):

```json
{
  "mcpServers": {
    "sheet-compressor": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"],
      "env": {
        "LLM_PROVIDER": "bedrock",
        "AWS_REGION": "us-east-1",
        "BEDROCK_MODEL_ID": "us.anthropic.claude-haiku-4-5-20251001-v1:0"
      }
    }
  }
}
```

Then `/mcp` inside Claude Code confirms `sheet-compressor` is connected and
lists the three primitives + the stretch tool.

## Demo

The demo runs against `examples/northstar-auto-q3-2025.xlsx` (the
**automotive hero file**: regional dealer-group sales, deliberately messy —
merged headers, stacked per-region tables, blank gaps). One-line summary, in
the client:

> Use sheet-compressor to compress `examples/northstar-auto-q3-2025.xlsx`,
> then use `sheet_qa` to tell me which region had the most orders, then run
> `extract_orders` on the same file and report the total revenue.

That asks the client to walk the three primitives in sequence:

1. **`compress_spreadsheet`** turns the hero file into the compact anchor
   encoding and returns its token figures.
2. **`sheet_qa`** wraps the encoding with the anchor reader explainer + the
   `sheetQA` task template so the model can decode the sheet and answer the
   region question from cell values — no extra LLM call from the server.
3. **`extract_orders`** compresses the sheet again and fans out one Bedrock
   call per region (concurrently), merging to `{orders: [...], total_revenue}`.

This is the flow the [eval harness](#eval-harness) regression-tests, and the
flow [`PRODUCTION.md`](PRODUCTION.md) describes hardening for enterprise
deployment.

## Tool — `compress_spreadsheet`

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

Makes no LLM calls — the AI reasoning happens in the client.

## Resource — `sheet://examples/{name}`

Returns the bundled example sheet in the default `anchor` encoding so a
client can see the format before sending its own data. Known names:
`sample-orders` (the generic order ledger). Unknown names return a clear
`ValueError`.

## Prompt — `sheet_qa`

```
sheet_qa(encoding_text: str, question: str, encoding: str = "anchor") -> str
```

Composes the encoding's reader explainer with the library's `sheetQA` task
template, substituting `{ENCODING}` and `{QUESTION}`. Hand this back to the
client and the model has everything it needs to decode the compressed sheet
and answer the question — no extra round-trip through this server.

## Stretch tool — `extract_orders`

```
extract_orders(xlsx_path: str, sheet: str | None = None) -> dict
```

Compresses `xlsx_path` (anchor encoding), then extracts order line-items —
**on Bedrock** by default per
[ADR-0001](docs/adr/0001-bedrock-provider-and-model-for-stretch-tool.md) —
returning:

```
{
  "orders": [
    {order_id, order_date, dealership, region, make, model,
     qty, unit_price, total, status},
    ...
  ],
  "total_revenue": <number>
}
```

The hero sheet holds **~426 orders** — too many for one call's output budget —
so `extract_orders` fans out **one bounded call per region** (the sheet's
natural partition), runs them **concurrently**, and merges, recomputing
`total_revenue` as the authoritative sum of every order's `total`. Each call
returns schema-valid JSON via a **forced tool call** (the Bedrock endpoint
doesn't accept the `output_config.format` structured-outputs API — see
ADR-0001). A full extraction runs ~40–50s.

The provider is selected by `LLM_PROVIDER` (`bedrock` | `anthropic`); the
model id is a config value — live-swap Haiku 4.5 → Opus 4.8 by editing the
client's env block. This is the only place the server itself calls an LLM.

## Tests

```bash
python -m pytest tests/
```

Tests run at Seam 1 (the tool functions) against both the bundled
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
PRODUCTION.md             # the enterprise path — transport, deploy,
                          # governance, observability, CI eval gates
```
