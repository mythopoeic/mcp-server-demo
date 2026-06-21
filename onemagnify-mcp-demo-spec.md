# Build Spec — MCP Server over `sheet-compressor`

> **Self-contained brief for a build agent.** You can drop this file into the target project as-is. It assumes no outside context. Build a small, *working* MCP server that exposes the existing `sheet-compressor` library to an LLM client, demonstrating all three MCP primitives (tools, resources, prompts). Favor "small and working" over comprehensive.

---

## 1. Background (what & why)

**MCP (Model Context Protocol)** is an open standard for exposing capabilities to LLM clients (Claude Desktop, Claude Code, etc.). An MCP server can expose three primitive types:
- **Tools** — functions the model can call (with typed args + structured returns).
- **Resources** — readable data the client can fetch by URI.
- **Prompts** — reusable prompt templates the client can invoke.

**`sheet-compressor`** is an existing, published library (the build target wraps it — you are NOT modifying it). It implements the **SheetCompressor** encoding from the *SpreadsheetLLM* paper (Dong et al., Microsoft, 2024 — arXiv:2407.09025). It turns a spreadsheet into a compact, LLM-friendly text representation, cutting token cost massively, and **makes no LLM calls itself**.

- GitHub: `github.com/mythopoeic/sheet-compressor`
- Local checkout (this machine): `C:\Users\mytho\Projects\SpreadsheetLLM`
- Published: **PyPI** `sheet-compressor` (→ `import sheet_compressor`), npm `sheet-compressor` (TS reference impl), NuGet `SheetCompressor`, Go module.

**Objective:** an MCP server named `sheet-compressor` that lets an LLM agent compress a spreadsheet (so it can read a big/messy sheet cheaply), browse example sheets, and use the library's shipped reader/task prompts — over stdio, runnable in Claude Desktop / Claude Code.

**Language:** Python 3.10+ (use the PyPI `sheet-compressor` package). MCP SDK: official `mcp` (FastMCP).

---

## 2. Step 0 — VERIFY the real library API before coding (do this first)

Do **not** trust the reference snippet below blindly — confirm exact names against the installed package / repo, because the wrapper breaks if a key or import path is wrong:

