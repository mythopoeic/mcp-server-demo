"""LLM provider abstraction for the extract_orders stretch tool.

One-method interface (`LLMProvider.extract_structured`) with two adapters per
ADR-0001: Bedrock primary (classic ``AnthropicBedrock`` / ``bedrock-runtime``
InvokeModel, region + inference-profile model id required) and Anthropic-direct
fallback. The InvokeModel path — not the Mantle endpoint — is what Bedrock
model-invocation logging and CloudWatch metrics observe. Schema-valid JSON is
obtained via a forced single tool call (portable across both providers).
Adapters import the ``anthropic`` SDK lazily so tests that inject a fake
provider need no network or SDK install.

Tests target Seam 2 — ``extract_orders`` against a fake provider — so the real
adapters are exercised only by the eval harness, not the unit suite.
"""

from __future__ import annotations

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

    # The model is forced to call this single tool; its input_schema IS the
    # requested JSON schema, so the tool_use input is schema-valid JSON.
    _TOOL_NAME = "emit_structured_result"

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
        # Structured outputs (``output_config.format``) are rejected by the
        # Bedrock (``AnthropicBedrockMantle``) endpoint, so we force a single
        # tool call whose ``input_schema`` is the requested JSON schema and read
        # the ``tool_use`` input. This is supported uniformly across Bedrock and
        # Anthropic-direct and across model versions. See ADR-0001.
        response = self._client().messages.create(
            model=self._model_id,
            max_tokens=max_tokens,
            system=system,
            tools=[
                {
                    "name": self._TOOL_NAME,
                    "description": "Emit the result as JSON conforming to the schema.",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": self._TOOL_NAME},
            messages=[{"role": "user", "content": user}],
        )
        block = next(
            b for b in response.content
            if getattr(b, "type", None) == "tool_use"
        )
        # ``tool_use`` input is already a parsed JSON object.
        return dict(block.input)


class BedrockProvider(_MessagesProvider):
    """Bedrock-primary adapter using the classic ``AnthropicBedrock`` client.

    Calls hit the ``bedrock-runtime`` InvokeModel API (not the Mantle endpoint),
    so they are captured by Bedrock model-invocation logging and CloudWatch
    metrics — the observability/governance path (ADR-0001). On-demand Haiku 4.5
    requires a cross-region inference-profile id, e.g.
    ``us.anthropic.claude-haiku-4-5-20251001-v1:0``.
    """

    def __init__(self, *, region: str, model_id: str) -> None:
        if "anthropic." not in model_id:
            raise ValueError(
                "Bedrock model ids must name an Anthropic model "
                "(e.g. 'us.anthropic.claude-haiku-4-5-20251001-v1:0'); "
                f"got {model_id!r}"
            )
        super().__init__(model_id)
        self._region = region

    def _build_client(self):
        from anthropic import AnthropicBedrock

        return AnthropicBedrock(aws_region=self._region)


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
        model_id = env.get(
            "BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
        )
        return BedrockProvider(region=region, model_id=model_id)
    if choice == "anthropic":
        model_id = env.get("ANTHROPIC_MODEL_ID", "claude-haiku-4-5")
        return AnthropicProvider(model_id=model_id)

    raise ValueError(
        f"Unknown LLM_PROVIDER {choice!r}; expected 'bedrock' or 'anthropic'"
    )
