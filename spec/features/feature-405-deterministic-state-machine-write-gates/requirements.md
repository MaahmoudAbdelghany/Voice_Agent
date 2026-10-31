# Requirements Specification: Feature 4.5 — Deterministic State Machine, Idempotency Keys & Write Safety Gates

> Traces to parent requirements R8, R9, R10 in `spec/features/feature-400-enterprise-ai-architecture-and-resilience/requirements.md` and Architectural Invariants 1, 2, 5, 7, 9, and 10 in `spec/tech.md`.

---

## 1. Functional Requirements

### R1: Session-Injected Caller Identity & Anti-Spoofing (`src/tools/gates.py`, `src/tools/schemas.py`, `src/tools/__init__.py`)
- **R1.1 (`contextvars`-Isolated Caller Session Context)**: `src/tools/gates.py` must provide `CallerSessionContext` (containing `caller_phone: str`, `session_id: str | None`, `caller_name: str | None`, `tenant_id: str`, `branch_id: str`), a context manager `caller_session_scope(...)`, and `get_current_caller_session()` using Python `contextvars.ContextVar` so concurrent async voice calls are strictly isolated.
- **R1.2 (Dual-Mode Server-Side Phone Resolution & Spoofing Prevention)**: `resolve_effective_caller_phone(explicit_phone: str | None)` must resolve the caller's phone number deterministically:
  1. When `caller_session_scope` is active (and `settings.enforce_session_caller_identity` is `True`), the verified session `caller_phone` is forcibly injected as the effective phone. If `explicit_phone` was also supplied and differs from the normalized session `caller_phone`, the override must be flagged (`spoof_attempt_blocked=True`) and logged as a security warning without exposing raw phone numbers in logs.
  2. When no `CallerSessionContext` is active in `contextvars` (e.g., standalone CLI scripts or Phase 3 unit/integration tests), `resolve_effective_caller_phone()` falls back to the normalized `explicit_phone` argument.
- **R1.3 (Session-Scoped LLM Tool Schemas)**: `src/tools/schemas.py` must define `LLMAppointmentBookingInput` and `LLMManageAppointmentInput` with `ConfigDict(extra="forbid")` that completely omit caller identity fields (`patient_phone`, `phone`, `patient_id`). Any attempt by an LLM payload to supply `patient_phone`, `phone`, or `patient_id` against these schemas must be rejected by Pydantic validation.
- **R1.4 (Session-Scoped Tool Definitions Export)**: `src/tools/__init__.py` must expose `get_session_scoped_tool_definitions()` returning OpenAI/Groq function-calling tool definitions where `book_appointment` uses `LLMAppointmentBookingInput` and `manage_appointment` uses `LLMManageAppointmentInput`, while preserving `get_tool_definitions()` for backward compatibility.

### R2: Deterministic Write Safety Gates (`DeterministicWriteGate` in `src/tools/gates.py`)
- **R2.1 (Pre-Write Booking Invariants)**: Before any appointment row is written, `DeterministicWriteGate.verify_booking()` must validate all 5 clinic business invariants in deterministic Python code:
  1. **Active Doctor**: Target doctor exists and `is_active` is `True`.
  2. **Cairo Date Window**: `target_date >= cairo_today` and `target_date <= cairo_today + 30 days`.
  3. **Active Shift Existence**: Doctor has an active `DoctorSchedule` on `target_date` (`has_shift == True`) and, if `target_date == cairo_today`, the shift has not already ended (`cairo_now_time < shift_end`).
  4. **Strict Shift Capacity Gate**: Current confirmed bookings on `(doctor_id, target_date)` strictly satisfy `booked_count < max_capacity` (`remaining_capacity >= 1`).
  5. **Consultation 14-Day Eligibility**: If `visit_type == VisitType.CONSULTATION`, verify whether the patient had a non-cancelled `EXAMINATION` with the same doctor within the preceding 14 days; if not, deterministically downgrade `effective_visit_type` to `VisitType.EXAMINATION` (`visit_type_downgraded=True`).
