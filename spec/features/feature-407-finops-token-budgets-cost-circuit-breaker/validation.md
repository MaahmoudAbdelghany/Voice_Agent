# Validation Criteria: Feature 4.7 — FinOps Token Budgets & Cost Circuit Breaker (`src/ai_core/finops.py`)

## 1. Success Definition
Feature 4.7 is complete and verified when:
1. `src/ai_core/finops.py` tracks per-call cumulative tokens (`8,000` default budget), resolves `session_id` automatically across `finops_session_scope`, `trace_scope`, and `caller_session_scope`, clamps final-turn `max_tokens` to remaining call tokens, and blocks further LLM calls on exhaustion (`CALL_BUDGET_EXCEEDED`).
2. `FinOpsController` accumulates daily USD spend by Cairo calendar date (`Africa/Cairo`), emits an idempotent `WARNING_80_PERCENT` alert at `$8.00` (80% of `$10.00`) once per day, trips the Cost Circuit Breaker (`DAILY_CAP_EXCEEDED`) at `$10.00`, and automatically resets on Cairo day rollover.
3. `ModelGateway` enforces `FinOpsController` pre-flight checks and post-stream usage recording, degrading `Stage.DIALOGUE` calls to **Tier 3 (`TIER_3_SEARCH_ONLY`)** (or **Tier 4** on emergency / no search snippet) when the daily cost cap is breached, and escalating to **Tier 4 (`TIER_4_HUMAN_ESCALATION`, `escalate=True`)** when a call's 8,000-token budget is exhausted.
4. `prune_tool_payload()` and `format_pruned_tool_message()` deterministically strip non-essential keys from all 5 clinic tools, enforce list-item (`5`), field-length (`300`), and total payload (`1,200` chars) caps, and preserve critical booking/schedule fields (`booking_code`, `queue_number`, `fee_egp`, `available_slots`, `message`).
5. All unit, integration, edge-case, regression, lint, and CLI verification checks pass with zero regressions across Phases 1–4.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: Isolated unit tests for per-call token budget tracking, remaining-token clamping, Cairo-day daily spend accumulation, 80% / 100% alert emission idempotency, Cairo midnight rollover, `session_id` resolution hierarchy, and schema-aware tool payload pruning. File: `tests/test_finops.py`.
- [x] `test_call_token_budget_tracking_and_remaining_token_clamping`: Verifies that a session accumulating 7,920 tokens out of 8,000 clamps the next `Stage.DIALOGUE` turn's `effective_max_tokens` from `150` down to `80`, and once consumption reaches `>= 8,000` (or remaining `< 16`), returns `FinOpsGateStatus.CALL_BUDGET_EXCEEDED`.
- [x] `test_daily_spend_accumulator_80_percent_alert_and_100_percent_breaker`: Verifies that reaching `$8.00` (80% of `$10.00`) emits exactly one `WARNING_80_PERCENT` alert while still returning `ALLOWED`, and reaching `$10.00` emits one `CRITICAL_100_PERCENT` alert and transitions to `DAILY_CAP_EXCEEDED`.
- [x] `test_cairo_date_rollover_resets_daily_spend_and_alerts`: Verifies that when the Cairo calendar date advances to the next day (`YYYY-MM-DD`), daily spend resets to `$0.00`, the cost circuit breaker closes (`ALLOWED`), and the 80% alert can fire again for the new day.
- [x] `test_session_id_resolution_priority_hierarchy`: Verifies automatic `session_id` resolution across `finops_session_scope`, `trace_scope(session_id=...)`, and `caller_session_scope(caller_phone=..., session_id=...)`.
- [x] `test_prune_tool_payload_allowlist_and_size_caps`: Verifies that `prune_tool_payload()` and `format_pruned_tool_message()` strip unrecognised/internal fields across `book_appointment`, `check_doctor_availability`, `manage_appointment`, `search_clinic_knowledge`, and `transfer_to_receptionist`, cap lists at 5 items, and keep serialized JSON `<= 1,200` characters while preserving `booking_code`, `queue_number`, and `message`.

### Tier 2: Integration Verification
- **Scope**: Multi-component interaction between `ModelGateway`, `FinOpsController`, `HierarchicalTracer` (`trace_scope`), Tier 3 search fallback, and Tier 4 emergency/receptionist escalation. File: `tests/test_finops.py`.
- [x] `test_gateway_enforces_call_budget_and_escalates_to_tier4_on_exhaustion`: Running multiple turns through `ModelGateway.agenerate()` inside a session accumulates tokens automatically; once the session reaches 8,000 tokens, the next `Stage.DIALOGUE` call bypasses Groq/Gemini (0 provider attempts) and returns `DegradationTier.TIER_4_HUMAN_ESCALATION` with `escalate=True` and `error_class="call_token_budget_exceeded"`.
- [x] `test_gateway_degrades_to_tier3_search_only_when_daily_cost_cap_breached`: When `FinOpsController` daily spend reaches `$10.00`, `ModelGateway.agenerate(Stage.DIALOGUE, ...)` skips Groq and Gemini (`attempts=[]`), invokes Tier 3 search fallback, and returns `DegradationTier.TIER_3_SEARCH_ONLY` with `error_class="daily_cost_cap_exceeded"` and the grounded clinic snippet.
- [x] `test_gateway_daily_cap_breach_still_routes_emergency_to_tier4`: Even when the `$10.00` daily cost circuit breaker is tripped, an emergency caller utterance (`"عندي ألم شديد في الصدر ومش قادر أتنفس"`) is immediately routed to `DegradationTier.TIER_4_HUMAN_ESCALATION` (`escalate=True`, `error_class="emergency_detected"`) with hotline `123`.
- [x] `test_gateway_finops_decisions_recorded_in_active_trace_span`: When executed inside `trace_scope()`, the child `gateway.dialogue` span records FinOps metadata (`finops_status`, `call_tokens_used`, `daily_spend_usd`) and properly rolls up `degradation_tier`.

