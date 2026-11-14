# Validation Criteria: Feature 5.5 — CLI Simulated Call Runner & Clinic Scenarios

## 1. Success Definition
Feature 5.5 is successful when `src/agent/scenarios.py` and `scripts/test_call.py` execute all 6 clinic benchmark scenarios (`booking`, `manage`, `knowledge`, `emergency`, `guardrail`, `unverified-booking`) end-to-end through `ClinicTurnEngine` in offline `--mock-llm` mode with exit code `0`, verify booking queue numbers, emergency escalations, guardrail refusals, and unverified-caller write blocks, persist PII-redacted session reports, and pass all automated tests and lint checks.

## 2. Requirement Traceability
| Requirement | Checks |
|:---|:---|
| R1 | T1.1, T2.1 |
| R2 | T1.2, T2.1, T2.2, T2.3, T7.1, T7.2, T7.3 |
| R3 | T1.3, T3.1, T7.1 |
| R4 | T1.3, T3.2, T7.1, T7.4 |
| R5 | T2.4, T7.1 |
| NFR1 | T7.1 |
| NFR2 | T2.1 |

---

## 3. Verification Tiers

### Tier 1: Unit Verification (`tests/test_simulated_scenarios.py`)
- [x] T1.1 — `ScriptedClinicLLMProvider` implements `astream` and yields valid `(text_chunk, tool_calls_delta, metadata)` tuples compatible with `ModelGateway`.
- [x] T1.2 — `CLINIC_SCENARIOS` contains exactly the 6 required scenario keys: `booking`, `manage`, `knowledge`, `emergency`, `guardrail`, and `unverified-booking`.
- [x] T1.3 — `scripts/test_call.py` argument parser parses `--scenario`, `--mock-llm`, `--live`, `--interactive`, `--phone`, `--lang`, `--save-session`, and `--livekit`.

### Tier 2: Integration Verification (`tests/test_simulated_scenarios.py`)
- [x] T2.1 — `run_simulated_scenario("booking")` runs multi-turn conversation through `ClinicTurnEngine` + seeded SQLite DB, executes `check_doctor_availability` and `book_appointment`, assigns a queue number, and returns `ScenarioRunReport(passed=True)`.
- [x] T2.2 — `run_simulated_scenario("emergency")` and `run_simulated_scenario("guardrail")` verify emergency escalation (`is_emergency=True`, `transfer_to_receptionist`) and prompt-injection/diagnosis refusal (`passed=True`).
- [x] T2.3 — `run_simulated_scenario("unverified-booking")` runs with `caller_phone=None`, verifies availability read succeeds, and confirms booking attempt is blocked before DB write and routed to `transfer_to_receptionist` (`passed=True`).
- [x] T2.4 — Running a scenario with `save_session=True` persists a PII-redacted call JSON artifact via `SessionManager` where raw phone numbers are masked.

### Tier 3: Error & Edge-Case Verification (`tests/test_simulated_scenarios.py`)
- [x] T3.1 — Running `--live` when `GROQ_API_KEY` and `GEMINI_API_KEY` are unset either exits with a clear configuration message or falls back gracefully via the gateway's degradation tiers without an unhandled traceback.
- [x] T3.2 — Passing an unknown scenario name (`--scenario nonexistent`) prints valid scenario names and exits with non-zero status code.

### Tier 4: Regression Checks
- [x] T4.1 — Full test suite passes: `uv run pytest -v`

### Tier 5: Build, Lint & Type Checks
- [x] T5.1 — `uv run ruff check .` clean
- Type checks: Status: Not Applicable — no type checker is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: `scripts/test_call.py` is a CLI tool verified directly via Tier 7 non-interactive command execution and exit-code assertions. Live voice interaction via `--livekit console` is covered at Phase Gate 2 (PI.9).

### Tier 7: API / CLI / Application Checks
- [x] T7.1 — `uv run python scripts/test_call.py --scenario booking` exits `0` and prints booking confirmation with queue number (`PI.1`).
- [x] T7.2 — `uv run python scripts/test_call.py --scenario emergency` exits `0` and confirms emergency instruction + receptionist handoff (`PI.2`).
- [x] T7.3 — `uv run python scripts/test_call.py --scenario unverified-booking` exits `0` and confirms zero DB booking writes + receptionist handoff (`PI.3`).
- [x] T7.4 — `uv run python scripts/test_call.py --scenario all` runs all 6 clinic scenarios offline and exits `0`.

---

## 4. Automated Execution Commands
```bash
uv run pytest tests/test_simulated_scenarios.py -v
uv run python scripts/test_call.py --scenario all
uv run pytest -v
uv run ruff check .
```