- **R2.2 (Pre-Write Cancellation & Reschedule Invariants)**: Before cancelling or rescheduling an appointment, `DeterministicWriteGate.verify_cancellation()` and `DeterministicWriteGate.verify_reschedule()` must verify in Python code:
  1. Target appointment exists and is currently in `CONFIRMED` status.
  2. **Caller Ownership Verification**: When an effective caller phone is present (from `CallerSessionContext` or explicit parameter), it matches the appointment owner's normalized phone (`clean_egyptian_phone(appt.patient.phone)`). Mismatches must be rejected (`error_code="phone_mismatch"`).
  3. **Shift Start Gate**: Appointment date is not in the past and, if scheduled for today, the doctor's shift has not already started (`cairo_now_time < schedule.start_time`).
  4. **Reschedule Target Gate**: For `reschedule`, the new target date differs from the current appointment date (`error_code="same_date"` if identical) and passes all shift existence, Cairo window, non-duplicate, and strict capacity (`booked_count < max_capacity`) checks for the same doctor.
- **R2.3 (Structured `GateVerdict` & 7-Day Nearest Slot Fallback)**: Every gate evaluation must return a typed `GateVerdict` (`allowed: bool`, `action: str`, `error_code: str | None`, `message_ar: str | None`, `doctor_id: int | None`, `schedule_id: int | None`, `target_date: str | None`, `remaining_capacity: int`, `max_capacity: int`, `effective_visit_type: str | None`, `visit_type_downgraded: bool`, `spoof_attempt_blocked: bool`, `next_available: dict[str, Any] | None`, `latency_ms: float`). When a booking or reschedule is rejected due to `no_shift`, `shift_ended`, or `shift_full`, the gate must scan up to 7 days ahead and populate `next_available` and a polite Egyptian Arabic suggestion without mutating database state.

### R3: Deterministic Booking Idempotency (`IdempotencyStore` in `src/tools/gates.py`)
- **R3.1 (Deterministic SHA-256 Key Formula)**: `compute_booking_idempotency_key(patient_phone, doctor_id, schedule_id, appointment_date)` must normalize `patient_phone` via `clean_egyptian_phone()` and compute a lowercase hex SHA-256 digest over the canonical string `f"book:{clean_phone}:{doctor_id}:{schedule_id}:{appointment_date.isoformat()}"`. Similarly, `compute_reschedule_idempotency_key(booking_code, new_date)` must hash `f"reschedule:{booking_code.strip().upper()}:{new_date.isoformat()}"`.
- **R3.2 (24-Hour TTL Store & Live DB Confirmation Cross-Check)**: `IdempotencyStore` must maintain idempotency records with a configurable TTL (`settings.idempotency_ttl_s`, default `86400` seconds = 24 hours) and max capacity (`settings.idempotency_max_entries`, default `5000` with LRU eviction). When a duplicate booking request arrives with an active idempotency key via `AppointmentWorkflowStateMachine` or `DeterministicWriteGate.execute_booking()`, the system must verify that the stored `booking_code` is still `CONFIRMED` in the database and return the existing confirmed booking details (`success=True`, `idempotent_replay=True`, `idempotency_key=key`, identical `booking_code` and `queue_number`) without incrementing queue numbers or inserting duplicate rows.
- **R3.3 (Automatic Invalidation on Cancellation or Rescheduling)**: When an appointment is cancelled or rescheduled (via `ManageAppointmentTool` or `AppointmentWorkflowStateMachine`), its booking idempotency key must be invalidated in `IdempotencyStore` so the patient can legitimately re-book the same doctor and shift date later if desired.
- **R3.4 (Phase 3 Direct Tool Backward Compatibility)**: Direct invocations of `AppointmentBookingTool.aexecute()` must continue returning `ToolResult(success=False, error="duplicate_booking")` when a duplicate confirmed booking exists on the same date (preserving 100% compatibility with Phase 3 test suites), while enriching `ToolResult.data` with `idempotency_key` and `spoof_attempt_blocked`.

