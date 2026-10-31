# Validation Criteria: Feature 4.5 — Deterministic State Machine, Idempotency Keys & Write Safety Gates

## 1. Success Definition
Feature 4.5 is complete and verified when:
1. `CallerSessionContext` and `caller_session_scope()` (`src/tools/gates.py`) isolate caller identity per async task via `contextvars`, automatically injecting the verified session phone into booking and appointment management operations and overriding/blocking any spoofed phone parameter (`spoof_attempt_blocked=True`), while `LLMAppointmentBookingInput` and `LLMManageAppointmentInput` (`src/tools/schemas.py`) omit `patient_phone`, `phone`, and `patient_id` from LLM-facing schemas (`get_session_scoped_tool_definitions()`).
2. `DeterministicWriteGate` (`src/tools/gates.py`) enforces all 6 clinic preconditions in Python code before any database write (active doctor, active shift schedule, Cairo date/time window, strict `booked_count < max_capacity`, 14-day consultation eligibility downgrade, and caller phone ownership for cancel/reschedule) and returns a structured `GateVerdict` with 7-day `next_available` suggestions when a shift is unavailable or full.
3. `IdempotencyStore` and `compute_booking_idempotency_key()` (`src/tools/gates.py`) compute deterministic SHA-256 keys (`patient_phone + doctor_id + schedule_id + appointment_date`), serve idempotent replays (`success=True`, `idempotent_replay=True`, identical `booking_code` and `queue_number`) within a 24-hour window without incrementing queue numbers or creating duplicate database rows, and automatically invalidate keys when an appointment is cancelled or rescheduled.
4. `AppointmentWorkflowStateMachine` (`src/ai_core/workflow.py`) executes `BOOK`, `CANCEL`, `RESCHEDULE`, and `LOOKUP` deterministically across explicit finite states (`INIT -> SLOT_COLLECTION -> PRECONDITION_GATE -> IDEMPOTENCY_CHECK -> ATOMIC_EXECUTION -> COMPLETED / REJECTED_BY_GATE / ESCALATED`) with a strict step budget (`workflow_max_steps = 6`) and structured `WorkflowStepTrace` telemetry.
5. All unit, integration, concurrency, edge-case, regression, lint, and CLI verification checks pass with zero regressions across Phases 1–4.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: Isolated unit tests for idempotency key hashing, `IdempotencyStore` TTL/LRU/invalidation logic, `CallerSessionContext` / `resolve_effective_caller_phone()` `contextvars` isolation, `LLMAppointmentBookingInput` / `LLMManageAppointmentInput` schema constraints, and step-budget state transitions. File: `tests/test_workflow_gates.py`.
- **Idempotency Hashing & Store (`src/tools/gates.py`)**:
  - [x] `test_compute_booking_idempotency_key_deterministic_and_normalized`: Verifies that equivalent Egyptian phone formats (`"01012345678"`, `"+20 10 1234 5678"`, `"00201012345678"`) produce the exact same 64-character SHA-256 hex digest for the same `(doctor_id, schedule_id, appointment_date)`, and different dates/doctors/schedules produce distinct keys.
  - [x] `test_idempotency_store_ttl_expiry_lru_and_invalidation`: Verifies storing, retrieving, TTL expiration, LRU eviction when `max_entries` is exceeded, and explicit invalidation by `idempotency_key` or `booking_code`.
- **Session-Injected Caller Identity & Schema Isolation (`src/tools/gates.py`, `src/tools/schemas.py`)**:
  - [x] `test_caller_session_scope_isolation_and_spoof_override`: Verifies that inside `caller_session_scope("01011112222")`, `resolve_effective_caller_phone("01299998888")` returns `("01011112222", True)` (`spoof_attempt_blocked=True`), and concurrent `asyncio.gather` tasks maintain separate `CallerSessionContext` values via `contextvars`.
  - [x] `test_llm_session_scoped_schemas_forbid_phone_and_patient_id`: Verifies that `LLMAppointmentBookingInput` and `LLMManageAppointmentInput` reject payloads containing `patient_phone`, `phone`, or `patient_id` (`extra="forbid"`), and `get_session_scoped_tool_definitions()` exposes zero phone parameters on `book_appointment` and `manage_appointment`.

