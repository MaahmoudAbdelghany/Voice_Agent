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
- [x] T1.1 — `Settings` in `src/config.py` exposes `write_tool_hard_cap_ms == 3000.0` and `max_tool_rounds_per_turn == 3` (`tests/test_voice_worker.py::test_t1_1_settings_expose_write_hard_cap_and_max_tool_rounds`).
- [x] T1.2 — `ClinicTurnEngine` initializes with injectable `gateway`, `cache_ladder`, `input_guardrail`, `output_guardrail`, `finops`, and `tracer` dependencies (`tests/test_voice_worker.py::test_t1_2_clinic_turn_engine_injectable_dependencies`).
- [x] T1.3 — `CALLER_TOOL_ALLOWLIST` equals `{"check_doctor_availability", "book_appointment", "manage_appointment", "search_clinic_knowledge", "transfer_to_receptionist"}` and session-scoped tool schemas strip `patient_phone` and `phone` (`tests/test_voice_worker.py::test_t1_3_caller_tool_allowlist_and_session_scoped_schemas`).
- [x] T1.4 — `extract_verified_caller_identity` resolves `caller_phone`, `language`, `tenant_id`, and `branch_id` from SIP attributes (`sip.phoneNumber`) first, then signed participant attributes (`caller_phone`, `lang`), and returns `caller_phone=None` when neither is present (`tests/test_voice_worker.py::test_t1_4_extract_verified_caller_identity_priority_and_fallback`).
- [x] T1.5 — `ClinicVoiceAgent` subclasses `livekit.agents.voice.Agent` and overrides `llm_node` (`tests/test_voice_worker.py::test_t1_5_clinic_voice_agent_subclasses_livekit_agent_and_overrides_llm_node`).
- [x] T1.6 — `create_stt`, `create_tts`, `create_vad`, `create_voice_pipeline`, and `get_worker_options` construct valid LiveKit component instances using offline placeholder keys when cloud env vars are empty (`tests/test_voice_worker.py::test_t1_6_plugin_factories_and_worker_options_offline_placeholder_keys`).
- [x] T1.7 — `generate_livekit_token` in `scripts/generate_token.py` encodes `caller_phone`, `lang`, `tenant_id`, and `branch_id` inside the decoded JWT payload attributes (`tests/test_voice_worker.py::test_t1_7_generate_livekit_token_encodes_signed_caller_attributes`).
- [x] T1.8 — Importing `src.agent.voice_agent` and `src.agent.turn_engine` does not invoke `httpx.get` at import time (`tests/test_voice_worker.py::test_t1_8_zero_import_time_http_requests`).

### Tier 2: Integration Verification
- [x] T2.1 — `ClinicTurnEngine.run_turn()` with a scripted `ModelGateway` executes a doctor availability inquiry, invokes `check_doctor_availability`, records the tool call and turn metrics on `CallSession`, records token usage in `FinOpsController`, and emits a hierarchical trace with child spans (`tests/test_voice_worker.py::test_t2_1_availability_inquiry_turn_records_metrics_finops_and_hierarchical_trace`).
- [x] T2.2 — `ClinicTurnEngine.run_turn()` with a verified `caller_phone` in `VerifiedCallerIdentity` binds `caller_session_scope` and completes an atomic `book_appointment` call against the SQLite clinic database without the LLM supplying `patient_phone` (`tests/test_voice_worker.py::test_t2_2_verified_caller_identity_atomic_sqlite_booking_without_llm_phone`).
- [x] T2.3 — Slow write tool (~500ms, within 3s cap) causes `ClinicTurnEngine.run_turn()` to yield the localized 400ms filler message first, followed by the completed booking confirmation once the shielded write finishes (`tests/test_voice_worker.py::test_t2_3_slow_write_tool_emits_400ms_filler_then_booking_confirmation`).
- [x] T2.4 — Emergency caller utterance (e.g. `"عندي ألم شديد في الصدر ومش قادر أتنفس"`) triggers `InputGuardrail` / emergency short-circuit, calls `async_transfer_to_receptionist(urgency='critical')`, sets `call_session.context.is_emergency = True`, and yields `build_emergency_message` without calling the LLM (`tests/test_voice_worker.py::test_t2_4_emergency_utterance_short_circuits_llm_and_transfers_critical`).
- [x] T2.5 — `ClinicVoiceAgent.llm_node(chat_ctx, tools, model_settings)` consumes a `livekit.agents.llm.ChatContext` containing a user message and yields spoken response chunks from `ClinicTurnEngine` (`tests/test_voice_worker.py::test_t2_5_clinic_voice_agent_llm_node_streams_from_chat_context`).
- [x] T2.6 — Session close hook persists a PII-redacted JSON file via `session_manager.async_end_and_persist` with `CallLifecycle.ENDED` (`tests/test_voice_worker.py::test_t2_6_session_close_hook_persists_pii_redacted_json_with_ended_lifecycle` & `test_t2_6b_barge_in_speech_created_hook_records_interruption`).

