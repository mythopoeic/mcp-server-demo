"""Seam 1 tests — `example_sheet` resource function against the bundled ledger.

The `sheet://examples/{name}` MCP Resource (issue #3) serves a bundled example
sheet compressed in the default `anchor` encoding, so an MCP client can see
the encoding format before sending its own data. Tests target the underlying
pure function — no MCP transport plumbing.
"""

import asyncio

import pytest

from sheet_compressor_mcp.tools import EXAMPLE_SHEETS, example_sheet


def test_example_sheet_returns_anchor_encoded_string_for_known_name():
    # The bundled generic ledger is the proven sample — anchor encoding must
    # preserve a known header so a reader can land on cell values.
    result = example_sheet("sample-orders")

    assert isinstance(result, str)
    assert "Order ID" in result


def test_example_sheet_registry_lists_sample_orders():
    # The Resource's discoverable names live in EXAMPLE_SHEETS so the server
    # can register one resource template and an explicit registry doc.
    assert "sample-orders" in EXAMPLE_SHEETS


def test_example_sheet_unknown_name_raises_clear_error():
    # Per the acceptance criteria, an unknown {name} must fail loudly with a
    # clear error rather than crash the server.
    with pytest.raises(ValueError) as exc:
        example_sheet("not-a-real-example")

    msg = str(exc.value)
    assert "not-a-real-example" in msg
    assert "sample-orders" in msg  # known names listed in the error


def test_resource_registered_on_mcp_server_and_fetchable_by_uri():
    # Thin wiring check beyond Seam 1: confirm the `sheet://examples/{name}`
    # template lands in FastMCP's registry and reading the URI returns the
    # anchor-encoded text. Catches breakage in `server.py`'s decorator wiring
    # without needing a real MCP client.
    from server import mcp

    async def _run():
        templates = await mcp.list_resource_templates()
        uris = [t.uriTemplate for t in templates]
        assert "sheet://examples/{name}" in uris

        contents = list(await mcp.read_resource("sheet://examples/sample-orders"))
        assert contents and "Order ID" in contents[0].content

    asyncio.run(_run())
