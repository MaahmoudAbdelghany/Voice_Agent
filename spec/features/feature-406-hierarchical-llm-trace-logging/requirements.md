# Requirements Specification: Feature 4.6 — Hierarchical LLM Trace Logging (`src/ai_core/tracing.py`)

> Parent spec: `spec/features/feature-400-enterprise-ai-architecture-and-resilience/requirements.md` (R6, R11, R15, NFR4, NFR5).

---

## 1. Functional Requirements

### R1: Hierarchical OpenTelemetry-Compatible Trace & Span Tree
- **R1.1**: Every conversational turn executed within `trace_scope()` must generate a unique 128-bit W3C-compatible `trace_id` (32 lowercase hex characters) and a root turn `span_id` (16 lowercase hex characters).
- **R1.2**: Every child operation executed within `span_scope()` or `@traced_span` must generate a unique 64-bit `span_id` (16 lowercase hex characters) and automatically link its `parent_span_id` to the enclosing active span (or the root trace span if at the top level), forming a multi-level hierarchical span tree.
- **R1.3**: Spans must classify their operational stage via `SpanKind` (`TURN`, `GUARDRAIL_INPUT`, `GUARDRAIL_OUTPUT`, `CACHE`, `ROUTER`, `LLM`, `RAG`, `WORKFLOW`, `TOOL`, `SAFETY_ASYNC`) and outcome via `SpanStatus` (`OK`, `ERROR`, `DEGRADED`, `BLOCKED`, `BYPASSED`).