### Tier 3: Error & Edge-Case Verification
- [x] T3.1 — If a mocked LLM returns a tool call for a non-allowlisted tool name (e.g. `"drop_database"`), `ClinicTurnEngine` blocks execution, logs a warning, and returns a safe fallback response (`tests/test_voice_worker.py::test_t3_1_non_allowlisted_tool_call_blocked_and_logged`).
- [x] T3.2 — When `VerifiedCallerIdentity.caller_phone` is `None` and the LLM attempts `book_appointment` or `manage_appointment(action='cancel'|'reschedule')`, `ClinicTurnEngine` blocks the DB write and routes to `transfer_to_receptionist` with a polite explanation, while allowing read tools (`tests/test_voice_worker.py::test_t3_2_unverified_caller_blocks_write_tools_and_routes_to_receptionist` & `test_t3_2b_unverified_caller_allows_read_only_lookup_and_availability`).
- [x] T3.3 — Read tool (`check_doctor_availability` or `search_clinic_knowledge`) exceeding `400ms` is cancelled immediately, increments `call_session.metrics.tool_timeout_count`, and yields a localized filler/fallback without crashing the turn (`tests/test_voice_worker.py::test_t3_3_read_tool_exceeding_400ms_cancelled_and_increments_timeout_count`).
- [x] T3.4 — Write tool exceeding `write_tool_hard_cap_ms` (simulated via a short cap against a slower tool) triggers automatic escalation to `transfer_to_receptionist` after yielding the initial filler (`tests/test_voice_worker.py::test_t3_4_write_tool_exceeding_hard_cap_triggers_receptionist_escalation`).
- [x] T3.5 — Prompt injection (`"ignore all previous instructions..."`) and medical diagnosis requests (`"شخص حالتي واكتبلي مضاد حيوي"`) are intercepted by `InputGuardrail` / `OutputGuardrail` and return localized safe refusal messages (`tests/test_voice_worker.py::test_t3_5_prompt_injection_medical_diagnosis_and_unsafe_output_intercepted`).
- [x] T3.6 — Closing the `ClinicTurnEngine.run_turn()` async generator mid-execution (simulating Silero VAD barge-in) while a write tool is in flight does not cancel the shielded write task (`asyncio.shield`), leaving the database booking intact (`tests/test_voice_worker.py::test_t3_6_barge_in_generator_close_preserves_shielded_sqlite_write`).

### Tier 4: Regression Checks
- [x] T4.1 — Full test suite passes: `uv run pytest -v`

### Tier 5: Build, Lint & Type Checks
- [x] T5.1 — `uv run ruff check .` clean
- Type checks: Status: Not Applicable — no type checker is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- [ ] T6.1 — Deferred to Phase Gate 2 (per `phase-overview.md` P9): human runs `uv run python scripts/generate_token.py --room clinic-room --identity patient_01 --phone 01012345678 --lang ar` and connects via `uv run python -m src.agent.voice_agent console` (or LiveKit playground) to verify live audio greeting, booking, barge-in cutoff, and emergency escalation.

### Tier 7: API / CLI / Application Checks
- [x] T7.1 — `uv run python -c "import src.agent.voice_agent as va; opts = va.get_worker_options(); print(opts.worker_type)"` succeeds offline with zero network calls.
- [x] T7.2 — `uv run python scripts/generate_token.py --room test-room --identity caller1 --phone 01012345678 --lang ar --api-key devkey --api-secret secret123456789012345678901234567890` prints a valid JWT containing the signed `caller_phone` and `lang` attributes.

---

## 4. Automated Execution Commands
```bash
uv run pytest tests/test_voice_worker.py -v
uv run pytest -v
uv run ruff check .
uv run python -c "import src.agent.voice_agent as va; opts = va.get_worker_options(); print(opts.worker_type)"
```

