# PRD — `sheet-compressor` MCP Server

> Portfolio artifact for a OneMagnify Full Stack AI Engineer interview (Mon 2026-06-22). Wraps the existing `sheet-compressor` library (unchanged) as an MCP server exposing all three primitives plus a Bedrock-backed extraction tool. See `CONTEXT.md` for vocabulary and `docs/adr/` for decisions.

## Problem Statement

An analyst — or an LLM agent acting on their behalf — needs to answer questions about and pull structured data from large, messy `.xlsx` spreadsheets (merged cells, stacked per-region tables, blank regions, inconsistent formatting). Feeding a raw spreadsheet to an LLM is token-expensive and the model parses irregular layouts unreliably, so answers and extractions are untrustworthy.

## Solution

An **MCP server** (`sheet-compressor`) that exposes the existing library to any MCP client (Claude Desktop / Claude Code) over stdio. It turns a messy sheet into a compact, **LLM-legible encoding** and ships the reader/task prompts that teach a model to decode it — so an agent can read a big messy sheet cheaply and answer questions or extract data reliably. The point is legibility and meaningful Q&A, not the compression ratio. It demonstrates all three MCP primitives plus a stretch tool that performs an actual LLM extraction:

- **Tool — `compress_spreadsheet`**: turn an `.xlsx` sheet into a compact encoding (default `anchor`, value-preserving) plus token figures.
- **Resource — `sheet://examples/{name}`**: serve a bundled example sheet, compressed, so a client can see the encoding format.
- **Prompt — `sheet_qa`**: a ready-to-run prompt combining the encoding's reader explainer with the `sheetQA` task template, so the model can decode the sheet and answer a question.
- **Stretch tool — `extract_orders`**: compress a sheet, then make one Claude call **on Bedrock** to return schema-valid structured JSON (order line-items). The only place the server itself calls an LLM — this is what makes it an LLM-powered service rather than MCP plumbing.

## User Stories

1. As an LLM agent, I want to compress a messy `.xlsx` into a compact encoding, so that I can read a large sheet within a fraction of the token budget.
2. As an LLM agent, I want the compressed encoding to preserve every cell value, so that I can answer questions about specific orders, regions, and totals.
3. As an LLM agent, I want to choose between the `anchor`, `invertedIndex`, and `formatAggregation` encodings, so that I can trade legibility against token cost per sheet.
4. As an LLM agent, I want a sensible default encoding (`anchor`) when I don't specify one, so that I get a value-preserving, prompt-supported format without having to choose.
5. As an LLM agent, I want token figures (encoding tokens, raw baseline) returned with the compression, so that I can reason about cost.
6. As an LLM agent, I want to select a specific worksheet by name, so that I can compress the right tab of a multi-sheet workbook.
7. As an analyst, I want to ask a natural-language question about a messy spreadsheet, so that I get an answer without manually reading the sheet.
8. As an LLM client, I want to fetch a bundled example sheet as a Resource, so that I can see the encoding format before sending my own data.
9. As an LLM client, I want a `sheet_qa` prompt that bundles the reader explainer with the question, so that the model knows how to decode the encoding before answering.
10. As an analyst, I want the server to extract structured order line-items from a messy automotive sales sheet, so that I get clean JSON I can load into another system.
11. As an analyst, I want the extraction to be schema-valid JSON, so that downstream consumers don't break on malformed output.
12. As a developer, I want the LLM call routed through Amazon Bedrock, so that the demo reflects how an enterprise (OneMagnify) would govern model access.
13. As a developer, I want an Anthropic-direct fallback behind the same interface, so that a Bedrock hiccup the night before the demo doesn't sink the centerpiece.
14. As a developer, I want to swap the model id by config, so that I can demonstrate the provider/model abstraction live (Haiku 4.5 → Opus 4.8).
15. As a developer, I want the server to register cleanly in Claude Desktop over stdio, so that the tool, resource, and prompt appear in the client.
16. As a developer, I want a small eval harness of golden cases, so that I can show measurable, regression-testable model behavior — not just a one-off demo.
17. As a developer, I want a `PRODUCTION.md` describing the enterprise path, so that I can answer "how does this go to production at scale?" with an artifact, not hand-waving.
18. As a developer, I want a realistic automotive hero spreadsheet, so that the demo lands in OneMagnify's automotive vertical.
19. As a developer, I want a README with install / register / one-line demo, so that anyone can reproduce the demo in minutes.
20. As a maintainer, I want the upstream `sheet-compressor` library left unmodified, so that the server is a pure consumer.

