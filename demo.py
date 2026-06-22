"""Command-line walkthrough of the sheet-compressor MCP server.

Runs the same flow a Claude Desktop client would drive, but straight from the
terminal so you can demo without a client:

  1. Tool          compress_spreadsheet  - messy .xlsx -> compact anchor encoding
  2. Resource      example_sheet         - a bundled sheet, pre-encoded
  3. Prompt        sheet_qa              - reader explainer + sheet + question
  4. Stretch tool  extract_orders        - one live Bedrock call per region -> JSON

Steps 1-3 are local and instant (no LLM, no credentials). Step 4 calls Claude
on Bedrock and takes ~40-50s; it needs AWS credentials in the standard chain
(~/.aws/credentials). The .env defaults (bedrock / us-east-1 / haiku-4-5) are
baked into the code, so no environment setup is required.

    python demo.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Surface each Bedrock round-trip (per region, with timing) on stderr so a
# recording shows the calls going out and results coming back. See extract._trace.
os.environ.setdefault("SHEET_MCP_TRACE", "1")

from sheet_compressor_mcp.extract import extract_orders
from sheet_compressor_mcp.tools import compress_spreadsheet, example_sheet, sheet_qa

# Render the library's prompt text (em-dashes, etc.) correctly on Windows
# consoles, and line-buffer so stdout interleaves with the stderr trace in order.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

HERO = str(Path(__file__).resolve().parent / "examples" / "northstar-auto-q3-2025.xlsx")


def rule(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def head(text: str, n: int) -> str:
    return "\n".join(text.splitlines()[:n])


def main() -> None:
    # 1. TOOL ---------------------------------------------------------------
    rule("1. TOOL  compress_spreadsheet  (local, no LLM)")
    c = compress_spreadsheet(HERO, encoding="anchor")
    print(f"encoding      : {c['encoding']}  (value-preserving; legibility over raw ratio)")
    print(f"tokenEstimate : {c['tokenEstimate']:,}")
    print(f"rawBaseline   : {c['rawBaselineTokens']:,}")
    print("\nfirst 6 lines of the anchor encoding:")
    print(head(c["compressed"], 6))

    # 2. RESOURCE -----------------------------------------------------------
    rule("2. RESOURCE  sheet://examples/sample-orders  (local, no LLM)")
    print(head(example_sheet("sample-orders"), 6))

    # 3. PROMPT -------------------------------------------------------------
    rule("3. PROMPT  sheet_qa  (local, no LLM - the client's model answers it)")
    question = "Which region had the most orders?"
    prompt = sheet_qa(c["compressed"], question)
    print(f"question: {question}")
    print(f"\nassembled prompt: {len(prompt):,} chars (reader explainer + sheet + task)")
    print("first 8 lines:")
    print(head(prompt, 8))

    # 4. STRETCH TOOL -------------------------------------------------------
    rule("4. STRETCH TOOL  extract_orders  (LIVE Bedrock - ~40-50s, 4 regions in parallel)")
    print("calling Claude on Bedrock, one bounded call per region ...")
    result = extract_orders(HERO)
    orders = result["orders"]
    regions = sorted({o["region"] for o in orders})
    print(f"\nextracted {len(orders):,} orders across regions {regions}")
    print(f"total_revenue : ${result['total_revenue']:,.2f}")
    print("\nsample order:")
    for k, v in orders[0].items():
        print(f"  {k:12}: {v}")


if __name__ == "__main__":
    main()
