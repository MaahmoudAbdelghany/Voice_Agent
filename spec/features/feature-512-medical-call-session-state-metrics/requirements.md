# Feature 5.2 — Medical Call Session State & Metric Tracking (Requirements)

## Functional Requirements

### R1 — Clinic Call Context
- **R1.1** `ClinicCallContext` exposes: `patient_name`, `patient_phone`, `language`, `requested_specialty`, `requested_doctor_id`, `requested_doctor_name`, `requested_date`, `visit_type`, `bookings`, `escalation`, `emergency_flag`, `current_intent`, `sentiment`.
- **R1.2** `patient_phone` is populated **only** from the verified `caller_session_scope` (or explicit `create_session(customer_phone=...)` by the worker), never from LLM tool arguments.
- **R1.3** Legacy restaurant fields remain loadable as `Optional` deprecated fields; `ExtractedContext` remains an importable alias.

### R2 — Tool-Driven Context Extraction
- **R2.1** `check_doctor_availability` → sets `requested_specialty`, `requested_doctor_id/name`, `requested_date`.
- **R2.2** `book_appointment` (success) → appends `BookingRef(action="booked", booking_code, queue_number, appointment_date, doctor_name)`, sets `patient_name`, `visit_type`.
- **R2.3** `manage_appointment` cancel/reschedule (success) → appends `BookingRef` with `action="cancelled"`/`"rescheduled"`.
- **R2.4** `transfer_to_receptionist` → fills `escalation` (reason, department, urgency) and transitions lifecycle to `ESCALATED`; `urgency=emergency` also sets `emergency_flag=True`.
- **R2.5** A method `mark_emergency()` sets `emergency_flag` (called when `InputGuardrail` returns `ESCALATE_EMERGENCY`).
- **R2.6** Failed tool results (`success=False`) never mutate booking context.

### R3 — Lifecycle & Activity
- **R3.1** `CallLifecycle`: `INITIATED`, `ACTIVE`, `ESCALATED`, `ENDED`, `FAILED` with an explicit allowed-transition table.
- **R3.2** Invalid transitions (e.g. from `ENDED`) are rejected, logged, and do not raise into the audio pipeline.
- **R3.3** `CallActivity` (`idle`, `listening`, `speaking`, `tool_calling`) is tracked separately and has no effect on lifecycle.
- **R3.4** Legacy status values in old JSON (`speaking`, `listening`, `tool_calling`) load as `ACTIVE` + matching activity.

### R4 — Metrics
- **R4.1** Per-turn latency record: `stt_ms`, `llm_ttft_ms`, `tts_ms`, `tool_ms`, `e2e_ms` (all optional).
- **R4.2** Computed per stage: `p50`, `p95`, `max` (nearest-rank), plus count of turns with `e2e_ms > settings.session_slo_turn_ms`.
- **R4.3** Counters: user/assistant turns, interruptions, tool calls succeeded / failed / timed out (`tool_ms > settings.session_tool_timeout_ms`).
- **R4.4** Tokens and cost are **read** from `FinOpsController.get_session_snapshot(session_id)`, copied into the session at `end_call()`; no independent token counting.
- **R4.5** Active `trace_id` (from tracer) is captured per turn when available; unique IDs are stored on the session.
- **R4.6** `SessionManager.get_aggregated_metrics()` returns calls total/active/escalated/emergency, global P50/P95 e2e, SLO breach ratio, tool failure ratio, total cost.

### R5 — Conversation Memory
- **R5.1** `get_conversation_history()` returns at most `settings.session_history_window` (default 12) non-system messages.
- **R5.2** The window never starts with a `tool` message whose originating `assistant` message was cut.
- **R5.3** `build_context_summary()` produces a short deterministic system message from `ClinicCallContext` (empty when context is empty); no LLM call.

### R6 — Persistence & Memory Management
- **R6.1** Persisted JSON passes context and all message contents/tool args/results through `get_pii_redactor()`; raw phone numbers / national IDs never appear on disk.
- **R6.2** Writes are atomic (temp file + `os.replace`).
- **R6.3** `async_save_session()` performs I/O via `asyncio.to_thread`.
- **R6.4** Auto-save on `end_call()` and on escalation (via manager helpers `end_and_persist` / `async_end_and_persist`).
- **R6.5** Ended sessions are evicted from memory after successful save when `settings.session_evict_on_end=True`.
- **R6.6** Old JSON files in `data/calls/` still load without error.

## Non-Functional Requirements
- **NFR-1** Any in-memory session operation (add turn, record tool, compute metrics for ≤ 200 turns) < 1ms average.
- **NFR-2** No blocking file I/O on the asyncio event loop in async paths.
- **NFR-3** Thread/async safe for 50 concurrent sessions (no lost updates in registry).
- **NFR-4** All thresholds in `src/config.py` (tech.md Invariant 8).
- **NFR-5** Session code never raises into the voice pipeline for bad input; it logs and degrades.

## Constraints
- **C1** Do not change the public signatures used by `voice_agent.py`, `scripts/test_call.py`, and dashboard modules unless required to keep them working (additive only).
- **C2** No new third-party dependencies.
- **C3** No DB schema changes.
- **C4** Do not use `phone`/`call_id` as metric labels (prep for 6.1) — metrics stay per-session objects.
- **C5** Do not implement new emergency detection; reuse guardrails/handoff.
- **C6** Do not delete legacy fields in this feature.
