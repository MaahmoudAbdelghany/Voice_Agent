# Validation Criteria: Feature 4.6 — Hierarchical LLM Trace Logging (`src/ai_core/tracing.py`)

## 1. Success Definition
Feature 4.6 is complete and verified when:
1. `src/ai_core/tracing.py` generates W3C-compliant 32-hex `trace_id` and 16-hex `span_id` identifiers, tracks multi-level `parent_span_id` nesting via `contextvars` (`trace_scope`, `span_scope`, `@traced_span`), and supports W3C `traceparent` header parsing and injection (`parse_traceparent`, `format_traceparent`, `inject_trace_headers`).
2. Core AI pipeline components (`InputGuardrail`, `CacheLadder`, `ModelGateway`, `HybridRetriever`, `AppointmentWorkflowStateMachine`, `OutputGuardrail`) automatically record nested child spans when executed inside an active `trace_scope()`, rolling up `total_prompt_tokens`, `total_completion_tokens`, `total_tokens`, `total_cost_usd`, `ttft_ms`, `degradation_tier`, and `error_category` to the root `TraceRecord`.
3. `AsyncTraceExporter` and `HierarchicalTracer` scrub 100% of Egyptian PII (`[REDACTED_PHONE]`, `[REDACTED_NATIONAL_ID]`) off the hot path via `EgyptianPIIRedactor.redact_dict()` before committing traces to `recent_traces` or dispatching Langfuse batch HTTP payloads (`/api/public/ingestion`), while keeping hot-path span recording latency **< 1ms**.
4. `AsyncLlamaGuardClassifier` off-hot-path safety verdicts automatically attach to their corresponding `TraceRecord` by `trace_id`, and Langfuse connection failures or unconfigured states degrade gracefully to a local no-op without raising exceptions.
5. All unit, integration, concurrency, edge-case, regression, lint, and CLI verification checks pass with zero regressions across Phases 1–4.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: Isolated unit tests for W3C `trace_id` / `span_id` / `traceparent` parsing and formatting, multi-level `parent_span_id` hierarchy, `estimate_llm_cost_usd()` calculations, error classification (`INFRASTRUCTURE` vs `SEMANTIC` vs `SECURITY_BLOCK`), and < 1ms hot-path latency budget. File: `tests/test_tracing.py`.
- [x] `test_w3c_traceparent_format_and_parse_roundtrip`: Verifies `generate_trace_id()` (32 lowercase hex), `generate_span_id()` (16 lowercase hex), `format_traceparent()`, `parse_traceparent()`, and `trace_scope(traceparent=...)` adopting the remote `trace_id` and `parent_span_id`, while rejecting malformed/all-zero headers gracefully.
- [x] `test_nested_span_hierarchy_and_parent_span_ids`: Verifies that a 3-level nested span hierarchy (`trace_scope` -> `span_scope("outer")` -> `span_scope("inner")`) assigns the exact `parent_span_id` chain (`root_span_id` -> `outer.span_id` -> `inner.span_id`) and rolls up token counts and `total_cost_usd` to the `TraceRecord`.
- [x] `test_estimate_llm_cost_usd_for_configured_models`: Verifies deterministic USD cost calculation for `groq/llama-3.3-70b-versatile`, `groq/llama-3.1-8b-instant`, and `gemini/gemini-2.0-flash` based on `settings.llm_cost_per_1m_tokens`.
- [x] `test_hot_path_span_recording_under_1ms`: Measures 100 iterations of opening and closing `trace_scope` + 3 child `span_scope` blocks on the hot path (before async flush) and asserts average hot-path overhead is **< 1.0ms**.

### Tier 2: Integration Verification
- **Scope**: End-to-end auto-instrumentation across `InputGuardrail`, `CacheLadder`, `ModelGateway`, `AppointmentWorkflowStateMachine`, `OutputGuardrail`, `AsyncLlamaGuardClassifier`, and Langfuse HTTP batch ingestion (`httpx.MockTransport`). File: `tests/test_tracing.py`.
- [x] `test_auto_instrumented_pipeline_builds_complete_trace_tree`: Executing `InputGuardrail.evaluate()`, `CacheLadder.lookup()`, `ModelGateway.agenerate()`, and `OutputGuardrail.validate()` inside a single `trace_scope("voice_turn")` followed by `await tracer.flush()` produces a single `TraceRecord` in `tracer.recent_traces` containing child spans for `GUARDRAIL_INPUT`, `CACHE`, `LLM`, and `GUARDRAIL_OUTPUT` with rolled-up tokens, cost, `ttft_ms`, and `degradation_tier`.
- [x] `test_pre_export_pii_redaction_scrubs_egyptian_phone_and_national_id`: Recording spans whose `input_payload`, `output_payload`, and `attributes` contain raw Egyptian mobile numbers (`01012345678`, `٠١١٢٣٤٥٦٧٨٩`) and 14-digit National IDs (`29501010101234`) results in 100% redacted payloads (`[REDACTED_PHONE]`, `[REDACTED_NATIONAL_ID]`) in both `tracer.recent_traces` and the exported Langfuse JSON batch.
- [x] `test_langfuse_http_batch_export_payload_structure`: Using an injected `httpx.MockTransport`, verifies that when `langfuse_enabled=True` with valid keys, `await tracer.flush()` sends `POST /api/public/ingestion` with Basic Auth and a `batch` array containing `trace-create`, `generation-create` (for LLM spans with usage/cost/model), and `span-create` events.
- [x] `test_async_llama_guard_verdict_attaches_to_trace`: Scheduling or evaluating an `AsyncLlamaGuardClassifier` check with `trace_id` attaches the `LlamaGuardVerdict` (`safe`, `category_codes`) to the corresponding `TraceRecord` metadata.