### R4: Deterministic Workflow State Machine (`AppointmentWorkflowStateMachine` in `src/ai_core/workflow.py`)
- **R4.1 (Explicit Finite States & Supported Actions)**: `AppointmentWorkflowStateMachine` must govern appointment operations (`WorkflowAction.BOOK`, `WorkflowAction.CANCEL`, `WorkflowAction.RESCHEDULE`, `WorkflowAction.LOOKUP`) through explicit finite states (`WorkflowState`: `INIT`, `SLOT_COLLECTION`, `PRECONDITION_GATE`, `IDEMPOTENCY_CHECK`, `ATOMIC_EXECUTION`, `COMPLETED`, `REJECTED_BY_GATE`, `ESCALATED`).
- **R4.2 (Step-Budget Enforcement — $0.95^{10}$ Reliability Law)**: Every state transition must increment a step counter and append a `WorkflowStepTrace` (`step_index`, `from_state`, `to_state`, `duration_ms`, `detail`). If a workflow execution exceeds `max_steps` (default `settings.workflow_max_steps = 6`), the state machine must immediately abort execution, transition to `WorkflowState.ESCALATED`, and return `WorkflowExecutionResult(success=False, terminal_state=WorkflowState.ESCALATED, error_class="step_budget_exhausted", escalate=True)` with a polite Egyptian Arabic receptionist handoff message.
- **R4.3 (Missing Slot Collection Without DB Touch)**: During `WorkflowState.SLOT_COLLECTION`, if required parameters are missing or invalid (e.g., missing doctor/date/patient name for `BOOK`, missing `booking_code` and no session phone for `CANCEL`/`LOOKUP`, or missing `booking_code`/`new_date` for `RESCHEDULE`), the workflow must return a voice-friendly Arabic prompt asking for the missing slot without executing database writes.
- **R4.4 (End-to-End Deterministic Execution Envelope)**: `AppointmentWorkflowStateMachine.execute()` must return a structured `WorkflowExecutionResult` containing `success`, `action`, `terminal_state`, `tool_result`, `idempotency_key`, `idempotent_replay`, `gate_verdict`, `spoof_attempt_blocked`, `escalate`, `error_class`, `steps_taken`, `step_traces`, and `total_latency_ms`.

---

## 2. Non-Functional Requirements

- **NFR1 (Gate & Idempotency Overhead Budget)**: In-memory idempotency lookup, SHA-256 key generation, and session phone resolution must execute in **< 2ms** CPU; full `DeterministicWriteGate` verification (including local SQLite availability query) must complete well within the **< 400ms** tool execution timeout (`spec/tech.md` Invariant 1).
- **NFR2 (100% Concurrency & Atomic Queue Integrity)**: Under concurrent booking requests for the final remaining slot(s) of a doctor's shift, `DeterministicWriteGate` + `ClinicRepository._get_shift_lock()` must guarantee that `booked_count` never exceeds `max_capacity`, assigned queue numbers are strictly sequential without gaps or duplicates, and excess callers receive `shift_full` with a 7-day `next_available` suggestion.
- **NFR3 (Zero Raw PII in Logs)**: Neither `DeterministicWriteGate` nor `AppointmentWorkflowStateMachine` may log raw patient phone numbers or national IDs when recording gate rejections or spoofing attempts.
- **NFR4 (Offline Deterministic Testability)**: All unit, integration, concurrency, idempotency, and spoofing-prevention tests in `tests/test_workflow_gates.py` must run 100% offline using an isolated async SQLite database without external network calls.

---

## 3. Constraints

- **C1 (Backward Compatibility with Phase 1–4 Suites)**: Existing tests in `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_clinic_tools.py`, `tests/test_database.py`, and `tests/test_guardrails.py` must pass without modification.
- **C2 (Code > Prompts)**: Shift capacity limits, consultation 14-day windows, phone ownership checks, and idempotency replay must be enforced in deterministic Python code (`src/tools/gates.py` and `src/ai_core/workflow.py`), never delegated solely to system prompts.
- **C3 (Centralized Configuration)**: All idempotency and workflow thresholds (`idempotency_ttl_s`, `idempotency_max_entries`, `workflow_max_steps`, `enforce_session_caller_identity`) must reside in `src/config.py`.
