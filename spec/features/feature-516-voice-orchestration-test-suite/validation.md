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
- [ ] T1.1 — `tests/test_agent.py::test_voice_component_factories_and_pipeline_assembly` verifies `create_stt`, `create_tts`, `create_vad`, `create_voice_pipeline`, and `get_worker_options` offline.
- [ ] T1.2 — `tests/test_agent.py::test_single_call_language_configuration` verifies Arabic default (`ar`) and English (`en`) configuration across STT, greeting, and system prompt.
- [ ] T1.3 — `tests/test_agent.py::test_extract_verified_caller_identity_and_jwt_roundtrip` verifies SIP attribute priority, signed JWT attributes from `generate_token.py`, and `caller_phone=None` fallback.

### Tier 2: Integration Verification
- [ ] T2.1 — `tests/test_agent.py::test_clinic_voice_agent_llm_node_chat_context` verifies `ClinicVoiceAgent.llm_node` processes `livekit.agents.llm.ChatContext` and streams spoken output chunks.
- [ ] T2.2 — `tests/test_agent.py::test_verified_caller_atomic_booking_flow` verifies end-to-end appointment booking with session-injected `caller_phone`, atomic queue number assignment, and `CallSession` booking record.
- [ ] T2.3 — `tests/test_agent.py::test_write_tool_slow_filler_and_shielded_commit` verifies a write tool exceeding the 400ms filler threshold emits a localized filler first and then completes the DB booking.
- [ ] T2.4 — `tests/test_agent.py::test_emergency_utterance_short_circuit_and_handoff` verifies emergency speech triggers `transfer_to_receptionist(urgency='critical')` and `build_emergency_message` with zero LLM call.
- [ ] T2.5 — `tests/test_agent.py::test_cache_hit_on_faq_and_bypass_on_booking` verifies `CacheLadder` caches general FAQ turns and bypasses personal/tool turns.
- [ ] T2.6 — `tests/test_agent.py::test_hierarchical_tracing_and_pii_redacted_session_persistence` verifies turn spans are recorded and persisted session JSON masks Egyptian phone numbers and national IDs.
- [ ] T2.7 — `tests/test_agent.py::test_all_six_clinic_simulated_scenarios` runs `booking`, `manage`, `knowledge`, `emergency`, `guardrail`, and `unverified-booking` scenarios and asserts all pass.

### Tier 3: Error & Edge-Case Verification
- [ ] T3.1 — `tests/test_agent.py::test_unverified_caller_write_blocked_and_escalated` verifies that with `caller_phone=None`, `check_doctor_availability` succeeds while `book_appointment` and `manage_appointment(action='cancel')` are blocked before DB write and routed to `transfer_to_receptionist`.
- [ ] T3.2 — `tests/test_agent.py::test_read_tool_timeout_aborts_and_yields_filler` verifies a read tool exceeding the timeout threshold is cancelled, increments `tool_timeout_count`, and yields a localized filler.
- [ ] T3.3 — `tests/test_agent.py::test_write_tool_hard_cap_escalates_to_receptionist` verifies a write tool exceeding `write_tool_hard_cap_ms` triggers receptionist escalation.
- [ ] T3.4 — `tests/test_agent.py::test_barge_in_mid_write_shields_db_transaction` verifies closing the turn generator mid-write preserves the shielded DB commit and records the interruption on `CallSession`.
- [ ] T3.5 — `tests/test_agent.py::test_input_and_output_guardrails_block_injection_and_diagnosis` verifies both input prompt-injection/diagnosis blocking and output medical-diagnosis scrubbing on `ClinicTurnEngine`.
- [ ] T3.6 — `tests/test_agent.py::test_unallowed_tool_call_rejected` verifies an LLM attempting to invoke a tool outside `CALLER_TOOL_ALLOWLIST` is blocked safely.
- [ ] T3.7 — `tests/test_agent.py::test_finops_budget_exhaustion_degrades_gracefully` verifies `FinOpsController` token budget breach degrades the turn to `SEARCH_ONLY` / `RECEPTIONIST`.

### Tier 4: Regression Checks
- [ ] T4.1 — Full test suite passes: `uv run pytest -v`
- [ ] T4.2 — Golden evaluation suite passes: `uv run pytest tests/evals/test_golden_evals.py -v`

### Tier 5: Build, Lint & Type Checks
- [ ] T5.1 — `uv run ruff check .` clean
- Type checks: Status: Not Applicable — no type checker is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- [ ] T6.1 — Covered by Phase Gate 2 manual live voice call (`phase-overview.md` PI.9).

### Tier 7: API / CLI / Application Checks
- [ ] T7.1 — `uv run pytest tests/test_agent.py -v` runs and passes all voice orchestration tests.

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
