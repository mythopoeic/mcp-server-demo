"""Prove it's a real MCP server: a client that drives server.py over stdio.

Unlike demo.py (which imports the tool functions directly), this launches
server.py as a subprocess and talks to it through the official MCP client SDK —
the same JSON-RPC-over-stdio path Claude Desktop uses. You see:

  * the connect handshake (client <-> server),
  * the primitives the server advertises over the wire (tools/resource/prompt),
  * each tool call's request and response, and
  * the server's own Bedrock round-trips (its stderr trace, interleaved).

    python demo_client.py            # run straight through
    python demo_client.py --step     # pause for Enter between steps (for recording)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# UTF-8 + line buffering so client output interleaves correctly, in real time,
# with the server subprocess's stderr trace (important when recording).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

ROOT = Path(__file__).resolve().parent
HERO = str(ROOT / "examples" / "northstar-auto-q3-2025.xlsx")
STEP = "--step" in sys.argv


def rule(title: str, *, send: bool = False) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)
    if STEP and send:
        input("   [press Enter to send this request] ")


def tool_dict(res) -> dict:
    """Pull the structured dict out of a CallToolResult, however it's carried."""
    sc = getattr(res, "structuredContent", None)
    if isinstance(sc, dict):
        return sc.get("result", sc)
    for block in res.content:
        if getattr(block, "type", None) == "text":
            try:
                return json.loads(block.text)
            except json.JSONDecodeError:
                return {"text": block.text}
    return {}


async def main() -> None:
    # Launch the server with AWS config + the request/response trace switched on
    # so the recording shows the Bedrock round-trips happening inside the server.
    env = dict(os.environ)
    env.setdefault("LLM_PROVIDER", "bedrock")
    env.setdefault("AWS_REGION", "us-east-1")
    # Don't pin BEDROCK_MODEL_ID here — let the server use its configured value
    # (env / .env) or the code default (the Haiku 4.5 inference profile). Hard-
    # coding a stale id here would override a correct one.
    env["SHEET_MCP_TRACE"] = "1"

    params = StdioServerParameters(
        command=sys.executable,
        args=[str(ROOT / "server.py")],
        env=env,
        cwd=str(ROOT),
    )

    rule("CONNECT  client -> server.py over stdio (JSON-RPC)")
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print(f"connected. server: {init.serverInfo.name} v{init.serverInfo.version}")
            print(f"protocol: {init.protocolVersion}")

            # PROOF the server is a server: it advertises its primitives.
            rule("DISCOVER  what the server exposes over the wire", send=True)
            tools = await session.list_tools()
            print("tools    :", [t.name for t in tools.tools])
            try:
                templ = await session.list_resource_templates()
                print("resources:", [t.uriTemplate for t in templ.resourceTemplates])
            except Exception as exc:  # noqa: BLE001 - informational only
                print(f"resources: (unavailable: {exc})")
            prompts = await session.list_prompts()
            print("prompts  :", [p.name for p in prompts.prompts])

            # 1. TOOL ---------------------------------------------------------
            rule("1. TOOL  call compress_spreadsheet", send=True)
            res = await session.call_tool("compress_spreadsheet", {"xlsx_path": HERO})
            d = tool_dict(res)
            print(
                f"<- encoding={d.get('encoding')} "
                f"tokenEstimate={d.get('tokenEstimate'):,} "
                f"rawBaseline={d.get('rawBaselineTokens'):,}"
            )

            # 2. RESOURCE -----------------------------------------------------
            rule("2. RESOURCE  read sheet://examples/sample-orders", send=True)
            r = await session.read_resource("sheet://examples/sample-orders")
            text = r.contents[0].text
            print("<- first 3 lines:")
            print("\n".join(text.splitlines()[:3]))

            # 3. PROMPT -------------------------------------------------------
            rule("3. PROMPT  get sheet_qa", send=True)
            p = await session.get_prompt(
                "sheet_qa",
                {"encoding_text": "A1,demo", "question": "Which region had the most orders?"},
            )
            content = p.messages[0].content
            ptext = getattr(content, "text", str(content))
            print(f"<- prompt ({len(ptext):,} chars), first 3 lines:")
            print("\n".join(ptext.splitlines()[:3]))

            # 4. STRETCH TOOL (live Bedrock) ----------------------------------
            rule(
                "4. STRETCH TOOL  call extract_orders  (LIVE Bedrock - watch the server trace)",
                send=True,
            )
            res = await session.call_tool("extract_orders", {"xlsx_path": HERO})
            if getattr(res, "isError", False):
                print("<- server returned an ERROR:")
                for block in res.content:
                    if getattr(block, "type", None) == "text":
                        print("  ", block.text)
            else:
                d = tool_dict(res)
                orders = d.get("orders", [])
                regions = sorted({o.get("region") for o in orders})
                revenue = d.get("total_revenue") or 0
                print(f"<- {len(orders):,} orders across {regions}")
                print(f"<- total_revenue ${revenue:,.2f}")

    rule("DISCONNECT  server process closed")


if __name__ == "__main__":
    asyncio.run(main())
