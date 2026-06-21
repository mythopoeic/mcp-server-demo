"""LLM provider abstraction for the extract_orders stretch tool.

One-method interface (`LLMProvider.extract_structured`) with two adapters per
ADR-0001: Bedrock primary (``AnthropicBedrockMantle``, ``anthropic.``-prefixed
model id, region required) and Anthropic-direct fallback. Adapters import the
``anthropic`` SDK lazily so tests that inject a fake provider need no network
or SDK install.

Tests target Seam 2 — ``extract_orders`` against a fake provider — so the real
adapters are exercised only by the eval harness, not the unit suite.
"""

from __future__ import annotations

import json
import os
from typing import Protocol


class LLMProvider(Protocol):
    """The one method the stretch tool needs from any LLM backend."""

    def extract_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int = 4096,
    ) -> dict:
        """Return the JSON object the model produced for ``user`` under ``schema``."""


class _MessagesProvider:
    """Shared call shape for both Bedrock and Anthropic-direct."""

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id
        self._instance = None

    def _build_client(self):  # pragma: no cover - overridden in subclasses
        raise NotImplementedError

    def _client(self):
        if self._instance is None:
            self._instance = self._build_client()
        return self._instance

    def extract_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int = 4096,
    ) -> dict:
        response = self._client().messages.create(
            model=self._model_id,
            max_tokens=max_tokens,
            system=system,
            output_config={"format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": user}],
        )
        text = next(
            block.text for block in response.content
            if getattr(block, "type", None) == "text"
        )
        return json.loads(text)


class BedrockProvider(_MessagesProvider):
    """Bedrock-primary adapter using ``AnthropicBedrockMantle`` (ADR-0001)."""

    def __init__(self, *, region: str, model_id: str) -> None:
        if not model_id.startswith("anthropic."):
            raise ValueError(
                f"Bedrock model ids must carry the 'anthropic.' prefix; got {model_id!r}"
            )
        super().__init__(model_id)
        self._region = region

    def _build_client(self):
        from anthropic import AnthropicBedrockMantle

        return AnthropicBedrockMantle(aws_region=self._region)


class AnthropicProvider(_MessagesProvider):
    """Anthropic-direct fallback adapter for the same interface."""

    def __init__(self, *, model_id: str) -> None:
        super().__init__(model_id)

    def _build_client(self):
        from anthropic import Anthropic

        return Anthropic()


def build_provider_from_env(env: dict[str, str] | None = None) -> LLMProvider:
    """Pick and construct an adapter from environment variables (.env contract)."""
    env = env if env is not None else os.environ
    choice = env.get("LLM_PROVIDER", "bedrock").lower()

    if choice == "bedrock":
        region = env.get("AWS_REGION", "us-east-1")
        model_id = env.get("BEDROCK_MODEL_ID", "anthropic.claude-haiku-4-5")
        return BedrockProvider(region=region, model_id=model_id)
    if choice == "anthropic":
        model_id = env.get("ANTHROPIC_MODEL_ID", "claude-haiku-4-5")
        return AnthropicProvider(model_id=model_id)

    raise ValueError(
        f"Unknown LLM_PROVIDER {choice!r}; expected 'bedrock' or 'anthropic'"
    )