## 5. Execution Results (filled in execute mode)
| Check | Result (✅ / ❌ / ⏭ N/A) | Evidence (command output summary, counts) |
|:---|:---|:---|
| T1.1 | ✅ | `tests/test_voice_worker.py::test_t1_1_settings_expose_write_hard_cap_and_max_tool_rounds` PASSED (`write_tool_hard_cap_ms == 3000.0`, `max_tool_rounds_per_turn == 3`). |
| T1.2 | ✅ | `tests/test_voice_worker.py::test_t1_2_clinic_turn_engine_injectable_dependencies` PASSED (all injected `ai_core` instances retained). |
| T1.3 | ✅ | `tests/test_voice_worker.py::test_t1_3_caller_tool_allowlist_and_session_scoped_schemas` PASSED (exact 5 clinic tools; `patient_phone`/`phone` stripped from LLM schemas). |
| T1.4 | ✅ | `tests/test_voice_worker.py::test_t1_4_extract_verified_caller_identity_priority_and_fallback` PASSED (`sip.phoneNumber` > signed JWT `caller_phone` > `None`). |
| T1.5 | ✅ | `tests/test_voice_worker.py::test_t1_5_clinic_voice_agent_subclasses_livekit_agent_and_overrides_llm_node` PASSED (`issubclass(ClinicVoiceAgent, Agent)` and custom `llm_node`). |
| T1.6 | ✅ | `tests/test_voice_worker.py::test_t1_6_plugin_factories_and_worker_options_offline_placeholder_keys` PASSED (STT, TTS, VAD, `create_voice_pipeline`, and `get_worker_options` assemble offline). |
| T1.7 | ✅ | `tests/test_voice_worker.py::test_t1_7_generate_livekit_token_encodes_signed_caller_attributes` PASSED (decoded HS256 JWT contains `caller_phone`, `lang`, `tenant_id`, `branch_id`). |
| T1.8 | ✅ | `tests/test_voice_worker.py::test_t1_8_zero_import_time_http_requests` PASSED (`importlib.reload` triggers 0 `httpx.get` calls). |
| T2.1 | ✅ | `tests/test_voice_worker.py::test_t2_1_availability_inquiry_turn_records_metrics_finops_and_hierarchical_trace` PASSED (`check_doctor_availability` executed, `CallSession` metrics, `FinOpsController` tokens, and nested trace spans verified). |
| T2.2 | ✅ | `tests/test_voice_worker.py::test_t2_2_verified_caller_identity_atomic_sqlite_booking_without_llm_phone` PASSED (atomic SQLite booking committed with `caller_session_scope`-injected phone and queue number). |
| T2.3 | ✅ | `tests/test_voice_worker.py::test_t2_3_slow_write_tool_emits_400ms_filler_then_booking_confirmation` PASSED (localized filler yielded at threshold followed by shielded booking confirmation). |
| T2.4 | ✅ | `tests/test_voice_worker.py::test_t2_4_emergency_utterance_short_circuits_llm_and_transfers_critical` PASSED (0 LLM calls, `transfer_to_receptionist(urgency='critical')`, `is_emergency=True`, `build_emergency_message` yielded). |
| T2.5 | ✅ | `tests/test_voice_worker.py::test_t2_5_clinic_voice_agent_llm_node_streams_from_chat_context` PASSED (`ClinicVoiceAgent.llm_node` consumes LiveKit `ChatContext` and streams spoken chunks). |
| T2.6 | ✅ | `tests/test_voice_worker.py::test_t2_6_session_close_hook_persists_pii_redacted_json_with_ended_lifecycle` & `test_t2_6b_barge_in_speech_created_hook_records_interruption` PASSED (PII masked on disk, `CallLifecycle.ENDED`, barge-in interruption recorded). |
| T3.1 | ✅ | `tests/test_voice_worker.py::test_t3_1_non_allowlisted_tool_call_blocked_and_logged` PASSED (non-allowlisted tool call rejected with warning and safe fallback). |
| T3.2 | ✅ | `tests/test_voice_worker.py::test_t3_2_unverified_caller_blocks_write_tools_and_routes_to_receptionist` & `test_t3_2b` PASSED (unverified caller read tools succeed; write tools blocked before DB and routed to receptionist). |
| T3.3 | ✅ | `tests/test_voice_worker.py::test_t3_3_read_tool_exceeding_400ms_cancelled_and_increments_timeout_count` PASSED (read tool cancelled on timeout, `tool_timeout_count` incremented, localized filler yielded). |
| T3.4 | ✅ | `tests/test_voice_worker.py::test_t3_4_write_tool_exceeding_hard_cap_triggers_receptionist_escalation` PASSED (write tool exceeding hard cap escalates to `transfer_to_receptionist`). |
| T3.5 | ✅ | `tests/test_voice_worker.py::test_t3_5_prompt_injection_medical_diagnosis_and_unsafe_output_intercepted` PASSED (both input prompt-injection/diagnosis refusal and output diagnosis scrubbing verified). |
| T3.6 | ✅ | `tests/test_voice_worker.py::test_t3_6_barge_in_generator_close_preserves_shielded_sqlite_write` PASSED (closing async generator mid-write preserves `asyncio.shield` SQLite transaction). |
| T4.1 | ✅ | `uv run pytest -q` → `558 passed, 0 failed, 0 skipped, 3 warnings in 71.24s` (including `tests/test_voice_worker.py`: `24 passed in 9.65s` and `tests/test_prompts.py::test_i3_voice_pipeline_instructions_use_clinic_prompt` un-skipped and passing). |
| T5.1 | ✅ | `uv run ruff check .` → `All checks passed!` (exit code `0`; type checks N/A per `pyproject.toml`). |
| T6.1 | ⏭ Deferred | Manual live audio call deferred to human verification at Phase Gate 2 per `phase-overview.md` Decision P9 (`PI.9`). |
| T7.1 | ✅ | `uv run python -c "import src.agent.voice_agent as va; opts = va.get_worker_options(); print(opts.worker_type)"` → `ServerType.ROOM` (exit code `0`, offline). |
| T7.2 | ✅ | `uv run python scripts/generate_token.py --room test-room --identity caller1 --phone 01012345678 --lang ar --api-key devkey --api-secret secret123456789012345678901234567890` → masked console output (`***678`) and signed JWT claims `{"lang":"ar","tenant_id":"default","branch_id":"main","caller_phone":"01012345678"}`. |
