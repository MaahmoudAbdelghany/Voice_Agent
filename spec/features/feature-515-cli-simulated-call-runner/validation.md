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

### Tier 1: Unit Verification
- [ ] T1.1 — `ScriptedClinicLLMProvider` implements `astream` and yields valid `(text_chunk, tool_calls_delta, metadata)` tuples compatible with `ModelGateway`.
- [ ] T1.2 — `CLINIC_SCENARIOS` contains exactly the 6 required scenario keys: `booking`, `manage`, `knowledge`, `emergency`, `guardrail`, and `unverified-booking`.
- [ ] T1.3 — `scripts/test_call.py` argument parser parses `--scenario`, `--mock-llm`, `--live`, `--interactive`, `--phone`, `--lang`, `--save-session`, and `--livekit`.

### Tier 2: Integration Verification
- [ ] T2.1 — `run_simulated_scenario("booking")` runs multi-turn conversation through `ClinicTurnEngine` + seeded SQLite DB, executes `check_doctor_availability` and `book_appointment`, assigns a queue number, and returns `ScenarioRunReport(passed=True)`.
- [ ] T2.2 — `run_simulated_scenario("emergency")` and `run_simulated_scenario("guardrail")` verify emergency escalation (`is_emergency=True`, `transfer_to_receptionist`) and prompt-injection/diagnosis refusal (`passed=True`).
- [ ] T2.3 — `run_simulated_scenario("unverified-booking")` runs with `caller_phone=None`, verifies availability read succeeds, and confirms booking attempt is blocked before DB write and routed to `transfer_to_receptionist` (`passed=True`).
- [ ] T2.4 — Running a scenario with `save_session=True` persists a PII-redacted call JSON artifact via `SessionManager` where raw phone numbers are masked.

### Tier 3: Error & Edge-Case Verification
- [ ] T3.1 — Running `--live` when `GROQ_API_KEY` and `GEMINI_API_KEY` are unset either exits with a clear configuration message or falls back gracefully via the gateway's degradation tiers without an unhandled traceback.
- [ ] T3.2 — Passing an unknown scenario name (`--scenario nonexistent`) prints valid scenario names and exits with non-zero status code.

### Tier 4: Regression Checks
- [ ] T4.1 — Full test suite passes: `uv run pytest -v`

### Tier 5: Build, Lint & Type Checks
- [ ] T5.1 — `uv run ruff check .` clean
- Type checks: Status: Not Applicable — no type checker is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: `scripts/test_call.py` is a CLI tool verified directly via Tier 7 non-interactive command execution and exit-code assertions. Live voice interaction via `--livekit console` is covered at Phase Gate 2 (PI.9).

### Tier 7: API / CLI / Application Checks
- [ ] T7.1 — `uv run python scripts/test_call.py --scenario booking` exits `0` and prints booking confirmation with queue number (`PI.1`).
- [ ] T7.2 — `uv run python scripts/test_call.py --scenario emergency` exits `0` and confirms emergency instruction + receptionist handoff (`PI.2`).
- [ ] T7.3 — `uv run python scripts/test_call.py --scenario unverified-booking` exits `0` and confirms zero DB booking writes + receptionist handoff (`PI.3`).
- [ ] T7.4 — `uv run python scripts/test_call.py --scenario all` runs all 6 clinic scenarios offline and exits `0`.

---

## 4. Automated Execution Commands
```bash
uv run python scripts/test_call.py --scenario all
uv run pytest -v
uv run ruff check .
```

## 5. Execution Results (filled in execute mode)
| Check | Result (✅ / ❌ / ⏭ N/A) | Evidence (command output summary, counts) |
|:---|:---|:---|
