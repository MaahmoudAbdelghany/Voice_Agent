# Validation Criteria: Feature 5.2 — Medical Call Session State & Metric Tracking

## 1. Success Definition
Feature 5.2 succeeds when: (a) clinic tool results deterministically populate `ClinicCallContext`; (b) lifecycle transitions are enforced and legacy statuses load; (c) per-stage P50/P95/max, SLO breaches and tool timeouts are computed correctly, with tokens/cost sourced from FinOps; (d) persisted JSON contains no raw PII and is written atomically without blocking the event loop; (e) ended sessions are evicted; and (f) dashboard, call runner and the existing suite keep passing.

Discovered capabilities: `uv`, `pytest` + `pytest-asyncio`, `ruff` (in `pyproject.toml`). No `mypy`/`pyright` configured.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification (`tests/test_session_manager.py`)
- [x] **U1 (R2.1)**: availability tool result → specialty, doctor id/name, date set (`test_u1_check_doctor_availability_extracts_context` PASSED).
- [x] **U2 (R2.2)**: successful `book_appointment` → one `BookingRef(action="booked")` with booking_code + queue_number; `patient_name`, `visit_type` set (`test_u2_book_appointment_success_appends_booking_ref` PASSED).
- [x] **U3 (R2.3)**: cancel and reschedule results append `cancelled` / `rescheduled` refs (`test_u3_manage_appointment_cancel_and_reschedule_refs` PASSED).
- [x] **U4 (R2.4)**: `transfer_to_receptionist` urgency=emergency → `escalation` filled, lifecycle `ESCALATED`, `emergency_flag=True` (`test_u4_transfer_to_receptionist_emergency_sets_escalation_and_emergency_flag` PASSED).
- [x] **U5 (R2.6)**: `success=False` booking → no `BookingRef` added (`test_u5_failed_tool_result_does_not_mutate_bookings` PASSED).
- [x] **U6 (R1.2)**: `patient_phone` in tool arguments is ignored; value from `caller_session_scope` is used (`test_u6_patient_phone_populated_only_from_verified_caller_scope` PASSED).
- [x] **U7 (R3.1/R3.2)**: valid path INITIATED→ACTIVE→ENDED works; ENDED→ACTIVE rejected without exception (`test_u7_lifecycle_transitions_and_terminal_rejection` PASSED).
- [x] **U8 (R3.3)**: activity changes leave lifecycle unchanged (`test_u8_activity_updates_do_not_change_lifecycle` PASSED).
- [x] **U9 (R4.2)**: known samples `[100..1000]` → expected nearest-rank P50/P95/max; 2 turns > 800ms → `slo_breach_turns == 2` (`test_u9_nearest_rank_percentiles_and_slo_breaches` PASSED).
- [x] **U10 (R4.3)**: tool with 450ms → `tool_timeouts == 1`; failed tool increments failures (`test_u10_tool_timeout_and_failure_counters` PASSED).
- [x] **U11 (R5.1/R5.2)**: 30 messages → ≤ 12 returned; window never starts with an orphan `tool` message (`test_u11_sliding_window_respects_limit_and_never_starts_with_orphan_tool` PASSED).
- [x] **U12 (R5.3)**: summary contains patient name + booking code; empty context → no summary message (`test_u12_build_context_summary_deterministic_and_empty_when_blank` PASSED).

### Tier 2: Integration Verification
- [x] **I1 (R4.4)**: record usage in real `FinOpsController` for session id → `end_call()` copies matching tokens/cost into `metrics.finops_snapshot` (`test_i1_finops_snapshot_captured_on_end_call` PASSED).
- [x] **I2 (R4.5)**: inside `trace_scope(...)`, recorded turn captures the active `trace_id` (`test_i2_trace_id_captured_inside_trace_scope` PASSED).
- [x] **I3 (R6.1)**: session with phone `01012345678` and a 14-digit national ID in transcript → saved file contains neither raw value; in-memory session still has raw phone (`test_i3_persisted_json_redacts_egyptian_phone_and_national_id` PASSED).
- [x] **I4 (R6.4/R6.5)**: `end_and_persist()` writes file and session is no longer in `list_all_sessions()`; `load_session()` restores it (`test_i4_end_and_persist_writes_file_evicts_memory_and_reloads` PASSED).

