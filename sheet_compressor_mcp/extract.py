"""The ``extract_orders`` stretch tool — compresses a sheet, then calls the
LLM provider once with structured outputs to return order line-items.

This is the only place the server itself talks to a model. The provider seam
(Seam 2) is injected so tests can drive ``extract_orders`` with a fake
provider returning canned JSON — no network, deterministic.
"""

from __future__ import annotations

from sheet_compressor import prompts

from .llm import LLMProvider, build_provider_from_env
from .tools import compress_spreadsheet


ORDERS_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "orders": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "order_id": {"type": "string"},
                    "order_date": {"type": "string"},
                    "dealership": {"type": "string"},
                    "region": {"type": "string"},
                    "make": {"type": "string"},
                    "model": {"type": "string"},
                    "qty": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "total": {"type": "number"},
                    "status": {"type": "string"},
                },
                "required": [
                    "order_id",
                    "order_date",
                    "dealership",
                    "region",
                    "make",
                    "model",
                    "qty",
                    "unit_price",
                    "total",
                    "status",
                ],
            },
        },
        "total_revenue": {"type": "number"},
    },
    "required": ["orders", "total_revenue"],
}


_TASK_PROMPT = (
    "Extract every order line-item from the compressed spreadsheet below.\n"
    "Return one object per order; populate every field of the schema. Use ISO\n"
    "dates (YYYY-MM-DD) for order_date. ``total_revenue`` is the sum of the\n"
    "orders' ``total`` values. If a value is missing from the sheet, use an\n"
    "empty string for text fields and 0 for numeric fields — do not invent\n"
    "data."
)


def extract_orders(
    xlsx_path: str,
    *,
    sheet: str | None = None,
    provider: LLMProvider | None = None,
) -> dict:
    """Compress ``xlsx_path`` (anchor encoding) and ask the provider for orders.

    The provider is injected for tests (Seam 2 — fake provider returns canned
    JSON). At runtime, ``build_provider_from_env()`` picks the configured
    adapter; the result is schema-valid JSON per ADR-0001.
    """
    if provider is None:
        provider = build_provider_from_env()

    compressed = compress_spreadsheet(xlsx_path, encoding="anchor", sheet=sheet)["compressed"]

    system = (
        f"{prompts.readers.anchor}\n\n"
        "You are an extraction assistant. Read the anchor-encoded sheet the user "
        "sends and return order line-items as JSON matching the provided schema."
    )
    user = f"{_TASK_PROMPT}\n\n{compressed}"

    return provider.extract_structured(
        system=system,
        user=user,
        schema=ORDERS_SCHEMA,
    )
