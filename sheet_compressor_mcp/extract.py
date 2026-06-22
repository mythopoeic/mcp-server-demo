"""The ``extract_orders`` stretch tool — compresses a sheet, then fans out one
LLM call per region (in parallel) and merges the results into order line-items.

The hero sheet stacks one table per region and holds 400+ orders in total —
far more than fit in a single call's output-token budget. So instead of
one-shotting the whole sheet, ``extract_orders`` extracts each region in its
own bounded, concurrent call and merges them, recomputing ``total_revenue`` as
the authoritative sum of every order's ``total``.

This is the only place the server itself talks to a model. The provider seam
(Seam 2) is injected so tests can drive ``extract_orders`` with a fake
provider returning canned JSON — no network, deterministic.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from sheet_compressor import prompts

from .llm import LLMProvider, build_provider_from_env
from .tools import compress_spreadsheet


# The hero sheet's four stacked per-region tables. Single source of truth for
# the regions we fan out over (the eval harness imports this to validate that
# every extracted order names a known region).
DEALER_REGIONS: tuple[str, ...] = ("Midwest", "Northeast", "Southeast", "West")

# The largest region holds ~115 orders ≈ 10k output tokens; 20k leaves ~2x
# headroom while staying under the SDK's non-streaming ceiling (~24k for this
# model), so each region call completes in one shot without streaming.
_PER_REGION_MAX_TOKENS = 20000


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
    regions: tuple[str, ...] = DEALER_REGIONS,
) -> dict:
    """Compress ``xlsx_path`` (anchor encoding) and extract orders region-by-region.

    Fans out one bounded LLM call per region — concurrently — and merges the
    results, recomputing ``total_revenue`` as the sum of every order's
    ``total`` (the authoritative figure, not the model's per-chunk arithmetic).

    The provider is injected for tests (Seam 2 — fake provider returns canned
    JSON). At runtime, ``build_provider_from_env()`` picks the configured
    adapter; each call returns schema-valid JSON via forced tool-use (ADR-0001).
    """
    if provider is None:
        provider = build_provider_from_env()

    compressed = compress_spreadsheet(xlsx_path, encoding="anchor", sheet=sheet)["compressed"]

    system = (
        f"{prompts.readers.anchor}\n\n"
        "You are an extraction assistant. Read the anchor-encoded sheet the user "
        "sends and return order line-items as JSON matching the provided schema."
    )

    def _extract_region(region: str) -> list[dict]:
        user = (
            f"Extract ONLY the orders whose region is {region}; ignore the other "
            f"regions' tables. {_TASK_PROMPT}\n\n{compressed}"
        )
        payload = provider.extract_structured(
            system=system,
            user=user,
            schema=ORDERS_SCHEMA,
            max_tokens=_PER_REGION_MAX_TOKENS,
        )
        return payload.get("orders", [])

    # IO-bound calls: one thread per region. pool.map preserves region order.
    with ThreadPoolExecutor(max_workers=len(regions)) as pool:
        per_region = list(pool.map(_extract_region, regions))

    orders = [order for region_orders in per_region for order in region_orders]
    total_revenue = sum((o.get("total") or 0) for o in orders)

    return {"orders": orders, "total_revenue": total_revenue}
