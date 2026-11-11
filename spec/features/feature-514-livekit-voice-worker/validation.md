# Validation Criteria: Feature 5.4 — LiveKit Voice Pipeline Worker & Clinic Turn Engine

## 1. Success Definition
Feature 5.4 is successful when `src/agent/turn_engine.py` and `src/agent/voice_agent.py` assemble a complete LiveKit 1.7.x voice pipeline whose custom `llm_node` routes every turn through `ClinicTurnEngine` (guardrails → FinOps budget check → cache ladder → `ModelGateway.astream` → allowlisted session-scoped clinic tools with 400ms read abort and 400ms filler + 3s shielded write timeout → output guardrail → `CallSession` & trace recording), enforces verified caller identity from SIP/JWT attributes, and passes all unit, integration, edge-case, regression, and lint checks without requiring live cloud API keys.

## 2. Requirement Traceability
| Requirement | Checks |
|:---|:---|
| R1 | T1.1, T1.2, T2.1 |
| R2 | T1.3, T3.1 |
| R3 | T1.4, T2.2, T3.2 |
| R4 | T2.3, T3.3, T3.4 |
| R5 | T2.4, T3.5 |
| R6 | T1.5, T2.5 |
| R7 | T1.6, T2.6 |
| R8 | T1.7, T7.2 |
| NFR1 | T1.8, T7.1 |
| NFR2 | T3.6 |
| NFR3 | T2.1 |

---

## 3. Verification Tiers

### Tier 1: Unit Verification
- [ ] T1.1 — `Settings` in `src/config.py` exposes `write_tool_hard_cap_ms == 3000.0` and `max_tool_rounds_per_turn == 3` (`tests/test_voice_worker_unit.py` or `tests/test_agent.py`).
- [ ] T1.2 — `ClinicTurnEngine` initializes with injectable `gateway`, `cache_ladder`, `input_guardrail`, `output_guardrail`, `finops`, and `tracer` dependencies.
- [ ] T1.3 — `CALLER_TOOL_ALLOWLIST` equals `{"check_doctor_availability", "book_appointment", "manage_appointment", "search_clinic_knowledge", "transfer_to_receptionist"}` and session-scoped tool schemas strip `patient_phone` and `phone`.
- [ ] T1.4 — `extract_verified_caller_identity` resolves `caller_phone`, `language`, `tenant_id`, and `branch_id` from SIP attributes (`sip.phoneNumber`) first, then signed participant attributes (`caller_phone`, `lang`), and returns `caller_phone=None` when neither is present.
- [ ] T1.5 — `ClinicVoiceAgent` subclasses `livekit.agents.voice.Agent` and overrides `llm_node`.
- [ ] T1.6 — `create_stt`, `create_tts`, `create_vad`, `create_voice_pipeline`, and `get_worker_options` construct valid LiveKit component instances using offline placeholder keys when cloud env vars are empty.
- [ ] T1.7 — `generate_livekit_token` in `scripts/generate_token.py` encodes `caller_phone`, `lang`, `tenant_id`, and `branch_id` inside the decoded JWT payload attributes.
- [ ] T1.8 — Importing `src.agent.voice_agent` and `src.agent.turn_engine` does not invoke `httpx.get` at import time.