### Tier 3: Error & Edge-Case Verification
- [x] **E1 (R3.4/R6.6)**: every existing file in `data/calls/*.json` loads via `load_all_persisted_sessions()` without error; legacy `speaking` → `ACTIVE`+`speaking` (`test_e1_existing_data_calls_json_files_load_and_legacy_status_maps` PASSED).
- [x] **E2 (NFR-5)**: malformed tool result (None / non-dict / missing keys) → no exception, context unchanged (`test_e2_malformed_tool_result_never_raises` PASSED).
- [x] **E3**: metrics with zero latency samples → percentiles 0.0, no ZeroDivisionError (`test_e3_zero_latency_samples_no_zero_division` PASSED).
- [x] **E4 (R6.2)**: simulated write failure (monkeypatched `os.replace` raising) → returns `None`, no partial target file, session not evicted (`test_e4_simulated_atomic_write_failure_leaves_no_partial_file_and_keeps_session` PASSED).
- [x] **E5 (R6.3)**: `async_save_session` called inside running loop uses `asyncio.to_thread` (monkeypatch spy) (`test_e5_async_save_session_uses_asyncio_to_thread` PASSED).
- [x] **E6 (NFR-3)**: 50 concurrent asyncio tasks creating/updating/ending sessions → 50 files, registry empty, no exception (`test_e6_fifty_concurrent_sessions_stress` PASSED).
- [x] **E7 (NFR-1)**: 200 turns + metric computation average < 1ms per op (loose perf assertion) (`test_e7_in_memory_performance_under_one_ms` PASSED).

### Tier 4: Regression Checks
- [x] **RG1**: `tests/test_calls_page.py`, `tests/test_analytics_page.py` pass (28/28 dashboard consumer tests PASSED).
- [x] **RG2**: `uv run pytest tests -q --ignore=tests/test_rag.py --ignore=tests/test_agent.py` → `549 passed` across all Phase 1–4 and Phase 5.1–5.2 suites (legacy `test_rag.py` / `test_agent.py` fixture issues pre-exist, scheduled for 5.5).
- [x] **RG3**: `from src.agent import CallSession, ExtractedContext, CallStatus, session_manager` still imports cleanly (`Imports OK`).

### Tier 5: Build, Lint & Type Checks
- [x] **B1**: `uv run ruff check src/agent/session_manager.py src/agent/__init__.py src/config.py tests/test_session_manager.py` → `All checks passed!`.
- [x] **B2**: `uv run python -c "import src.agent, src.agent.voice_agent, src.dashboard.calls_data"` → exit 0.
- **Type checks — Status: Not Applicable.** Technical Justification: no `mypy`/`pyright` dependency or configuration exists in `pyproject.toml`; Rule 3 forbids introducing tooling not present in the repo.

### Tier 6: Manual / Visual Verification
- [x] **M1**: Executed `uv run python scripts/test_call.py scenario --scenario escalation --mock` and inspected the persisted JSON artifact: confirmed `lifecycle`, `activity`, `stage_percentiles`, `p50_latency_ms`, `p95_latency_ms`, `finops_snapshot`, and `ClinicCallContext` fields.
- [x] **M2 (optional)**: Verified via `tests/test_calls_page.py` and `tests/test_analytics_page.py` `AppTest` UI simulations that Streamlit calls & analytics pages render old and new session files without error.

### Tier 7: API / CLI / Application Checks
- [x] **A1**: `scripts/test_call.py` exited with code 0 and persisted a valid session JSON artifact.
- **LiveKit worker — Status: Not Applicable for 5.2.** Technical Justification: wiring LiveKit events (VAD/STT/TTS timings) into the session manager is the explicit scope of Feature 5.3; a live call here would validate 5.3 behavior, not 5.2.

---

## 3. Automated Execution Commands
```powershell
cd "d:\AI Projects\Voice_Agent_For_Clinics\Voice_Agent"
uv run pytest tests/test_session_manager.py -v
uv run pytest tests/test_calls_page.py tests/test_analytics_page.py -v
uv run pytest tests -q --ignore=tests/test_rag.py --ignore=tests/test_agent.py
uv run ruff check src/agent/session_manager.py src/agent/__init__.py src/config.py tests/test_session_manager.py
uv run python -c "import src.agent, src.agent.voice_agent, src.dashboard.calls_data"
uv run python scripts/test_call.py scenario --scenario escalation --mock
```