## 5. Execution Results (filled in execute mode)
| Check | Result (✅ / ❌ / ⏭ N/A) | Evidence (command output summary, counts) |
|:---|:---|:---|
| T1.1 | ✅ | `tests/test_simulated_scenarios.py::test_t1_1_scripted_provider_streams_text_and_integrates_with_model_gateway` & `test_t1_1_scripted_provider_streams_tool_call_deltas_via_model_gateway` PASSED (3-tuple `astream` protocol + `ModelGateway` text & tool-call delta stitching + `FinOpsController` 165-token ledger verified). |
| T1.2 | ✅ | `tests/test_simulated_scenarios.py::test_t1_2_clinic_scenarios_contains_exact_six_required_keys` PASSED (`{'booking', 'manage', 'knowledge', 'emergency', 'guardrail', 'unverified-booking'}`). |
| T1.3 | ✅ | `tests/test_simulated_scenarios.py::test_t1_3_test_call_cli_parser_supports_all_required_flags` PASSED (`--scenario`, `--mock-llm`, `--live`, `--interactive`, `--phone`, `--lang`, `--save-session`, `--livekit console|dev|start`). |
| T2.1 | ✅ | `tests/test_simulated_scenarios.py::test_t2_1_booking_scenario_executes_availability_and_atomic_booking_with_queue` & `test_t2_1_manage_and_knowledge_scenarios_pass_end_to_end` PASSED (`booking`: `APT-20261114-01001`, `queue_numbers=[1]`, `db_appointments_count=1`, `total_tokens=800`; `manage` & `knowledge`: `passed=True`). |
| T2.2 | ✅ | `tests/test_simulated_scenarios.py::test_t2_2_emergency_and_guardrail_scenarios_enforce_safety_boundaries` PASSED (`emergency`: `is_emergency=True`, `escalated=True`, `transfer_to_receptionist`, `123` instruction, 0 LLM tokens; `guardrail`: prompt injection & diagnosis refused in Egyptian Arabic, 0 tool/LLM calls). |
| T2.3 | ✅ | `tests/test_simulated_scenarios.py::test_t2_3_unverified_booking_allows_read_and_blocks_write_with_handoff` PASSED (`check_doctor_availability` succeeded on Turn 1; `book_appointment` blocked before DB write on Turn 2 with `db_appointments_count=0` and routed to `transfer_to_receptionist`). |
| T2.4 | ✅ | `tests/test_simulated_scenarios.py::test_t2_4_save_session_persists_pii_redacted_json_artifact` PASSED (persisted JSON masks raw phone `01012345678`; `save_session=False` writes 0 files to `data/calls/`). |
| T3.1 | ✅ | `tests/test_simulated_scenarios.py::test_t3_1_live_mode_with_unset_api_keys_exits_cleanly_and_gateway_degrades` PASSED (`--live` with empty `GROQ_API_KEY`/`GEMINI_API_KEY` exits code `2` with clear configuration message and zero traceback; programmatic `live=True` degrades gracefully via `ModelGateway`). |
| T3.2 | ✅ | `tests/test_simulated_scenarios.py::test_t3_2_unknown_scenario_prints_valid_names_and_exits_nonzero` PASSED (`--scenario nonexistent` exits code `2` and prints all 6 valid scenario names). |
| T4.1 | ✅ | `uv run pytest -v` → **569 passed**, 0 failed in 74.88s (including `test_repository_purity_guard_no_legacy_restaurant_symbols` and `test_t1_8_zero_import_time_http_requests`). |
| T5.1 | ✅ | `uv run ruff check .` → `All checks passed!` (exit code `0`). |
| Type checks | ⏭ N/A | Not Applicable — no type checker is configured in `pyproject.toml`. |
| Tier 6 | ⏭ N/A | Not Applicable — CLI runner verified via Tier 7 command execution and exit-code assertions; interactive `--livekit console` covered at Phase Gate 2 (`PI.9`). |
| T7.1 | ✅ | `uv run python scripts/test_call.py --scenario booking` exited `0` (`[PASS]`, `Bookings: APT-20261114-01001 (queue #1) | DB Appointments: 1`, `Tokens: 800`, `1/1 scenarios passed`). |
| T7.2 | ✅ | `uv run python scripts/test_call.py --scenario emergency` exited `0` (`[PASS]`, `Emergency: True | Escalated: True | Lifecycle: escalated`, `123` ambulance instruction + `transfer_to_receptionist`, `Tokens: 0`). |
| T7.3 | ✅ | `uv run python scripts/test_call.py --scenario unverified-booking` exited `0` (`[PASS]`, `DB Appointments: 0 | Escalated: True | Lifecycle: escalated`, `Tools: check_doctor_availability, transfer_to_receptionist`). |
| T7.4 | ✅ | `uv run python scripts/test_call.py --scenario all` exited `0` (`Total: 6/6 scenarios passed`: `booking`, `manage`, `knowledge`, `emergency`, `guardrail`, `unverified-booking`; `data/calls/` kept 100% clean with 0 stray files). |
