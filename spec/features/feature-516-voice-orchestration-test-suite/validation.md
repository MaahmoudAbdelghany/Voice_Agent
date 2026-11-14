# Validation Criteria: Feature 5.6 — Automated Voice Orchestration & Guardrail Test Suite

## 1. Success Definition
Feature 5.6 is successful when `tests/test_agent.py` provides comprehensive automated unit, integration, and edge-case coverage for `ClinicVoiceAgent`, `ClinicTurnEngine`, verified caller identity, read/write tool timeouts, barge-in shielding, cache bypass, FinOps degradation, hierarchical tracing, guardrails, and all 6 multi-turn clinic scenarios, and passes alongside the full project test suite, golden evals, and `ruff`.

## 2. Requirement Traceability
| Requirement | Checks |
|:---|:---|
| R1 | T1.1, T1.2, T2.1 |
| R2 | T1.3, T2.2, T3.1 |
| R3 | T2.3, T3.2, T3.3, T3.4 |
| R4 | T2.4, T3.5, T3.6 |
| R5 | T2.5, T2.6, T3.7 |
| R6 | T2.7 |
| NFR1 | T1.1, T4.1 |
| NFR2 | T4.1, T4.2, T5.1 |

---

## 3. Verification Tiers

### Tier 1: Unit Verification
- [x] T1.1 — `tests/test_agent.py::test_voice_component_factories_and_pipeline_assembly` verifies `create_stt`, `create_tts`, `create_vad`, `create_voice_pipeline`, and `get_worker_options` offline.
- [x] T1.2 — `tests/test_agent.py::test_single_call_language_configuration` verifies Arabic default (`ar`) and English (`en`) configuration across STT, greeting, and system prompt.
- [x] T1.3 — `tests/test_agent.py::test_extract_verified_caller_identity_and_jwt_roundtrip` verifies SIP attribute priority, signed JWT attributes from `generate_token.py`, and `caller_phone=None` fallback.

### Tier 2: Integration Verification
- [x] T2.1 — `tests/test_agent.py::test_clinic_voice_agent_llm_node_chat_context` verifies `ClinicVoiceAgent.llm_node` processes `livekit.agents.llm.ChatContext` and streams spoken output chunks.
- [x] T2.2 — `tests/test_agent.py::test_verified_caller_atomic_booking_flow` verifies end-to-end appointment booking with session-injected `caller_phone`, atomic queue number assignment, and `CallSession` booking record.
- [x] T2.3 — `tests/test_agent.py::test_write_tool_slow_filler_and_shielded_commit` verifies a write tool exceeding the 400ms filler threshold emits a localized filler first and then completes the DB booking.
- [x] T2.4 — `tests/test_agent.py::test_emergency_utterance_short_circuit_and_handoff` verifies emergency speech triggers `transfer_to_receptionist(urgency='critical')` and `build_emergency_message` with zero LLM call.
- [x] T2.5 — `tests/test_agent.py::test_cache_hit_on_faq_and_bypass_on_booking` verifies `CacheLadder` caches general FAQ turns and bypasses personal/tool turns.
- [x] T2.6 — `tests/test_agent.py::test_hierarchical_tracing_and_pii_redacted_session_persistence` verifies turn spans are recorded and persisted session JSON masks Egyptian phone numbers and national IDs.
- [x] T2.7 — `tests/test_agent.py::test_all_six_clinic_simulated_scenarios` runs `booking`, `manage`, `knowledge`, `emergency`, `guardrail`, and `unverified-booking` scenarios and asserts all pass.

