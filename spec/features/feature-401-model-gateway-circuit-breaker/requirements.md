# Requirements Specification: Feature 4.1 — Model Gateway, Stage-Based Model Routing & Circuit Breaker

> Traces to parent requirements R1 (R1.1–R1.6) and R2 (R2.1–R2.2) in `feature-400-.../requirements.md`.

## 1. Functional Requirements

### R1: Single Gateway Entry Point
- **R1.1**: All new LLM calls must go through `ModelGateway` (`agenerate()` for full responses, `astream()` for incremental text). Callers pass a `Stage` and OpenAI-format `messages`; optional `tools`, `temperature`, `max_tokens`.
- **R1.2**: The gateway must support Groq (primary) and Google Gemini `gemini-2.0-flash` (fallback) through a **LiteLLM**-based provider adapter (`litellm.acompletion`, model IDs `groq/<model>` and `gemini/<model>`). Providers are pluggable via a `LLMProvider` protocol.
- **R1.3**: A provider whose API key is missing or a placeholder (`your_...`) must be skipped without counting as a failure.
- **R1.4**: LiteLLM must be used only as the provider client: its built-in `Router` fallbacks/cooldowns must not be used; `num_retries=0`; telemetry disabled; no LiteLLM success/failure callbacks registered; API keys passed explicitly per provider.

### R2: Deterministic Stage-Based Routing
- **R2.1**: `Stage.CLASSIFICATION` and `Stage.EXTRACTION` must use `llm_stage_model` (default `llama-3.1-8b-instant`); `Stage.DIALOGUE` must use `groq_model` (default `llama-3.3-70b-versatile`).
- **R2.2**: The stage → model mapping must come from `src/config.py` only. No LLM call may be used to choose a model.
- **R2.3**: The fallback model for every stage is `gemini_fallback_model` (default `gemini-2.0-flash`, sent to LiteLLM as `gemini/gemini-2.0-flash`).

### R3: Token Caps
- **R3.1**: For `Stage.DIALOGUE`, effective `max_tokens = min(requested or 150, voice_max_tokens)`; it must never exceed `voice_max_tokens` (default 150).
- **R3.2**: Other stages use `stage_max_tokens` (default 256) unless a smaller value is requested.

### R4: Timeouts & Retries
- **R4.1**: If the first token/chunk does not arrive within `llm_ttft_timeout_s` (default 3.5s), the attempt is aborted and treated as a retryable failure.
- **R4.2**: Each attempt is bounded by `llm_request_timeout_s` (default 10s) total.
- **R4.3**: Automatic retries must be disabled (`num_retries=0` in LiteLLM); failover to the next tier is the only retry mechanism.

### R5: Circuit Breaker
- **R5.1**: Each provider has its own breaker with states `CLOSED`, `OPEN`, `HALF_OPEN`.
- **R5.2**: Retryable failures = timeout, connection error, HTTP 429, HTTP 5xx (LiteLLM: `Timeout`, `APIConnectionError`, `RateLimitError`, `ServiceUnavailableError`, `InternalServerError`, or any exception with `status_code` ≥ 500). Non-retryable client errors (400/401/403/404/422 — `BadRequestError`, `AuthenticationError`, `PermissionDeniedError`, `NotFoundError`, `UnprocessableEntityError`) must not change breaker state.
- **R5.3**: The breaker trips to `OPEN` after `circuit_breaker_failure_threshold` (5) consecutive retryable failures whose first failure is within `circuit_breaker_window_s` (60s). A success resets the counter. Failures older than the window restart counting.
- **R5.4**: While `OPEN`, requests must skip the provider immediately (no network call, no timeout wait) for `circuit_breaker_cooldown_s` (60s).
- **R5.5**: After cooldown the breaker enters `HALF_OPEN` and allows exactly **one** probe request. Probe success → `CLOSED`; probe failure → `OPEN` with a new cooldown. Other requests during the probe skip the provider.
- **R5.6**: Breaker state must be inspectable (`state`, `snapshot()`) for future dashboards/tracing.