### Tier 3: Error & Edge-Case Verification
- **Scope**: Concurrent `contextvars` isolation (`asyncio.gather`), Langfuse server outage/timeout resilience, disabled tracing no-op mode, and queue backpressure. File: `tests/test_tracing.py`.
- [x] `test_concurrent_async_traces_strict_contextvars_isolation`: Running 20 concurrent async tasks via `asyncio.gather`, each opening its own `trace_scope` and recording 3 child spans with task-specific markers, results in 20 distinct `TraceRecord` objects with zero cross-contamination of spans or `trace_id`s.
- [x] `test_langfuse_outage_and_timeout_degrades_to_noop`: When the mock Langfuse server returns HTTP 503 or raises `httpx.ConnectTimeout`, `await tracer.flush()` catches the error, increments `exporter.failed_batches_count`, preserves the sanitized trace in `recent_traces`, and never raises an exception to the caller.
- [x] `test_tracing_disabled_is_strict_noop`: When `settings.tracing_enabled = False`, `trace_scope` and `span_scope` execute as fast no-ops without queuing or exporting traces.

### Tier 4: Regression Checks
- **Scope**: Existing Phase 1–4 test suites must pass without regression after adding auto-instrumentation hooks to `gateway.py`, `cache.py`, `guardrails.py`, `workflow.py`, and `hybrid_retriever.py`.
- [x] `tests/test_workflow_gates.py`, `tests/test_guardrails.py`, `tests/test_hybrid_rag.py`, `tests/test_cache_ladder.py`, `tests/test_model_gateway.py`, `tests/test_circuit_breaker.py`: Verify all Phase 4 AI Core tests pass 100%.
- [x] `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_doctor_availability.py`, `tests/test_clinic_tools.py`, `tests/test_database.py`: Verify all Phase 1–3 database and tool tests pass 100%.

### Tier 5: Build, Lint & Type Checks
- [x] **Lint Check**:
  ```powershell
  uv run ruff check src/ai_core/tracing.py src/ai_core/gateway.py src/ai_core/cache.py src/ai_core/guardrails.py src/ai_core/workflow.py src/rag/hybrid_retriever.py src/ai_core/__init__.py src/config.py tests/test_tracing.py
  ```
- [x] **Format Check**:
  ```powershell
  uv run ruff format --check src/ai_core/tracing.py tests/test_tracing.py
  ```
- [x] **Import & Public API Check**:
  ```powershell
  uv run python -c "from src.ai_core.tracing import HierarchicalTracer, AsyncTraceExporter, TraceRecord, SpanRecord, SpanKind, SpanStatus, trace_scope, span_scope, traced_span, format_traceparent, parse_traceparent, get_tracer"
  ```
- **Type Checking**:
  - **Status**: Not Applicable
  - **Technical Justification**: No static type checker (`mypy` or `pyright`) is installed or configured in `pyproject.toml` (`[project.optional-dependencies].dev` contains only `pytest`, `pytest-asyncio`, and `ruff`).

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: Feature 4.6 is a backend observability and trace logging module (`src/ai_core/tracing.py`) with no Streamlit UI or visual frontend components (dashboard trace visualization belongs to Phase 7).

### Tier 7: API / CLI / Application Checks
- [x] **Live CLI Smoke Verification of Hierarchical Trace Tree & PII Redaction**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "import asyncio`nfrom src.ai_core.tracing import get_tracer, trace_scope, span_scope, SpanKind`ntracer = get_tracer()`nasync def main():`n    async with trace_scope('cli_smoke_turn', input_payload='رقمي 01012345678') as t:`n        with span_scope('child_op', kind=SpanKind.TOOL, input_payload={'phone': '01012345678'}) as s:`n            s.set_output({'status': 'ok'})`n    await tracer.flush()`n    rec = tracer.get_trace(t.trace_id)`n    assert rec is not None and '[REDACTED_PHONE]' in str(rec.input_payload)`n    print('Trace verified:', rec.trace_id, 'spans:', len(rec.spans))`nasyncio.run(main())"
  ```

---

## 3. Automated Execution Commands

```powershell
# 1. Run Feature 4.6 Hierarchical LLM Trace Logging test suite
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_tracing.py -v

# 2. Run Phase 4 AI Core regression suites
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_workflow_gates.py tests/test_guardrails.py tests/test_hybrid_rag.py tests/test_cache_ladder.py tests/test_model_gateway.py tests/test_circuit_breaker.py -v

# 3. Run Phase 1-3 Database & Medical Tools regression suites
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_database.py tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_doctor_availability.py tests/test_clinic_tools.py -v

# 4. Run Ruff linter & format checks
uv run ruff check src/ai_core/tracing.py src/ai_core/gateway.py src/ai_core/cache.py src/ai_core/guardrails.py src/ai_core/workflow.py src/rag/hybrid_retriever.py src/ai_core/__init__.py src/config.py tests/test_tracing.py
uv run ruff format --check src/ai_core/tracing.py tests/test_tracing.py
```