### Tier 2: Integration Verification
- [ ] T2.1 — `ClinicTurnEngine.run_turn()` with a scripted `ModelGateway` executes a doctor availability inquiry, invokes `check_doctor_availability`, records the tool call and turn metrics on `CallSession`, records token usage in `FinOpsController`, and emits a hierarchical trace with child spans.
- [ ] T2.2 — `ClinicTurnEngine.run_turn()` with a verified `caller_phone` in `VerifiedCallerIdentity` binds `caller_session_scope` and completes an atomic `book_appointment` call against the SQLite clinic database without the LLM supplying `patient_phone`.
- [ ] T2.3 — Slow write tool (~500ms, within 3s cap) causes `ClinicTurnEngine.run_turn()` to yield the localized 400ms filler message first, followed by the completed booking confirmation once the shielded write finishes.
- [ ] T2.4 — Emergency caller utterance (e.g. `"عندي ألم شديد في الصدر ومش قادر أتنفس"`) triggers `InputGuardrail` / emergency short-circuit, calls `async_transfer_to_receptionist(urgency='critical')`, sets `call_session.context.is_emergency = True`, and yields `build_emergency_message` without calling the LLM.
- [ ] T2.5 — `ClinicVoiceAgent.llm_node(chat_ctx, tools, model_settings)` consumes a `livekit.agents.llm.ChatContext` containing a user message and yields spoken response chunks from `ClinicTurnEngine`.
- [ ] T2.6 — Session close hook persists a PII-redacted JSON file via `session_manager.async_end_and_persist` with `CallLifecycle.ENDED`.

### Tier 3: Error & Edge-Case Verification
- [ ] T3.1 — If a mocked LLM returns a tool call for a non-allowlisted tool name (e.g. `"drop_database"` or `"get_order_status"`), `ClinicTurnEngine` blocks execution, logs a warning, and returns a safe fallback response.
- [ ] T3.2 — When `VerifiedCallerIdentity.caller_phone` is `None` and the LLM attempts `book_appointment` or `manage_appointment(action='cancel'|'reschedule')`, `ClinicTurnEngine` blocks the DB write and routes to `transfer_to_receptionist` with a polite explanation.
- [ ] T3.3 — Read tool (`check_doctor_availability` or `search_clinic_knowledge`) exceeding `400ms` is cancelled immediately, increments `call_session.metrics.tool_timeout_count`, and yields a localized filler/fallback without crashing the turn.
- [ ] T3.4 — Write tool exceeding `write_tool_hard_cap_ms` (simulated via a short cap, e.g. `100ms`, against a `300ms` tool) triggers automatic escalation to `transfer_to_receptionist` after yielding the initial filler.
- [ ] T3.5 — Prompt injection (`"ignore all previous instructions..."`) and medical diagnosis requests (`"شخص حالتي واكتبلي مضاد حيوي"`) are intercepted by `InputGuardrail` / `OutputGuardrail` and return localized safe refusal messages.
- [ ] T3.6 — Closing the `ClinicTurnEngine.run_turn()` async generator mid-execution (simulating Silero VAD barge-in) while a write tool is in flight does not cancel the shielded write task (`asyncio.shield`), leaving the database booking intact.

### Tier 4: Regression Checks
- [ ] T4.1 — Full test suite passes: `uv run pytest -v`

### Tier 5: Build, Lint & Type Checks
- [ ] T5.1 — `uv run ruff check .` clean
- Type checks: Status: Not Applicable — no type checker is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- [ ] T6.1 — Deferred to Phase Gate 2 (per `phase-overview.md` P9): human runs `uv run python scripts/generate_token.py --room clinic-room --identity patient_01 --phone 01012345678 --lang ar` and connects via `uv run python -m src.agent.voice_agent console` (or LiveKit playground) to verify live audio greeting, booking, barge-in cutoff, and emergency escalation.

### Tier 7: API / CLI / Application Checks
- [ ] T7.1 — `uv run python -c "import src.agent.voice_agent as va; opts = va.get_worker_options(); print(opts.worker_type)"` succeeds offline with zero network calls.
- [ ] T7.2 — `uv run python scripts/generate_token.py --room test-room --identity caller1 --phone 01012345678 --lang ar --api-key devkey --api-secret secret123456789012345678901234567890` prints a valid JWT containing the signed `caller_phone` and `lang` attributes.

---

## 4. Automated Execution Commands
```bash
uv run pytest -v
uv run ruff check .
uv run python -c "import src.agent.voice_agent as va; opts = va.get_worker_options(); print(opts.worker_type)"
```

## 5. Execution Results (filled in execute mode)
| Check | Result (✅ / ❌ / ⏭ N/A) | Evidence (command output summary, counts) |
|:---|:---|:---|