### R6: 4-Tier Degradation Chain
- **R6.1**: Order: Tier 1 primary (Groq) → Tier 2 fallback (Google Gemini) → Tier 3 search-only → Tier 4 human escalation.
- **R6.2**: Any primary failure (retryable or not) or primary breaker `OPEN` must move the same request to Tier 2.
- **R6.3** (`DIALOGUE` only): If Tiers 1–2 fail, and the latest user message is an emergency (via `detect_emergency`), return Tier 4 immediately with `escalate=True` and an Egyptian-Arabic message mentioning the emergency number from config.
- **R6.4** (`DIALOGUE` only): Otherwise call the configured `search_fallback(query)` (default: clinic knowledge-search tool) with a timeout of 400ms. A non-empty snippet → Tier 3 result (`success=True`, text = short apology + snippet). Empty/failed/timed-out → Tier 4 receptionist message with `escalate=True`.
- **R6.5** (`CLASSIFICATION`/`EXTRACTION`): If Tiers 1–2 fail, return `success=False`, `text=None`, `degradation_tier=TIER_4_HUMAN_ESCALATION`.
- **R6.6**: The gateway must never raise to the caller for provider failures; it always returns a `GatewayResult`.

### R7: Result Contract
- **R7.1**: Every `GatewayResult` must include: `success`, `text`, `tool_calls`, `stage`, `provider`, `model`, `degradation_tier`, `escalate`, `truncated`, `finish_reason`, `ttft_ms`, `latency_ms`, `prompt_tokens`, `completion_tokens`, `error_class`, and `attempts` (ordered list of `{provider, model, outcome}`).
- **R7.2**: `degradation_tier` uses exactly: `TIER_1_PRIMARY`, `TIER_2_BACKUP`, `TIER_3_SEARCH_ONLY`, `TIER_4_HUMAN_ESCALATION`.
- **R7.3**: Tool calls returned by providers (including those assembled from streamed deltas) must be exposed as OpenAI-format dicts (`id`, `type`, `function.name`, `function.arguments`).

### R8: Streaming Semantics
- **R8.1**: `astream()` yields text chunks as they arrive and exposes the final `GatewayResult` after completion.
- **R8.2**: Failover is allowed only **before** the first chunk is yielded. A failure after the first chunk ends the stream, sets `truncated=True`, and records a breaker failure.
- **R8.3**: When degraded to Tier 3/4, `astream()` yields the fallback message as a single chunk.

---

## 2. Non-Functional Requirements
- **NFR1 (Overhead)**: Gateway logic (binding, breaker check, result building) adds **< 5ms** excluding provider network time.
- **NFR2 (Fast fail when OPEN)**: With the primary breaker OPEN, time to start the fallback attempt is **< 5ms** (no primary wait).
- **NFR3 (Concurrency)**: Breaker updates are safe under concurrent async calls (no lost failure counts, single half-open probe).
- **NFR4 (Privacy/Logging)**: Logs at INFO must not contain message content, phone numbers, or API keys — only stage, provider, model, tier, timings, error class.
- **NFR5 (Voice-friendly fallbacks)**: Tier 3/4 messages are Egyptian Arabic, ≤ 300 characters, no Markdown symbols.
- **NFR6 (Offline testability)**: All automated tests run without network or real API keys.

---

## 3. Constraints
- **C1**: Do not modify `src/agent/voice_agent.py` or the LiveKit plugin wiring (deferred to Feature 5.3).
- **C2**: Do not change the default of existing `llm_max_tokens`; add new fields instead.
- **C3**: No secrets in code, logs, or prompt content; `.env.example` gets placeholders only.
- **C4**: The only new dependency is **`litellm`** (added via `uv add`, recorded in `uv.lock`); it must resolve alongside existing pins (e.g. `onnxruntime<1.20`) without downgrading them.
- **C5**: The gateway must not perform side effects such as creating escalation tickets; it only signals `escalate=True`.
- **C6**: All thresholds/models live in `src/config.py` (Invariant 8, parent C2/C4).