### Tier 2: Integration Verification
- **Scope**: Multi-component database + gate + workflow state machine flows across `AppointmentWorkflowStateMachine`, `DeterministicWriteGate`, `IdempotencyStore`, `AppointmentBookingTool`, `ManageAppointmentTool`, and `ClinicRepository`. File: `tests/test_workflow_gates.py`.
- [x] `test_workflow_book_idempotent_replay_returns_same_queue_number`: Executing `AppointmentWorkflowStateMachine.execute(action=WorkflowAction.BOOK, ...)` twice for the same patient, doctor, and date within 24h transitions through `IDEMPOTENCY_CHECK -> COMPLETED` on the second call, returning `success=True`, `idempotent_replay=True`, the exact same `booking_code` and `queue_number`, and only 1 database row in `appointments`.
- [x] `test_workflow_cancel_invalidates_idempotency_allowing_rebook`: Booking an appointment via the workflow, cancelling it via `WorkflowAction.CANCEL`, and then booking the same doctor and date again creates a fresh confirmed booking (`idempotent_replay=False`) instead of replaying the cancelled record.
- [x] `test_workflow_session_phone_prevents_cross_patient_cancel_and_lookup`: When Patient A (`01011111111`) has a confirmed booking `APT-...` and Caller B (`01022222222`) invokes `manage_appointment` or `AppointmentWorkflowStateMachine` inside `caller_session_scope("01022222222")` attempting to cancel or reschedule Patient A's `booking_code` (even if passing Patient A's phone in arguments), the gate blocks the spoof attempt and rejects the operation with `error_code="phone_mismatch"`, leaving Patient A's appointment `CONFIRMED`.
- [x] `test_workflow_reschedule_atomic_swap_and_gate_validation`: Executing `WorkflowAction.RESCHEDULE` inside `caller_session_scope` validates ownership and target shift capacity via `DeterministicWriteGate`, atomically cancels the old appointment and creates the new one, and records `step_traces` ending in `WorkflowState.COMPLETED`.

### Tier 3: Error & Edge-Case Verification
- **Scope**: Shift capacity exhaustion, concurrency race conditions, inactive doctors, consultation 14-day downgrade, missing slots, and step-budget exhaustion. File: `tests/test_workflow_gates.py`.
- [x] `test_deterministic_gate_rejects_full_shift_with_next_available`: When a doctor's shift has `booked_count == max_capacity`, `DeterministicWriteGate.verify_booking()` and `AppointmentWorkflowStateMachine` reject the write in Python code (`terminal_state == WorkflowState.REJECTED_BY_GATE`, `error_code == "shift_full"`), populate `next_available` for the next open shift within 7 days, and leave DB row count unchanged.
- [x] `test_concurrent_workflow_bookings_never_exceed_shift_capacity`: Launching 5 concurrent `AppointmentWorkflowStateMachine.execute(BOOK)` coroutines via `asyncio.gather` against a shift with `max_capacity = 2` results in exactly 2 `COMPLETED` bookings (queue numbers 1 and 2) and 3 `REJECTED_BY_GATE` (`shift_full`) responses.
- [x] `test_workflow_step_budget_exhaustion_escalates_safely`: Configuring `AppointmentWorkflowStateMachine(max_steps=2)` on a multi-step booking flow aborts deterministically at step 3 with `terminal_state == WorkflowState.ESCALATED`, `error_class == "step_budget_exhausted"`, and `escalate == True`.
- [x] `test_workflow_missing_slots_halts_at_slot_collection`: Invoking `WorkflowAction.BOOK` without `date` or `doctor_name` halts at `WorkflowState.SLOT_COLLECTION` (`success=False`, `error_class="missing_or_invalid_slot"`) with a clear Arabic prompt and zero database writes.

