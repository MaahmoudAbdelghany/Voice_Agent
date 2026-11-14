# Requirements: Feature 5.6 — Automated Voice Orchestration & Guardrail Test Suite

> Decisions and behaviours, not implementation micro-details. Every requirement must be testable and map to at least one check in `validation.md`.

## 1. Functional Requirements
| ID | Requirement | Validated by |
|:---|:---|:---|
| R1 | **Pipeline, `llm_node` & Single-Language Tests**: `tests/test_agent.py` must verify `create_stt`, `create_tts`, `create_vad`, `create_voice_pipeline`, `get_worker_options`, single-language resolution (`ar` and `en`), and `ClinicVoiceAgent.llm_node` streaming response chunks from `livekit.agents.llm.ChatContext`. | Tier 1 – T1.1, T1.2; Tier 2 – T2.1 |
| R2 | **Verified Caller Identity & Unverified Write Protection Tests**: `tests/test_agent.py` must verify `extract_verified_caller_identity` for SIP (`sip.phoneNumber`), signed JWT (`caller_phone` from `scripts/generate_token.py`), and unverified callers (`caller_phone=None`), proving that unverified callers can execute read tools (`check_doctor_availability`, `search_clinic_knowledge`, `manage_appointment` lookup) while any write tool (`book_appointment`, `manage_appointment` cancel/reschedule) is intercepted before touching the DB and routed to `transfer_to_receptionist`. | Tier 1 – T1.3; Tier 2 – T2.2; Tier 3 – T3.1 |
| R3 | **Read vs. Write Tool Timeout & Barge-In Shielding Tests**: `tests/test_agent.py` must verify: (a) read tools exceeding the timeout threshold abort and yield a filler, (b) write tools exceeding the filler threshold yield a filler and complete their shielded DB transaction (`asyncio.shield`), (c) write tools exceeding `write_tool_hard_cap_ms` escalate to `transfer_to_receptionist`, and (d) closing the turn generator mid-write (simulating Silero VAD barge-in) does not abort the shielded DB commit and records the interruption on `CallSession`. | Tier 2 – T2.3; Tier 3 – T3.2, T3.3, T3.4 |
| R4 | **Guardrails, Emergency Escalation & Allowlist Enforcement Tests**: `tests/test_agent.py` must verify: (a) `InputGuardrail` blocks prompt injection and diagnosis requests on the voice path, (b) `OutputGuardrail` blocks/replaces unsafe LLM medical diagnosis output before TTS yield, (c) emergency utterances bypass LLM generation and immediately invoke `transfer_to_receptionist(urgency='critical')` + `build_emergency_message`, and (d) non-allowlisted tool calls from the LLM are rejected. | Tier 2 – T2.4; Tier 3 – T3.5, T3.6 |
| R5 | **Cache Bypass, FinOps Degradation & Hierarchical Tracing Tests**: `tests/test_agent.py` must verify: (a) `CacheLadder` caches general FAQ turns and bypasses personal/booking/tool turns, (b) `FinOpsController` degrades turns when call/daily budgets are breached, and (c) `HierarchicalTracer` emits nested spans with PII redacted on every voice turn and `SessionManager` persists PII-redacted call JSON on session end. | Tier 2 – T2.5, T2.6; Tier 3 – T3.7 |
| R6 | **End-to-End Multi-Turn Clinic Scenarios**: `tests/test_agent.py` must execute all 6 `CLINIC_SCENARIOS` (`booking`, `manage`, `knowledge`, `emergency`, `guardrail`, `unverified-booking`) and assert every scenario passes. | Tier 2 – T2.7 |

## 2. Non-Functional Requirements
| ID | Requirement | Validated by |
|:---|:---|:---|
| NFR1 | **Fast, Offline & Deterministic Execution**: `uv run pytest tests/test_agent.py -v` must complete in under 15 seconds with zero network calls and zero flaky sleeps. | Tier 1 – T1.1; Tier 4 – T4.1 |
| NFR2 | **Zero Regressions & Golden Eval Compatibility**: The full test suite (`uv run pytest -v`), `ruff check .`, and golden evaluation suite (`uv run pytest tests/evals/test_golden_evals.py -v`) must pass. | Tier 4 – T4.1, T4.2; Tier 5 – T5.1 |

## 3. Constraints (must NOT do / change)
- C1: Must respect all `spec/tech.md` invariants (§1–§10) and `sdd-validation` strict rules (no fabricated hollow mocks that bypass `ClinicTurnEngine`).
- C2: Must contain zero legacy restaurant tests (`order_status`, `book_reservation`, `restaurant_kb`).

## 4. Dependencies & Assumptions
- **Depends on**: Features 5.3, 5.4, and 5.5.
- **Assumptions**: None.