## Implementation Decisions

- **Framework / transport**: Python 3.10+, official `mcp` SDK (`FastMCP`), stdio transport. Pure consumer of `sheet-compressor` — no edits to the library.
- **Default encoding**: `anchor` for `compress_spreadsheet` and the `sheet_qa` / `extract_orders` paths — value-preserving and LLM-legible, with a shipped reader prompt. Not `formatAggregation` (lossy). See ADR-0002. The `encoding` argument still exposes all three.
- **Prompt wiring**: `sheet_qa` composes `prompts.readers.<encoding>` + `prompts.tasks.sheetQA` from the library's Python `prompts` accessor (verified present), filling the `{ENCODING}` / `{QUESTION}` placeholders.
- **LLM provider abstraction**: a one-method provider interface with two adapters — **Bedrock primary** (classic `AnthropicBedrock` / `bedrock-runtime` InvokeModel, inference-profile id `us.anthropic.claude-haiku-4-5-20251001-v1:0`, region required — the InvokeModel path so calls are observable in model-invocation logging / CloudWatch) and **Anthropic-direct fallback** — selectable by config. Model id is a config value. See ADR-0001.
- **Output reliability**: `extract_orders` returns schema-valid JSON via a **forced single tool call** (the tool's `input_schema` is the schema; `tool_choice` pins it). The dedicated structured-outputs API (`output_config.format`) is rejected by the Bedrock endpoint — see ADR-0001. Schema: `{ orders: [{ order_id, order_date, dealership, region, make, model, qty, unit_price, total, status }], total_revenue }`.
- **Extraction at scale**: the hero sheet has ~426 orders — too many to extract in one call's output budget — so `extract_orders` fans out one bounded call per region (the sheet's natural partition), runs them concurrently, and merges, recomputing `total_revenue` as the authoritative sum. See ADR-0001.
- **Modules**: an MCP server module (registers the three primitives + stretch tool); an `llm` provider module (interface + Bedrock/Anthropic adapters); an `evals` module (golden cases + runner). Example data and the hero-file generator live under `examples/`.
- **Bundled data**: the generic ledger is the served Resource (proven, stable); the automotive hero file (`examples/northstar-auto-q3-2025.xlsx`, already built and verified) is the live-demo target for `compress_spreadsheet` / `sheet_qa` / `extract_orders`.

## Testing Decisions

- **What makes a good test**: assert external behavior of the tool functions, not the library's internals or MCP transport plumbing. Given an `.xlsx`, a tool returns the expected shape and values; given a sheet + question, `sheet_qa` returns a prompt containing the reader explainer and the filled task.
- **Seams** (fewest, highest):
  - *Seam 1 — the tool/prompt functions* (`compress_spreadsheet`, `sheet_qa`, `example_sheet`): pure and deterministic, tested directly against the bundled and hero `.xlsx` files. No MCP client needed.
  - *Seam 2 — the `llm` provider interface*: `extract_orders` depends on the interface, so tests inject a **fake provider** returning canned structured JSON to assert the tool's compose/parse behavior deterministically (no network). The same interface lets the eval harness run the real Bedrock adapter.
- **Modules tested**: the tool/prompt functions (Seam 1) and `extract_orders` against a fake provider (Seam 2). The eval harness exercises the real provider against golden cases as a separate, network-dependent check.
- **Prior art**: the upstream library's `tests/` (e.g. `test_xlsx_adapter.py`, `test_prompts.py`) model the behavior-focused style to follow.

## Out of Scope

- No edits to the upstream `sheet-compressor` library.
- No HTTP/SSE transport — stdio only (noted as a future remote-deploy option in `PRODUCTION.md`).
- No auth, persistence, or UI.
- Observability/tracing, Dockerfile, and CI eval-gates are carried as spoken narrative + `PRODUCTION.md`, not built this weekend.

## Further Notes

- **Interview framing (B)**: production judgement first, weekend velocity as the kicker. The built eval harness + `PRODUCTION.md` are the "production gestures" that counter the JD's "not prototype demos" line.
- **Delivery**: recording-first (90s capture of compress → `sheet_qa` → `extract_orders`), live-optional in Claude Desktop, with the Bedrock call pre-warmed.
- **Verified pre-build**: the library's `compress()` return shape, `read_sheet` adapter, and Python `prompts` accessor all match the reference scaffold; Bedrock model access (Haiku 4.5, Opus 4.8/4.7) is enabled.
