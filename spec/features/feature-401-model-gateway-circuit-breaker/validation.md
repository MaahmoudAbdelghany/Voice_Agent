# Validation Criteria: Feature 4.1 — Model Gateway, Stage-Based Model Routing & Circuit Breaker (`src/ai_core/gateway.py`)

## 1. Success Definition
The feature is complete when: every stage is routed to its configured model by code; `DIALOGUE` never exceeds 150 output tokens; a primary TTFT > 3.5s, 429, 5xx, or connection error fails over to Google Gemini (`gemini-2.0-flash`) within the same request; the per-provider breaker opens after 5 consecutive retryable failures in 60s, skips the provider instantly while OPEN, and allows exactly one HALF_OPEN probe after 60s; total LLM failure degrades to Tier 3 (search snippet) or Tier 4 (receptionist, emergency-aware) without raising; every result carries the full contract including `degradation_tier`; and unit, integration, edge-case, regression, lint, and CLI checks pass — all automated tests offline.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: `tests/test_circuit_breaker.py` (fake clock), pure helpers in `tests/test_model_gateway.py`.
- **Breaker**:
  - `test_starts_closed_and_allows`.
  - `test_trips_after_threshold_consecutive_failures`: 4 failures → CLOSED; 5th → OPEN; `allow_request()` False.
  - `test_success_resets_counter`: 4 failures, 1 success, 4 failures → still CLOSED.
  - `test_failures_outside_window_restart_count`: 4 failures, advance clock 61s, 1 failure → CLOSED (count = 1).
  - `test_half_open_after_cooldown_single_probe`: OPEN, advance 60s → first `allow_request()` True (HALF_OPEN), second False.
  - `test_probe_success_closes` / `test_probe_failure_reopens_with_new_cooldown`.
  - `test_snapshot_fields`: state, consecutive_failures, opened_at, next_probe_at.
- **Helpers**:
  - `test_stage_binding`: CLASSIFICATION/EXTRACTION → `llama-3.1-8b-instant`; DIALOGUE → `llama-3.3-70b-versatile`; fallback → `gemini-2.0-flash` (values read from settings, overridable).
  - `test_max_tokens_clamp`: DIALOGUE requested None→150, 50→50, 500→150; EXTRACTION None→256, 100→100.
  - `test_error_classification`: LiteLLM `Timeout`/`APIConnectionError`/`RateLimitError`/`InternalServerError`/`ServiceUnavailableError` and generic exceptions with `status_code` 500/503 → retryable; `BadRequestError`/`AuthenticationError`/`PermissionDeniedError`/`NotFoundError`/`UnprocessableEntityError` → non-retryable.
  - `test_litellm_model_ids`: Groq stages → `groq/llama-3.3-70b-versatile`, `groq/llama-3.1-8b-instant`; fallback → `gemini/gemini-2.0-flash`.
  - `test_litellm_call_hardening`: `LiteLLMProvider` with a patched `litellm.acompletion` records kwargs → `stream=True`, `num_retries=0`, explicit `api_key`, `stream_options={"include_usage": True}`; `litellm.telemetry is False` and no callbacks registered after gateway init.
  - `test_unconfigured_provider_detection`: empty key and `your_...` placeholders → skipped.

### Tier 2: Integration Verification
- **Scope**: `ModelGateway` + real `CircuitBreaker` + scripted fake providers implementing `LLMProvider` (stream chunks, usage, delays, raised errors) + fake `search_fallback`. File: `tests/test_model_gateway.py`.
- `test_primary_success_tier1`: text assembled, `provider="groq"`, `TIER_1_PRIMARY`, tokens/`ttft_ms`/`latency_ms` populated, `attempts` has 1 success.
- `test_dialogue_sends_clamped_max_tokens_and_bound_model`: fake provider records call kwargs → model 70B, `max_tokens=150`.
- `test_extraction_uses_8b_model`.
- `test_failover_on_429_tier2` / `test_failover_on_5xx_tier2` / `test_failover_on_connection_error_tier2`.
- `test_failover_on_ttft_timeout`: primary first chunk delayed > `ttft_timeout` (set to 0.05s in test) → TIER_2 (Gemini); elapsed < 0.5s.
- `test_non_retryable_fails_over_without_tripping`: 6× primary 401 → each request TIER_2, primary breaker still CLOSED.
- `test_breaker_open_skips_primary_instantly`: 5 failing requests → 6th request: primary fake **not called**, fallback called, primary skip time < 5ms.
- `test_half_open_probe_recovers`: after cooldown (fake clock) primary healthy → TIER_1 and breaker CLOSED.
- `test_tool_calls_assembled_from_stream_deltas`: fragmented `function.arguments` deltas → single OpenAI-format tool call with full JSON args.
- `test_astream_yields_chunks_then_result`: chunks in order, final result TIER_1.
- `test_astream_failover_before_first_chunk`: primary fails pre-first-chunk → chunks come from fallback, TIER_2.
- `test_concurrent_failures_counted_once_each`: 10 concurrent failing requests → breaker OPEN, consecutive count consistent; only one HALF_OPEN probe under concurrency.

