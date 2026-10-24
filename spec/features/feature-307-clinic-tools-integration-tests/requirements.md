# Requirements: Feature 3.7 — Automated Unit & Integration Tests for Medical Tools

## 1. Functional Requirements

### Registry Contract
- **R1**: The suite must verify that `TOOL_REGISTRY` contains exactly these clinic tools: `check_doctor_availability`, `book_appointment`, `manage_appointment`, `search_clinic_knowledge`, `transfer_to_receptionist`, each bound to its Feature 3.1 input/output schema.
- **R2**: For each clinic tool, `get_tool_definitions()` must yield a valid OpenAI/Groq function definition (`type=function`, `parameters.type=object`, `properties` non-empty, `required` ⊆ `properties`).
- **R3**: Internal-only parameters (`session_id`, `session_factory`, `timeout_s`) must not appear in any LLM-facing schema.
- **R4**: Registry `sync_callable` / `async_callable` must route to the module singletons (so rebinding a singleton's `session_factory` changes the DB used by the dispatcher).

### End-to-End Patient Journeys (through `async_execute_tool`)
- **R5 — Booking journey**: availability → booking → lookup must succeed in sequence using only data returned by previous steps (doctor ID/name, booking code, phone).
- **R6 — Reschedule journey**: rescheduling a booking created by `book_appointment` produces a new confirmed booking on the new date with the same doctor & visit type; the old booking becomes cancelled.
- **R7 — Cancel journey**: cancelling a booking created by `book_appointment` marks it cancelled and the slot is reflected as free by `check_doctor_availability`.
- **R8 — Capacity journey**: filling a shift to `max_capacity` makes availability report it full; a further booking fails with `success=False` and a next-available suggestion (or reception referral); after one cancellation the same booking succeeds.

### Cross-Tool State Consistency
- **R9**: Remaining slots reported by `check_doctor_availability` must always equal `max_capacity − confirmed bookings` after any sequence of book/cancel/reschedule made through the dispatcher.
- **R10**: A booking code returned by `book_appointment` must be accepted by every `manage_appointment` action; a wrong phone with a valid code must be rejected (privacy).

### Concurrency
- **R11**: N (≥ 5) concurrent `book_appointment` dispatcher calls for a capacity-2 shift must yield exactly 2 successes with distinct queue numbers, N−2 graceful failures, and no unhandled exception.

### Escalation & Safety
- **R12**: An emergency phrase (e.g. "عندي ألم جامد في صدري") sent to `transfer_to_receptionist` via the dispatcher must return `urgency=emergency`, `transfer_requested=True`, the emergency number from settings in the message, and a ticket persisted in the DB (visible via `ClinicRepository.list_open_escalations`).
- **R13**: A booking attempt with no availability in the look-ahead window must produce a message that offers reception transfer (no silent failure).

### Knowledge Search
- **R14**: A clinic fee/preparation question via the dispatcher must return `success=True`, `found=True`, and at least one grounded chunk from `clinic_kb.md`.
- **R15**: A diagnosis/prescription-style question must not yield diagnostic or dosage content; the tool's existing guardrail response is asserted.

### Cross-Cutting Invariants (all 5 clinic tools)
- **R16**: For valid, invalid-typed, and empty argument payloads, both dispatchers must return a `ToolResult` and never raise.
- **R17**: Every `ToolResult.message` must be non-empty and contain Arabic text; `success=False` results must carry a non-empty `error`.
- **R18**: Sync (`execute_tool`) and async (`async_execute_tool`) dispatchers must produce equivalent `success` and `data` keys for the same read-only input.
- **R19**: Captured logs during journeys must not contain the raw caller phone number.

## 2. Non-Functional Requirements
- **NFR-1 Isolation**: each test uses its own temp DB; singleton rebinding is auto-restored (`monkeypatch`); suite order-independent.
- **NFR-2 Determinism**: frozen Cairo clock and in-file seed data; no reliance on real current date or random data.
- **NFR-3 Speed**: whole file runs in < 60s locally (excluding first-time embedding model download).
- **NFR-4 Latency smoke**: each DB-backed dispatcher call on a warm DB completes in < 1.5s (regression guard, not SLA proof).
- **NFR-5 Readability**: tests grouped by section headers, descriptive names, docstrings mapping to R-IDs.
- **NFR-6 Lint**: file passes `ruff check` and `ruff format --check` with project config.

## 3. Constraints
- **C1**: No new dependencies; only `pytest`, `pytest-asyncio`, and existing project modules.
- **C2**: Do not modify or delete existing per-tool test files.
- **C3**: Do not change Feature 3.1 schemas or tool public signatures.
- **C4**: Production code changes only for real defects exposed by tests — minimal and individually reported.
- **C5**: No network calls to external services (Groq, Qdrant Cloud, PostgreSQL, LiveKit).
- **C6**: Legacy restaurant tools are not tested here.