### Tier 3: Error & Edge-Case Verification
- [x] T3.1 — `tests/test_agent.py::test_unverified_caller_write_blocked_and_escalated` verifies that with `caller_phone=None`, `check_doctor_availability` succeeds while `book_appointment` and `manage_appointment(action='cancel')` are blocked before DB write and routed to `transfer_to_receptionist`.
- [x] T3.2 — `tests/test_agent.py::test_read_tool_timeout_aborts_and_yields_filler` verifies a read tool exceeding the timeout threshold is cancelled, increments `tool_timeout_count`, and yields a localized filler.
- [x] T3.3 — `tests/test_agent.py::test_write_tool_hard_cap_escalates_to_receptionist` verifies a write tool exceeding `write_tool_hard_cap_ms` triggers receptionist escalation.
- [x] T3.4 — `tests/test_agent.py::test_barge_in_mid_write_shields_db_transaction` verifies closing the turn generator mid-write preserves the shielded DB commit and records the interruption on `CallSession`.
- [x] T3.5 — `tests/test_agent.py::test_input_and_output_guardrails_block_injection_and_diagnosis` verifies both input prompt-injection/diagnosis blocking and output medical-diagnosis scrubbing on `ClinicTurnEngine`.
- [x] T3.6 — `tests/test_agent.py::test_unallowed_tool_call_rejected` verifies an LLM attempting to invoke a tool outside `CALLER_TOOL_ALLOWLIST` is blocked safely.
- [x] T3.7 — `tests/test_agent.py::test_finops_budget_exhaustion_degrades_gracefully` verifies `FinOpsController` token budget breach degrades the turn to `SEARCH_ONLY` / `RECEPTIONIST`.

### Tier 4: Regression Checks
- [x] T4.1 — Full test suite passes: `uv run pytest -v`
- [x] T4.2 — Golden evaluation suite passes: `uv run pytest tests/evals/test_golden_evals.py -v`

### Tier 5: Build, Lint & Type Checks
- [x] T5.1 — `uv run ruff check .` clean
- Type checks: Status: Not Applicable — no type checker is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- [ ] T6.1 — Covered by Phase Gate 2 manual live voice call (`phase-overview.md` PI.9).

### Tier 7: API / CLI / Application Checks
- [x] T7.1 — `uv run pytest tests/test_agent.py -v` runs and passes all voice orchestration tests.

---

## 4. Automated Execution Commands
```bash
uv run pytest tests/test_agent.py -v
uv run pytest tests/evals/test_golden_evals.py -v
uv run pytest -v
uv run ruff check .
```