```bash
pip install sheet-compressor openpyxl
python - <<'PY'
import sheet_compressor as sc
print(dir(sc))                      # confirm: compress, prompts?, adapters?
from sheet_compressor import compress
# Build the tiny grid from the README and inspect the real return shape:
grid = {"origin": {"row": 1, "col": 1}, "rows": [["Name","Qty","Price"],["Apple","3","1.50"]]}
r = compress(grid)
print(r.keys())                     # expect: encodings, rawBaseline (confirm)
print(r["encodings"].keys())        # expect: anchor, invertedIndex, formatAggregation
print(r["encodings"]["anchor"].keys())  # expect: string, json, tokenEstimate
print(r["rawBaseline"])             # expect a dict with tokenEstimate
PY
```
Also check `packages/python/README.md` in the repo for:
- the **xlsx adapter** import path (reference shows `from sheet_compressor.adapters.xlsx import read_sheet`; `read_sheet("file.xlsx")` or `read_sheet(path, {"sheet": "Q3"})`),
- the **prompts accessor** for Python (the TS API exposes `prompts.readers.{anchor,invertedIndex,formatAggregation}` and `prompts.tasks.{sheetQA,cellValueLookup,tableRegionDetection}` — find the Python equivalent; if absent, read templates from the repo's top-level `prompts/` directory).

Adjust the scaffold to whatever Step 0 reveals.

---

## 3. Known facts about `sheet-compressor` (from its README)

- **Core call:** `compress(grid)` → returns `{ encodings: {anchor, invertedIndex, formatAggregation}, rawBaseline }`.
- **Grid shape:** `{ "origin": {"row": 1, "col": 1}, "rows": [[<cell strings>], ...] }`.
- **Each encoding** carries `.string` (LLM-ready text), `.json` (structured form), `.tokenEstimate`. `rawBaseline` carries `.tokenEstimate` (the uncompressed baseline).
- **Three encodings:** `anchor` (structural-anchor skeleton — general default), `invertedIndex` (sparse/repetitive sheets), `formatAggregation` (large numeric blocks). On the bundled 576×23 ledger: raw ~10,110 tokens → anchor 807 / inverted 456 / format 160 (≈12–63× smaller).
- **Shipped prompts:** reader explainers (one per encoding) + task templates (`sheetQA {ENCODING} {QUESTION}`, `cellValueLookup`, `tableRegionDetection`). Fill placeholders via string replace.
- Library makes **no LLM/network calls**.

---

## 4. Requirements (acceptance criteria)

The server is "done" when:
1. `pip install "mcp[cli]" sheet-compressor openpyxl` then running the server starts cleanly over **stdio**.
2. It registers in **Claude Desktop** (via `mcp install server.py` or `claude_desktop_config.json`) and the tool/resource/prompt show up in the client.
3. **Tool** `compress_spreadsheet(xlsx_path, encoding="anchor", sheet=None)` returns a dict with `compressed` (the encoding string), `tokenEstimate`, `rawBaselineTokens`, and `savingsRatio`. Works on a real `.xlsx`.
4. **Resource** serves at least one bundled example sheet (compressed) by URI.
5. **Prompt** `sheet_qa(encoding_text, question)` returns a usable prompt (reader explainer + filled task template).
6. A short `README.md` in the new project shows install, register, and a one-line demo.
7. No edits to the upstream `sheet-compressor` library; it's a pure consumer.

---

## 5. Reference scaffold — `server.py`

> Treat as a starting point; reconcile names with Step 0.

```python
from mcp.server.fastmcp import FastMCP
from sheet_compressor import compress
from sheet_compressor.adapters.xlsx import read_sheet  # CONFIRM path in Step 0

mcp = FastMCP("sheet-compressor")

# ---- TOOL ----
@mcp.tool()
def compress_spreadsheet(xlsx_path: str, encoding: str = "anchor", sheet: str | None = None) -> dict:
    """Compress an .xlsx sheet into a compact, LLM-readable encoding so an agent can read a
    large/messy spreadsheet at a fraction of the tokens. Makes no LLM calls.
    encoding ∈ {anchor, invertedIndex, formatAggregation}."""
    grid = read_sheet(xlsx_path) if sheet is None else read_sheet(xlsx_path, {"sheet": sheet})
    result = compress(grid)
    enc = result["encodings"][encoding]
    raw = result["rawBaseline"]["tokenEstimate"]
    return {
        "encoding": encoding,
        "compressed": enc["string"],
        "tokenEstimate": enc["tokenEstimate"],
        "rawBaselineTokens": raw,
        "savingsRatio": round(raw / enc["tokenEstimate"], 1) if enc["tokenEstimate"] else None,
    }

# ---- RESOURCE ----
@mcp.resource("sheet://examples/{name}")
def example_sheet(name: str) -> str:
    """Serve a bundled example spreadsheet (compressed anchor form) so an agent can see the
    encoding format. Point at a real example .xlsx shipped in this project."""
    grid = read_sheet(f"examples/{name}.xlsx")
    return compress(grid)["encodings"]["anchor"]["string"]

# ---- PROMPT ----
@mcp.prompt()
def sheet_qa(encoding_text: str, question: str) -> str:
    """Prompt that teaches the model to decode a compressed sheet and answer a question
    (reader explainer + sheetQA task). Wire to the library's shipped prompts (Step 0); the
    placeholders below are literal strings to fill if accessors aren't exposed in Python."""
    reader = "<anchor reader explainer text>"          # from prompts.readers.anchor or prompts/readers/
    task = "<sheetQA task template>".replace("{ENCODING}", encoding_text).replace("{QUESTION}", question)
    return f"{reader}\n\n{task}"

if __name__ == "__main__":
    mcp.run()  # stdio transport
```

---

## 6. Register & run (Claude Desktop)

```bash
pip install "mcp[cli]" sheet-compressor openpyxl
mcp install server.py        # registers with Claude Desktop
```
Or hand-edit `claude_desktop_config.json`:
```json
{ "mcpServers": { "sheet-compressor": { "command": "python", "args": ["C:/abs/path/server.py"] } } }
```
(Claude Code: equivalent `.mcp.json` entry.) Restart the client; confirm the server appears.

**Smoke test:** in Claude Desktop, attach a messy `.xlsx` and ask: *"Use the spreadsheet tool to compress this and tell me which region had the highest profit."* The model should call `compress_spreadsheet`, then answer from the compact encoding. Surface the token savings.

---

## 7. Stretch (optional, only if core works)

A second tool `extract_orders(xlsx_path)` that compresses **then** makes one LLM call to return structured JSON (line items, SKU, qty, price). Needs an API key (e.g. `ANTHROPIC_API_KEY`) + the `anthropic` SDK. Keep it behind the working core; skip if it risks the demo.

## 8. Out of scope

- No changes to upstream `sheet-compressor`.
- No HTTP/SSE transport required (stdio is enough); mention it as a future remote-deploy option only.
- No auth, no persistence, no UI.

## 9. Deliverables

`server.py`, a `requirements.txt` (or `pyproject`), a `README.md` (install + register + demo), and at least one example `.xlsx` (copy one from the `sheet-compressor` repo's `examples/`).