### Tier 3: Error & Edge-Case Verification
- **Scope**: Session LRU eviction bounds, disabled FinOps mode, non-dialogue stage rejection on budget breach, mid-stream failure token accounting, and concurrent async updates. File: `tests/test_finops.py`.
- [x] `test_session_ledger_lru_eviction_respects_max_tracked_sessions`: Setting `finops_max_tracked_sessions = 10` and recording usage across 15 distinct `session_id`s evicts the 5 oldest sessions while keeping the 10 most recent sessions intact.
- [x] `test_concurrent_async_usage_recording_consistency`: Running 25 concurrent async tasks recording token usage into the same `FinOpsController` produces the exact mathematical sum of tokens and USD spend with zero lost updates.
- [x] `test_non_dialogue_stage_returns_failed_result_on_budget_breach`: When `Stage.CLASSIFICATION` or `Stage.EXTRACTION` is called under `CALL_BUDGET_EXCEEDED` or `DAILY_CAP_EXCEEDED`, `ModelGateway` returns `success=False`, `degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION`, without attempting any LLM call.
- [x] `test_finops_disabled_bypasses_all_caps`: When `settings.finops_enabled = False`, requests exceeding 8,000 tokens or `$10.00` daily spend remain `ALLOWED`.

### Tier 4: Regression Checks
- **Scope**: Existing Phase 1–4 test suites must continue to pass without regression after integrating `FinOpsController` into `ModelGateway` and `Settings`.
- [x] `tests/test_tracing.py`, `tests/test_workflow_gates.py`, `tests/test_guardrails.py`, `tests/test_hybrid_rag.py`, `tests/test_cache_ladder.py`, `tests/test_model_gateway.py`, `tests/test_circuit_breaker.py`: Verify all Phase 4 AI Core tests pass 100% (127/127 passed).
- [x] `tests/test_database.py`, `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_doctor_availability.py`, `tests/test_clinic_tools.py`: Verify all Phase 1–3 database and medical tool tests pass 100% (125/125 passed).

### Tier 5: Build, Lint & Type Checks
- [x] **Lint Check**:
  ```powershell
  uv run ruff check src/ai_core/finops.py src/ai_core/gateway.py src/ai_core/__init__.py src/config.py tests/test_finops.py
  ```
- [x] **Format Check**:
  ```powershell
  uv run ruff format --check src/ai_core/finops.py src/ai_core/gateway.py src/ai_core/__init__.py src/config.py tests/test_finops.py
  ```
- [x] **Import & Public API Check**:
  ```powershell
  uv run python -c "from src.ai_core.finops import FinOpsController, FinOpsGateStatus, FinOpsDecision, FinOpsAlert, AlertLevel, CallBudgetSnapshot, DailySpendSnapshot, finops_session_scope, get_finops_controller, prune_tool_payload, format_pruned_tool_message"
  ```
- **Type Checking**:
  - **Status**: Not Applicable
  - **Technical Justification**: No static type checker (`mypy` or `pyright`) is installed or configured in `pyproject.toml` (`[project.optional-dependencies].dev` contains only `pytest`, `pytest-asyncio`, and `ruff`).

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: Feature 4.7 is a backend FinOps budget enforcement, cost circuit breaker, and tool payload pruning module (`src/ai_core/finops.py`) with no Streamlit UI or visual frontend components (dashboard cost/budget charts belong to Phase 7).

### Tier 7: API / CLI / Application Checks
- [x] **Live CLI Smoke Verification of FinOps Call Budget, Daily Cap Breaker & Tool Pruning**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "from src.ai_core.finops import FinOpsController, FinOpsGateStatus, prune_tool_payload`nfrom src.ai_core.gateway import Stage`nfrom src.tools.schemas import ToolResult`nctrl = FinOpsController()`nctrl.record_usage('groq/llama-3.3-70b-versatile', prompt_tokens=5000, completion_tokens=3000, session_id='call_1')`ndec = ctrl.check_budget(Stage.DIALOGUE, requested_max_tokens=150, session_id='call_1')`nassert dec.status == FinOpsGateStatus.CALL_BUDGET_EXCEEDED`npruned = prune_tool_payload('book_appointment', ToolResult(success=True, message='تم الحجز', data={'booking_code': 'NOUR-101', 'queue_number': 3, 'debug_blob': 'x'*2000}))`nassert 'booking_code' in pruned['data'] and 'debug_blob' not in pruned['data']`nprint('FinOps CLI smoke verified:', dec.status.value, pruned['data'])"
  ```

---

## 3. Automated Execution Commands

```powershell
# 1. Run Feature 4.7 FinOps Token Budgets & Cost Circuit Breaker test suite
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_finops.py -v

# 2. Run Phase 4 AI Core regression suites
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_tracing.py tests/test_workflow_gates.py tests/test_guardrails.py tests/test_hybrid_rag.py tests/test_cache_ladder.py tests/test_model_gateway.py tests/test_circuit_breaker.py -v

# 3. Run Phase 1-3 Database & Medical Tools regression suites
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_database.py tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_doctor_availability.py tests/test_clinic_tools.py -v

# 4. Run Ruff linter & format checks
uv run ruff check src/ai_core/finops.py src/ai_core/gateway.py src/ai_core/__init__.py src/config.py tests/test_finops.py
uv run ruff format --check src/ai_core/finops.py src/ai_core/gateway.py src/ai_core/__init__.py src/config.py tests/test_finops.py
```
