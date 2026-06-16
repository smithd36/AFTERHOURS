# ADR-006: LLM Thesis Layer — Pluggable Providers and Prompt-Level JSON

**Status:** Accepted
**Date:** 2026-06-09
**Deciders:** Lead Architect

---

## Context

Phase 2 introduces the first LLM-powered component: a thesis generator that watches
accumulated signals and produces structured trade theses. Several design decisions were
required:

1. Which LLM provider(s) to support, and how to make the choice swappable.
2. How to reliably extract structured data from LLM responses without requiring
   provider-specific JSON modes or function-calling APIs.
3. How to handle thesis invalidation in Phase 2 given that programmatic condition
   evaluation (e.g. "price drops below X") requires the risk engine not yet built.

---

## Decisions

### 1. Pluggable `LLMProvider` ABC

A single `async complete(messages, *, max_tokens) -> str` interface abstracts all
providers. Concrete implementations are lazy-imported so uninstalled SDKs do not
cause import errors — only a failure when that provider is actually selected.

The factory (`create_provider`) validates the required API key at startup and raises
a clear `ValueError` before any requests are made.

**Supported providers:**

| Provider | Implementation | Notes |
|---|---|---|
| `ollama` | `httpx` to local `/api/chat` | No SDK, no API key, default for dev |
| `groq` | `openai` SDK, custom `base_url` | Free 14k req/day |
| `mistral` | `openai` SDK, custom `base_url` | Free 1B tokens/month |
| `openrouter` | `openai` SDK, custom `base_url` | Free 50 req/day; wide model selection |
| `anthropic` | `anthropic` SDK | Paid; native system-message separation |
| `openai` | `openai` SDK | Paid |

Groq, Mistral, and OpenRouter all use a single `OpenAICompatibleProvider` class —
they share the same request/response shape and only differ in `base_url` and API key.

### 2. Prompt-level JSON extraction with one retry

Rather than relying on provider-specific JSON modes (not universally available,
especially on Ollama), the generator:

1. Prompts the model to return a specific JSON schema with no surrounding text.
2. Strips markdown code fences and extracts the first `{...}` block via regex.
3. On parse failure, appends the bad response and a correction request, then retries once.
4. If the second attempt also fails, logs a warning and drops the generation — no
   partial or malformed thesis is emitted.

This approach works identically across all six providers without branching logic.

### 3. Time-based invalidation only in Phase 2

Invalidation conditions are captured as plain-language strings in the thesis
(e.g. "BTC drops below 60000" or "ETH RSI crosses below 30"). Programmatic
evaluation of these conditions requires:
- A parsed condition format (not free text)
- Access to current market state at evaluation time
- Integration with the risk engine

All three prerequisites belong to Phase 3+. In Phase 2, `ThesisInvalidator` only
performs time-based expiry: a thesis is invalidated when its `time_horizon_hours`
elapses. The plain-language conditions are displayed in the UI so the operator can
evaluate them manually.

### 4. Signal citation via `supporting_signal_ids`

Each emitted thesis records the UUIDs of the signals that triggered it in
`supporting_signal_ids`. This enables audit replay: given a thesis, the full
evidence set can be reconstructed from the event store by signal ID. Signals without
a parseable UUID are silently skipped rather than failing the generation.

---

## Consequences

### Positive
- Provider swap is a one-line `.env` change (`LLM_PROVIDER=groq` → `mistral`, etc.).
- Free-tier providers (Groq, Mistral, OpenRouter) cover all of Phase 2–3 development
  with no API spend required.
- JSON extraction without JSON mode means identical code paths for all providers,
  including local Ollama models that may not support structured output.
- Thesis cites its evidence — supports the audit trail that is a project non-negotiable.

### Negative / constraints
- Prompt-level JSON is less reliable than native JSON mode. The one-retry mechanism
  handles most failures, but persistent model misbehaviour will produce dropped
  generations (logged as warnings) rather than malformed output.
- Plain-language invalidation conditions are not machine-checkable in Phase 2.
  The operator must monitor them manually via the ThesisFeed panel.
- `time_horizon_hours` is LLM-supplied and therefore untrusted. Phase 3 should
  clamp it to a configured maximum before the risk engine uses it for position sizing.

---

## When to revisit

- **Phase 3 (risk engine):** parse invalidation conditions into a structured format
  the risk engine can evaluate against live ticks. Clamp `time_horizon_hours`.
- **Phase 4 (execution):** consider switching the default to a faster/cheaper
  provider for high-frequency thesis updates, or adding a "thesis refresh" path
  that updates confidence as new signals arrive.

---

## Addendum (2026-06-16): JSON mode + outbound rate limiting

Two refinements after observing free-tier behaviour in multi-instance data collection.
Neither reverses the original decisions; both are additive and opt-out.

**1. Native JSON mode is now used where available, with prompt-level extraction retained
as the fallback.** Decision #2 (prompt-level JSON, *no* provider-specific JSON modes) was
chosen for uniform code paths. In practice the OpenAI-compatible providers (Groq, Mistral)
support `response_format=json_object`, which makes valid JSON on the first try and removes
most of the one-retry round-trips — meaningful when those retries were doubling calls against
a tight per-minute rate limit. So `OpenAICompatibleProvider` now sets `response_format` by
default (`LLM_JSON_MODE`, default on). The prompt-level `_extract_json` + one-retry path is
**unchanged** and still runs — it remains the cross-provider contract (and the only path for
Ollama/Anthropic, which don't go through this provider). Caveat: some OpenRouter models reject
`response_format` with a `400`; set `LLM_JSON_MODE=false` for those.

**2. Client-side rate limiting + Retry-After backoff.** Free-tier `429`s turned out to be
*per-minute* (RPM/TPM) limits tripped by signal bursts, not the daily caps. The provider chain
is now `CachingProvider → ThrottledProvider → <provider>`: a requests-per-minute token bucket +
concurrency cap (`reasoning/llm/throttle.py`, auto-on for the free providers) smooths bursts,
and `OpenAICompatibleProvider` owns a Retry-After-aware retry loop that logs the rate-limit
headers (`llm.rate_limited`). The throttle sits *inside* the cache, so cache hits never wait.
Key caveat: provider limits are **per-account, not per-key** — instances sharing one free
account share one bucket, so `LLM_MAX_RPM` must be split across them. Full operational detail
and tuning: `docs/development.md` → *LLM Providers — Rate Limiting & Resilience*.
