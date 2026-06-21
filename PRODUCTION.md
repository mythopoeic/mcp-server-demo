# PRODUCTION.md — From Weekend Demo to Enterprise MCP Service

> The demo in [`README.md`](README.md) is a stdio MCP server — small, working,
> wires up cleanly in Claude Desktop and Claude Code, and ships the centerpiece
> `extract_orders` call on Bedrock. This document is the **spoken-narrative
> artifact** for "how does this go to production at scale?" It is not built
> this weekend; it is the credible path forward, written down.

The shape is deliberate: keep what already works (the tool/prompt seams, the
provider abstraction, the eval harness) and rewire only what the deployment
boundary changes (transport, host, observability, gates).

## 1. Transport: stdio → HTTP/SSE

**Today.** `FastMCP("sheet-compressor").run()` speaks stdio. The MCP client
spawns the Python process per session; one client, one process, no network
hop. Right for desktop use, wrong for multi-tenant.

**Production.** Switch the transport to **HTTP with Server-Sent Events**
(streamable HTTP, the MCP spec's remote transport). FastMCP exposes
`mcp.run(transport="streamable-http", host=..., port=...)` — the tool /
resource / prompt definitions are unchanged. The wire format changes; the
seams don't. That's the value of having all four primitives behind pure
functions in `sheet_compressor_mcp/`: nothing in `tools.py`, `extract.py`,
or `llm.py` is transport-coupled.

**Auth.** Bearer tokens (OAuth 2.1 per the MCP spec) terminated at the edge
(API Gateway / ALB). The server itself stays trust-the-caller; auth is the
edge's job.

## 2. Deploy targets: ECS or Lambda behind API Gateway

Two reasonable shapes, picked by traffic profile:

| Shape | When it fits | Why |
|---|---|---|
| **ECS Fargate task + ALB** | Bursty + sustained: dozens-to-hundreds of concurrent sessions; long-lived SSE streams; warm `AnthropicBedrockMantle` client cached in-process | No cold-start; in-memory cache for compressed sheets pays back; tasks scale on `RequestCountPerTarget` |
| **Lambda + API Gateway (WebSocket or HTTP-stream)** | Spiky, low-baseline: a few analysts a day; cost-optimized; long idle periods | Cold-start tolerable when the call is already ~1–3s of Bedrock latency; no idle compute bill |

Both sit behind **API Gateway** for auth, rate limiting, and request
logging. Network egress to Bedrock stays inside the VPC (Bedrock VPC
endpoint), so the spreadsheet payload never leaves AWS.

**Container image** is a standard `python:3.12-slim` base + this repo's
`requirements.txt`. The eval harness is the image's smoke test in CI.

## 3. Bedrock for governance and data residency

The provider abstraction (ADR-0001) already routes the centerpiece LLM
call through `AnthropicBedrockMantle`. That choice **is** the enterprise
governance story:

- **Data residency.** Bedrock keeps the request payload (the compressed
  sheet — which still contains every cell value under the `anchor`
  encoding) inside the selected AWS region. `AWS_REGION` in the env block
  is a compliance control, not just a config knob.
- **No model-training carve-out needed.** Bedrock's terms exclude customer
  data from training by default; no separate Zero Data Retention
  negotiation required.
- **IAM-scoped model access.** Which models a deployed task can invoke is
  IAM policy on the task role (`bedrock:InvokeModel` for specific model
  ARNs) — not an API key. Rotation is role-rotation.
- **Right-sized model id.** `BEDROCK_MODEL_ID=anthropic.claude-haiku-4-5`
  is the production default (sub-second, cheap, sufficient for
  schema-bounded extraction from a pre-compressed grid). The id is config,
  so an operator flips to `anthropic.claude-opus-4-8` for sensitive
  high-stakes batches without a redeploy.
- **Anthropic-direct fallback.** `LLM_PROVIDER=anthropic` is a one-env-var
  failover for the rare Bedrock-region incident. Same `extract_structured`
  interface; same JSON schema; no caller changes.

## 4. Caching

Two layers, both cheap:

1. **Compressed-sheet cache** (in-process LRU, ECS) or **ElastiCache**
   (Lambda). Key: `sha256(xlsx bytes) + encoding + sheet name`. Value: the
   `compress()` result. Justification: the library makes **no** network
   calls but does walk every cell, and clients re-attach the same file
   across a conversation. A cache hit on `compress_spreadsheet` skips
   straight to formatting the response. Estimated 30–60% hit rate during a
   single analyst session.
2. **Bedrock prompt cache.** The `extract_orders` system prompt (anchor
   reader explainer + extraction directive) is identical across every
   call. Marked as a cache breakpoint, it slashes input-token cost on the
   high-volume use case (overnight batch extraction) by ~80%.

Cache invalidation is by content hash — the file's bytes change, the key
changes, the entry expires by LRU. No timestamp games.

## 5. Observability

The eval harness already proves the model *works*; observability proves it
**keeps** working in production.

- **Structured logs.** Every `extract_orders` call emits one JSON log line:
  `{request_id, xlsx_bytes_len, encoding, sheet, tokens_in, tokens_out,
   provider, model_id, latency_ms, orders_count, total_revenue,
   schema_valid: true|false}`. Schema-valid is always `true` today
   (structured outputs enforce it server-side); logging it explicitly is the
   canary for the day a model change drops structured-output support.
- **CloudWatch metrics.** Latency p50/p95/p99, error rate by exception
   class, Bedrock throttle count, cache hit rate. SLO: p95 < 3s for the hero
   sheet's size class.
- **CloudWatch Logs Insights queries** for the standard cuts: regressions in
   orders-extracted-per-call, sudden drops in `total_revenue` reasonableness.
- **LangSmith** (or equivalent — Langfuse, Arize Phoenix) for trace-level
   inspection of the LLM call: prompt, raw model output, parsed JSON,
   latency. The provider seam is exactly the right place to add tracing as
   a wrapper adapter (`TracingProvider(inner)`) — no `extract_orders`
   change.
- **OpenTelemetry** spans wrap `compress_spreadsheet` and the provider
   call, propagating the API Gateway request id end-to-end.

## 6. CI eval gates

The eval harness in `sheet_compressor_mcp/evals.py` is the deployment
gate. Its exit code is the contract:

```yaml
# .github/workflows/release.yml (sketch)
jobs:
  unit:
    steps:
      - run: pip install -r requirements.txt
      - run: pytest tests/                 # deterministic, no network
  evals:
    needs: unit
    environment: bedrock-eval               # OIDC-assumed role w/ bedrock:InvokeModel
    steps:
      - run: pip install -r requirements.txt
      - run: python -m sheet_compressor_mcp.evals
  release:
    needs: [unit, evals]
    steps:
      - run: ./build-and-push-image.sh
      - run: aws ecs update-service ...
```

The unit suite gates **every** PR. The eval harness gates **every release**
— it costs a real Bedrock call per case, runs in a few seconds, and catches
the failure modes a unit test can't (a model upgrade that drops a region,
totals that no longer reconcile, schema regressions in the underlying
Messages API). The split — fast deterministic unit tests + slow real-model
evals — is the same split that makes [`tests/`](tests/) and
[`sheet_compressor_mcp/evals.py`](sheet_compressor_mcp/evals.py) two
modules instead of one.

## 7. What stays the same

The point of this document is what **does not** change:

- The four primitive definitions in `tools.py`, `extract.py` — same
  signatures, same return shapes.
- The `LLMProvider` interface — `extract_structured(system, user, schema)`.
  Tracing, caching, and rate limiting all attach as adapter wrappers; no
  call-site edits.
- The `compress_spreadsheet` → `sheet_qa` → `extract_orders` demo flow.
  Same three calls in production as in the README's one-line demo.
- The upstream `sheet-compressor` library, untouched.

That's the production gesture the JD asks for: an artifact that points
credibly at scale without overbuilding the weekend.