### Tier 3: Error & Edge-Case Verification
- `test_both_providers_down_dialogue_search_tier3`: fallback returns snippet → `success=True`, `TIER_3_SEARCH_ONLY`, text contains snippet, `escalate=False`.
- `test_both_down_no_snippet_tier4`: search returns `""`/None → `TIER_4_HUMAN_ESCALATION`, `escalate=True`, receptionist message.
- `test_both_down_search_timeout_tier4`: search sleeps 1s (timeout 0.4s) → TIER_4 in < 0.6s.
- `test_both_down_search_raises_tier4`: no exception propagates.
- `test_both_down_emergency_goes_tier4_without_search`: last user message `"عندي ألم جامد في صدري"` → TIER_4, `escalate=True`, message contains emergency number `123`, search fake **not called**.
- `test_both_down_extraction_returns_failure`: `success=False`, `text=None`, TIER_4.
- `test_fallback_unconfigured_skipped`: no Gemini key + primary failure → goes to Tier 3/4 path; attempts show `skipped_unconfigured`.
- `test_mid_stream_failure_truncates_no_failover`: primary yields 2 chunks then raises → stream ends, `truncated=True`, fallback **not called**, breaker failure recorded.
- `test_finish_reason_length_surfaced`.
- `test_empty_messages_rejected_gracefully`: `[]` → `success=False`, `error_class="invalid_request"`, no provider call.
- `test_fallback_messages_voice_safe`: Tier 3/4 texts ≤ 300 chars, no `*`, `#`, `|`.
- `test_no_content_or_keys_in_info_logs`: `caplog` INFO → no message text, no phone, no API key strings.
- `test_gateway_never_raises`: provider raising arbitrary `RuntimeError` → returns `GatewayResult`.

### Tier 4: Regression Checks
- Must still pass: `tests/test_medical_schemas.py`, `tests/test_doctor_availability.py`, `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_knowledge_search.py`, `tests/test_human_handoff.py`, `tests/test_clinic_tools.py`, `tests/test_tools.py`, `tests/test_database.py`, `tests/test_clinic_repository.py`, `tests/test_session_manager.py`, `tests/test_prompts.py`.
- `Settings()` loads with the existing `.env` unchanged (new fields all have defaults); existing `llm_max_tokens` default still 512.
- **Known pre-existing legacy failures (not regressions)**: `tests/test_rag.py`, `tests/test_database_engine.py`, `tests/test_agent.py` (Phase 5 debt). Baseline recorded before implementation and compared after.

### Tier 5: Build, Lint & Type Checks
- `uv run ruff check src/ai_core src/config.py tests/test_circuit_breaker.py tests/test_model_gateway.py scripts/gateway_smoke.py`
- `uv run ruff format --check src/ai_core tests/test_circuit_breaker.py tests/test_model_gateway.py scripts/gateway_smoke.py`
- Build: `uv add litellm` resolves without downgrading existing pins; `uv sync` succeeds; `uv run python -c "import litellm, src.ai_core; from src.ai_core import get_gateway, Stage, DegradationTier"` imports cleanly.
- Type checking: **Not Applicable** — no type checker (mypy/pyright) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable (UI/audio) — this feature adds no dashboard view and no audio output; it is a backend library. The supervisor reviews the Egyptian-Arabic Tier 3/4 messages printed by the Tier 7 CLI for tone and correctness.

### Tier 7: API / CLI / Application Checks
- **Live primary (requires `GROQ_API_KEY` in `.env`)**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/gateway_smoke.py --stage dialogue --prompt "مواعيد العيادة إيه؟"
  ```
  **Expected**: `TIER_1_PRIMARY`, provider `groq`, model `llama-3.3-70b-versatile`, completion_tokens ≤ 150, TTFT printed.
- **Stage routing live**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/gateway_smoke.py --stage classification --prompt "عايز أحجز عند دكتور عظام"
  ```
  **Expected**: model `llama-3.1-8b-instant`.
- **Simulated primary outage (tests failover to Gemini if `GEMINI_API_KEY` configured)**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/gateway_smoke.py --stage dialogue --prompt "سعر الكشف كام؟" --simulate-primary-outage --repeat 7
  ```
  **Expected**: runs 1–5 show primary failure → TIER_2 Gemini (or TIER_3/4 if no Gemini key); breaker state `OPEN` printed after run 5; runs 6–7 show primary `skipped_open` with near-zero primary time.
- **Emergency degradation**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/gateway_smoke.py --stage dialogue --prompt "والدي عنده ألم جامد في صدره" --simulate-total-outage
  ```
  **Expected**: `TIER_4_HUMAN_ESCALATION`, `escalate=True`, message mentions `123`.

---

## 3. Automated Execution Commands

```powershell
# 0. Baseline before implementation (record pass/fail)
$env:PYTHONIOENCODING="utf-8"; uv run pytest -q

# 1. Feature tests
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_circuit_breaker.py tests/test_model_gateway.py -v

# 2. Lint and format
uv run ruff check src/ai_core src/config.py tests/test_circuit_breaker.py tests/test_model_gateway.py scripts/gateway_smoke.py
uv run ruff format --check src/ai_core tests/test_circuit_breaker.py tests/test_model_gateway.py scripts/gateway_smoke.py

# 3. Build / import
uv sync
uv run python -c "import litellm, src.ai_core; from src.ai_core import get_gateway, Stage, DegradationTier"

# 4. Regression
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_medical_schemas.py tests/test_doctor_availability.py tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_knowledge_search.py tests/test_human_handoff.py tests/test_clinic_tools.py tests/test_tools.py tests/test_database.py tests/test_clinic_repository.py tests/test_session_manager.py tests/test_prompts.py -v
```
