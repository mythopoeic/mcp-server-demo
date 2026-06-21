"""Seam 2 tests — ``extract_orders`` against a fake provider.

Per the PRD: the LLM provider interface is the seam; tests inject a fake
provider returning canned structured JSON to assert compose/parse behavior
deterministically (no network). Real-provider behavior is the eval harness's
job, not the unit suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sheet_compressor_mcp.extract import ORDERS_SCHEMA, extract_orders
from sheet_compressor_mcp.llm import (
    AnthropicProvider,
    BedrockProvider,
    build_provider_from_env,
)


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
HERO_XLSX = str(EXAMPLES / "northstar-auto-q3-2025.xlsx")


class FakeProvider:
    """Records the call and returns the canned response."""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[dict] = []

    def extract_structured(self, *, system, user, schema, max_tokens=4096):
        self.calls.append(
            {
                "system": system,
                "user": user,
                "schema": schema,
                "max_tokens": max_tokens,
            }
        )
        return self.response


CANNED_RESPONSE = {
    "orders": [
        {
            "order_id": "NA-001",
            "order_date": "2025-07-08",
            "dealership": "Northstar Auto Detroit",
            "region": "Midwest",
            "make": "Ford",
            "model": "F-150",
            "qty": 2,
            "unit_price": 45000.0,
            "total": 90000.0,
            "status": "delivered",
        }
    ],
    "total_revenue": 90000.0,
}


def test_extract_orders_returns_provider_payload_unchanged():
    fake = FakeProvider(CANNED_RESPONSE)
    result = extract_orders(HERO_XLSX, provider=fake)
    assert result == CANNED_RESPONSE


def test_extract_orders_passes_agreed_schema_to_provider():
    fake = FakeProvider(CANNED_RESPONSE)
    extract_orders(HERO_XLSX, provider=fake)

    assert len(fake.calls) == 1
    schema = fake.calls[0]["schema"]
    assert schema is ORDERS_SCHEMA

    order_props = schema["properties"]["orders"]["items"]["properties"]
    expected_fields = {
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
    }
    assert set(order_props.keys()) == expected_fields
    assert "total_revenue" in schema["properties"]


def test_extract_orders_user_prompt_carries_anchor_encoded_sheet():
    # Seam 2 must prove the sheet actually reaches the model — otherwise the
    # tool is calling the LLM blind. Northstar is the hero file's title block.
    fake = FakeProvider(CANNED_RESPONSE)
    extract_orders(HERO_XLSX, provider=fake)

    user = fake.calls[0]["user"]
    assert "Northstar Auto" in user


def test_extract_orders_system_prompt_includes_anchor_reader():
    # The anchor reader explainer is what teaches the model to decode the
    # encoding — the system prompt must carry it (per the PRD reader-wiring
    # decision for the LLM paths).
    fake = FakeProvider(CANNED_RESPONSE)
    extract_orders(HERO_XLSX, provider=fake)

    system = fake.calls[0]["system"]
    assert "anchor-skeleton" in system


def test_bedrock_provider_rejects_bare_model_id():
    # ADR-0001 / PRD: Bedrock model ids carry the 'anthropic.' prefix; bare
    # ids 400 on Bedrock, so the adapter must fail loudly at construction.
    with pytest.raises(ValueError, match="anthropic."):
        BedrockProvider(region="us-east-1", model_id="claude-haiku-4-5")


def test_bedrock_provider_accepts_prefixed_model_id():
    provider = BedrockProvider(region="us-east-1", model_id="anthropic.claude-haiku-4-5")
    assert provider._model_id == "anthropic.claude-haiku-4-5"


def test_build_provider_from_env_picks_bedrock_by_default():
    provider = build_provider_from_env(
        {"AWS_REGION": "us-east-1", "BEDROCK_MODEL_ID": "anthropic.claude-haiku-4-5"}
    )
    assert isinstance(provider, BedrockProvider)


def test_build_provider_from_env_picks_anthropic_when_configured():
    provider = build_provider_from_env(
        {"LLM_PROVIDER": "anthropic", "ANTHROPIC_MODEL_ID": "claude-haiku-4-5"}
    )
    assert isinstance(provider, AnthropicProvider)


def test_build_provider_from_env_rejects_unknown_choice():
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        build_provider_from_env({"LLM_PROVIDER": "openai"})