### R2: Transparent Auto-Instrumentation & Rollup Metrics
- **R2.1**: When an active trace context is present in `contextvars`, the core pipeline modules must automatically record child spans without requiring caller code changes:
  1. `InputGuardrail.evaluate()` -> `SpanKind.GUARDRAIL_INPUT` (logging `action`, `category`, `matched_rule`, `escalate`).
  2. `CacheLadder.lookup()` & `CacheLadder.store()` -> `SpanKind.CACHE` (logging `tier`, `hit`, `similarity`, `bypass_reason`).
  3. `ModelGateway.astream()` / `agenerate()` -> `SpanKind.ROUTER` (for `CLASSIFICATION`/`EXTRACTION`) or `SpanKind.LLM` (for `DIALOGUE`), logging `provider`, `model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `cost_usd`, `ttft_ms`, `degradation_tier`, `error_class`, and `attempts_count`.
  4. `HybridRetriever.search()` -> `SpanKind.RAG` (logging `category`, `top_k`, `results_count`).
  5. `AppointmentWorkflowStateMachine.execute()` -> `SpanKind.WORKFLOW` (logging `action`, `terminal_state`, `steps_taken`, `idempotent_replay`, `spoof_attempt_blocked`, `error_class`).
  6. `OutputGuardrail.validate()` -> `SpanKind.GUARDRAIL_OUTPUT` (logging `allowed`, `violation_category`).
- **R2.2**: When the root `trace_scope()` closes, the `TraceRecord` must automatically roll up across all child spans:
  - `total_prompt_tokens`, `total_completion_tokens`, `total_tokens`
  - `total_cost_usd` (computed deterministically from `settings.llm_cost_per_1m_tokens`)
  - `degradation_tier` (highest/most degraded tier encountered during the turn)
  - `ttft_ms` (from the dialogue LLM span, if any)
  - `error_category` (`NONE`, `INFRASTRUCTURE`, `SEMANTIC`, `SECURITY_BLOCK`) and `error_class`.

### R3: `contextvars` Async Concurrency Isolation & W3C `traceparent` Propagation
- **R3.1**: Active trace and span contexts must be stored in Python `contextvars.ContextVar` instances so that concurrent asynchronous calls (`asyncio.gather` / parallel LiveKit room sessions) never leak or cross-contaminate spans across callers.
- **R3.2**: The tracer must implement W3C Trace Context v1 (`00-<32-hex-trace-id>-<16-hex-span-id>-<2-hex-flags>`):
  - `format_traceparent()` and `inject_trace_headers()` must serialize the current active `trace_id` and `span_id` into a valid `traceparent` header.
  - `parse_traceparent()` and `trace_scope(traceparent=...)` must accept an incoming W3C `traceparent` header, adopt its `trace_id`, and set the remote `span_id` as the initial `parent_span_id`.

### R4: Mandatory Pre-Export Egyptian PII Redaction
- **R4.1**: Before any `TraceRecord` or `SpanRecord` is committed to the in-memory `recent_traces` ring buffer or exported over HTTP to Langfuse, all `input_payload`, `output_payload`, and `attributes` fields across all spans must be scrubbed via `EgyptianPIIRedactor.redact_dict()` (`[REDACTED_PHONE]`, `[REDACTED_NATIONAL_ID]`, `[REDACTED_CARD]`, `[REDACTED_EMAIL]`).
- **R4.2**: PII redaction must execute during the asynchronous flush/export phase (off the voice hot path) so that span creation and completion remain sub-millisecond while guaranteeing zero raw patient PII in stored or exported traces.

### R5: Self-Hosted Langfuse Batch Export & Graceful No-Op Degradation
- **R5.1**: Completed traces must be placed into an in-memory bounded queue (`put_nowait`) and flushed asynchronously (`await tracer.flush()` or background flush worker) to both:
  1. A bounded in-memory ring buffer (`tracer.recent_traces`, default 200 traces) for fast inspection and dashboard display.
  2. The configured self-hosted Langfuse Ingestion API (`POST {langfuse_host}/api/public/ingestion` with Basic Auth `langfuse_public_key:langfuse_secret_key`), formatting root traces as `trace-create`, LLM/router spans as `generation-create`, and other spans as `span-create`.
- **R5.2**: If Langfuse is disabled (`langfuse_enabled=False`), unconfigured, or unreachable (timeout, HTTP 5xx, connection refused), the exporter must catch all exceptions, increment an internal failure counter, and degrade gracefully to a local no-op without raising exceptions or impacting the caller session.
- **R5.3**: When `AsyncLlamaGuardClassifier` completes an off-hot-path safety evaluation carrying a `trace_id`, the verdict (`safe`, `category_codes`, `status`) must be attached to the corresponding `TraceRecord` in `recent_traces` (and queued as a Langfuse event/score if Langfuse is enabled).

---

## 2. Non-Functional Requirements

### NFR1: Sub-Millisecond Hot-Path Overhead (< 1ms Target)
- Creating a root `trace_scope()` and recording a child `span_scope()` on the hot path must add **< 1ms** (target **< 0.2ms**) of CPU latency before async background flushing (`spec/tech.md` Invariant 7).

### NFR2: Zero Patient PII Leakage
- 100% of Egyptian mobile/landline phone numbers (ASCII and Arabic-Indic numerals) and 14-digit Egyptian National IDs present in caller inputs, tool arguments, or outputs must be masked in `TraceRecord` and Langfuse batch payloads.

### NFR3: Data Sovereignty
- The default `langfuse_host` must point to self-hosted infrastructure (`http://localhost:3000`); no telemetry or trace payloads may be dispatched to external cloud SaaS unless explicitly configured by clinic ops.

---

## 3. Constraints & Invariants

- **C1 (Zero Heavy SDK Dependencies)**: Do not add heavy third-party tracing SDKs to `pyproject.toml`; use standard library `contextvars`, `uuid`/`secrets`, `pydantic`, and existing `httpx` for Langfuse REST batch ingestion.
- **C2 (100% Backward Compatibility)**: When code runs outside of an active `trace_scope()`, all existing Phase 1–4 modules (`gateway.py`, `cache.py`, `guardrails.py`, `workflow.py`, `hybrid_retriever.py`) must behave identically to before and pass all existing test suites without modification.
- **C3 (Configurable Thresholds)**: All tracing toggles, queue bounds, flush intervals, Langfuse URL/keys, and per-1M-token model pricing must reside in `src/config.py`.