### Tier 4: Regression Checks
- **Scope**: Existing Phase 1–4 test suites must pass without regression after integrating `gates.py`, `workflow.py`, and session-scoped schemas.
- [x] `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_doctor_availability.py`, `tests/test_clinic_tools.py`: Verify all Phase 3 medical tool tests (including direct duplicate booking returning `error="duplicate_booking"`) pass 100%.
- [x] `tests/test_database.py`: Verify database models, seeder, and concurrency tests pass.
- [x] `tests/test_guardrails.py`, `tests/test_hybrid_rag.py`, `tests/test_cache_ladder.py`, `tests/test_model_gateway.py`, `tests/test_circuit_breaker.py`: Verify all Phase 4 AI Core tests pass.

### Tier 5: Build, Lint & Type Checks
- [x] **Lint Check**:
  ```powershell
  uv run ruff check src/tools/gates.py src/ai_core/workflow.py src/tools/schemas.py src/tools/appointment_booking.py src/tools/manage_appointment.py src/tools/__init__.py src/ai_core/__init__.py src/config.py tests/test_workflow_gates.py
  ```
- [x] **Format Check**:
  ```powershell
  uv run ruff format --check src/tools/gates.py src/ai_core/workflow.py tests/test_workflow_gates.py
  ```
- [x] **Import & Public API Check**:
  ```powershell
  uv run python -c "from src.tools.gates import DeterministicWriteGate, IdempotencyStore, CallerSessionContext, caller_session_scope, compute_booking_idempotency_key; from src.ai_core.workflow import AppointmentWorkflowStateMachine, WorkflowState, WorkflowAction; from src.tools import get_session_scoped_tool_definitions"
  ```
- **Type Checking**:
  - **Status**: Not Applicable
  - **Technical Justification**: No static type checker (`mypy` or `pyright`) is installed or configured in `pyproject.toml` (`[project.optional-dependencies].dev` contains only `pytest`, `pytest-asyncio`, and `ruff`).

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: Feature 4.5 is a backend AI Core and tool safety gate layer (`src/ai_core/workflow.py`, `src/tools/gates.py`, `src/tools/schemas.py`) with no Streamlit UI or visual frontend changes.

### Tier 7: API / CLI / Application Checks
- [x] **Live CLI Smoke Verification of Workflow State Machine, Idempotency & Anti-Spoofing**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "import asyncio; from src.tools import get_session_scoped_tool_definitions; defs = get_session_scoped_tool_definitions(); book_def = next(d for d in defs if d['function']['name'] == 'book_appointment'); assert 'patient_phone' not in book_def['function']['parameters']['properties']; print('Session-scoped tool definitions verified successfully:', len(defs))"
  ```

---

## 3. Automated Execution Commands

```powershell
# 1. Run Feature 4.5 Workflow State Machine, Idempotency & Write Safety Gates test suite
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_workflow_gates.py -v

# 2. Run Phase 3 Medical Tools regression suites
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_doctor_availability.py tests/test_clinic_tools.py -v

# 3. Run full Phase 1-4 regression suite
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_database.py tests/test_guardrails.py tests/test_hybrid_rag.py tests/test_cache_ladder.py tests/test_model_gateway.py tests/test_circuit_breaker.py -v

# 4. Run Ruff linter & format checks
uv run ruff check src/tools/gates.py src/ai_core/workflow.py src/tools/schemas.py src/tools/appointment_booking.py src/tools/manage_appointment.py src/tools/__init__.py src/ai_core/__init__.py src/config.py tests/test_workflow_gates.py
uv run ruff format --check src/tools/gates.py src/ai_core/workflow.py tests/test_workflow_gates.py

# 5. Run CLI smoke check for session-scoped tool definitions
$env:PYTHONIOENCODING="utf-8"; uv run python -c "from src.tools import get_session_scoped_tool_definitions; defs = get_session_scoped_tool_definitions(); book_def = next(d for d in defs if d['function']['name'] == 'book_appointment'); assert 'patient_phone' not in book_def['function']['parameters']['properties']; print('OK:', len(defs))"
```