## 5. Execution Results (filled in execute mode)
| Check | Result (✅ / ❌ / ⏭ N/A) | Evidence (command output summary, counts) |
|:---|:---|:---|
| T1.1 | ✅ | `tests/test_agent.py::test_voice_component_factories_and_pipeline_assembly PASSED` — verified offline `create_stt`, `create_tts`, `create_vad`, `create_voice_pipeline`, `get_worker_options`, `GatewayBackedLLM` sentinel, 5-tool allowlist with phone-stripped schemas, and zero import-time HTTP calls. |
| T1.2 | ✅ | `tests/test_agent.py::test_single_call_language_configuration PASSED` — verified `ar` default and `en` override across Deepgram STT, greeting message, system prompt, and `create_voice_pipeline`. |
| T1.3 | ✅ | `tests/test_agent.py::test_extract_verified_caller_identity_and_jwt_roundtrip PASSED` — verified SIP `sip.phoneNumber` priority, HS256 JWT round-trip from `scripts/generate_token.py`, and `caller_phone=None` unverified fallback. |
| T2.1 | ✅ | `tests/test_agent.py::test_clinic_voice_agent_llm_node_chat_context PASSED` — verified `ClinicVoiceAgent.llm_node` bridges `ChatContext` -> `<caller_utterance>` XML -> `ClinicTurnEngine` -> streaming spoken chunks, STT latency handoff, and FinOps token ledger. |
| T2.2 | ✅ | `tests/test_agent.py::test_verified_caller_atomic_booking_flow PASSED` — verified 2-turn availability + booking flow with session-bound `caller_phone` overriding rogue LLM phone args, atomic `queue_number=1` in SQLite, and `CallSession` booking context. |
| T2.3 | ✅ | `tests/test_agent.py::test_write_tool_slow_filler_and_shielded_commit PASSED` — verified slow write tool emits localized Arabic filler first and completes shielded SQLite booking (`queue_number=1`). |
| T2.4 | ✅ | `tests/test_agent.py::test_emergency_utterance_short_circuit_and_handoff PASSED` — verified chest-pain/dyspnea utterance makes `0` LLM calls, invokes `transfer_to_receptionist(urgency='critical', department='emergency')`, sets `is_emergency=True` & `CallLifecycle.ESCALATED`, and speaks `build_emergency_message` (`123`). |
| T2.5 | ✅ | `tests/test_agent.py::test_cache_hit_on_faq_and_bypass_on_booking PASSED` — verified `CacheLadder` Tier 1 exact hit on general clinic FAQ (`0` additional LLM calls) and strict bypass on personal (`BypassReason.PERSONAL_QUERY`) and tool/booking turns. |
| T2.6 | ✅ | `tests/test_agent.py::test_hierarchical_tracing_and_pii_redacted_session_persistence PASSED` — verified nested `GUARDRAIL_INPUT`, `LLM`, and `TOOL` spans with valid `parent_span_id`, `trace.pii_redacted=True`, and zero raw Egyptian phone (`01012345678`) or 14-digit National ID (`29501010101234`) in flushed traces or persisted `SessionManager` JSON. |
| T2.7 | ✅ | `tests/test_agent.py::test_all_six_clinic_simulated_scenarios PASSED` — executed all 6 `CLINIC_SCENARIOS` (`booking`, `manage`, `knowledge`, `emergency`, `guardrail`, `unverified-booking`) via `run_all_scenarios()`; 6/6 passed all scenario assertions. |
| T3.1 | ✅ | `tests/test_agent.py::test_unverified_caller_write_blocked_and_escalated PASSED` — verified `caller_phone=None` allows `check_doctor_availability` while blocking `book_appointment` and `manage_appointment(action='cancel')` before DB mutation and routing to `transfer_to_receptionist`. |
| T3.2 | ✅ | `tests/test_agent.py::test_read_tool_timeout_aborts_and_yields_filler PASSED` — verified slow read tool (`check_doctor_availability`) is cancelled on timeout, increments `tool_timeout_count=1`, records `SpanStatus.ERROR` (`timeout`), and yields filler + fallback. |
| T3.3 | ✅ | `tests/test_agent.py::test_write_tool_hard_cap_escalates_to_receptionist PASSED` — verified write tool exceeding `write_tool_hard_cap_ms` emits filler and escalates to `transfer_to_receptionist(urgency='urgent')` with `CallLifecycle.ESCALATED`. |
| T3.4 | ✅ | `tests/test_agent.py::test_barge_in_mid_write_shields_db_transaction PASSED` — verified `gen.aclose()` + interrupted speech callback mid-write preserves `asyncio.shield` SQLite commit (`queue_number=1`) and increments `total_interruptions=1`. |
| T3.5 | ✅ | `tests/test_agent.py::test_input_and_output_guardrails_block_injection_and_diagnosis PASSED` — verified `InputGuardrail` blocks prompt injection & medication requests (`0` LLM calls) and `OutputGuardrail` scrubs unsafe LLM diagnosis & antibiotic dosage output before TTS yield (`cache.tier1_backend.size() == 0`). |
| T3.6 | ✅ | `tests/test_agent.py::test_unallowed_tool_call_rejected PASSED` — verified non-allowlisted LLM tool calls (`drop_table`, `export_all_patient_records`) are blocked (`SpanStatus.BLOCKED`), logged at `WARNING`, never dispatched, and yield safe fallback. |
| T3.7 | ✅ | `tests/test_agent.py::test_finops_budget_exhaustion_degrades_gracefully PASSED` — verified daily spend cap breach degrades to `TIER_3_SEARCH_ONLY` (`0` LLM calls, grounded clinic KB fallback) and per-call token budget breach degrades to `TIER_4_HUMAN_ESCALATION` + `transfer_to_receptionist`. |
| T4.1 | ✅ | `uv run pytest -v` → `594 passed, 3 warnings in ~78s` (zero regressions across entire test suite, including repository purity guard and deep-review hardening tests). |
| T4.2 | ✅ | `uv run pytest tests/evals/test_golden_evals.py -v` → `10 passed, 2 warnings in ~3.3s` (100% golden dataset exact-match, RAGAS thresholds, and adversarial/emergency interception). |
| T5.1 | ✅ | `uv run ruff check .` → `All checks passed!` (`0` lint/import errors). |
| Type checks | ⏭ N/A | Not Applicable — no type checker is configured in `pyproject.toml`. |
| T6.1 | ⏭ Deferred | Deferred to Phase Gate 2 manual live voice call (`phase-overview.md` PI.9). |
| T7.1 | ✅ | `uv run pytest tests/test_agent.py -v` → `19 passed, 2 warnings in ~8.0s` (`< 15s` per `NFR1`, 100% offline & deterministic, including production secret guard and tool-loop cap tests). |

