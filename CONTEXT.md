# MCP Server Demo

An MCP (Model Context Protocol) server that exposes the `sheet-compressor` library to LLM clients, built as a portfolio artifact for a OneMagnify Full Stack AI Engineer interview. The demo's job is to evidence the JD's explicit MCP requirement and demonstrate production judgement, not just protocol mechanics.

## Language

**MCP server**:
The program in this repo (`server.py`) that exposes capabilities to an LLM client over stdio. Named `sheet-compressor` to the client.
_Avoid_: service, API (those imply the production HTTP shape this demo deliberately is not)

**Primitive**:
One of the three things an MCP server can expose: a Tool, a Resource, or a Prompt. The demo ships all three.

**Tool**:
A function the LLM client can call with typed args and a structured return.

**Resource**:
Readable data the client fetches by URI (here, a bundled example sheet served compressed).

**Prompt**:
A reusable prompt template the client can invoke (here, `sheet_qa`).

**Core**:
The three primitives wrapping `sheet-compressor` directly. Makes **no LLM calls** — the AI reasoning happens in the client.

**Stretch tool**:
The `extract_orders` tool: it compresses a sheet **and then** makes one LLM call to return structured JSON. This is the only place the server itself talks to a model — it is what makes the demo an "LLM-powered service" rather than MCP plumbing.
_Avoid_: bonus, optional (it is the centerpiece of the AI-engineering story, not a throwaway)

**Encoding**:
One of `sheet-compressor`'s three compact text representations of a sheet: `anchor` (general default), `invertedIndex` (sparse/repetitive), `formatAggregation` (large numeric blocks). Each carries `.string`, `.json`, `.tokenEstimate`.

**Raw baseline**:
The uncompressed token count of a sheet. A secondary, supporting figure — the demo's point is that the encoding makes a messy sheet **LLM-legible and answerable**, not the compression multiple. Compression is a means (cheaper, more legible), not the headline.

**Hero file**:
The custom, deliberately-messy automotive `.xlsx` built for this demo (a regional dealer-group sales/orders sheet). It is the file the live demo runs `compress_spreadsheet` and `extract_orders` against, chosen so the demo lands in OneMagnify's automotive vertical. Distinct from the bundled generic ledger, which stays the served Resource for its proven token numbers.
_Avoid_: test file, sample (it is the demo centerpiece)

**Production gesture**:
A deliberately-included signal (e.g. evaluation, observability, a deploy path) that bridges the gap between a weekend prototype and the "enterprise scale" the JD demands. The demo stays weekend-sized but points credibly at production.
