# Requirements: Feature 5.5 — CLI Simulated Call Runner & Clinic Scenarios

> Decisions and behaviours, not implementation micro-details. Every requirement must be testable and map to at least one check in `validation.md`.

## 1. Functional Requirements
| ID | Requirement | Validated by |
|:---|:---|:---|
| R1 | **Scripted Clinic LLM Provider (`src/agent/scenarios.py`)**: `ScriptedClinicLLMProvider` must implement the `LLMProvider` streaming protocol (`astream`) from `src/ai_core/gateway.py` so `ModelGateway` executes its real stage routing, circuit breaker, FinOps accounting, and tracing spans while returning deterministic tool calls and Egyptian Arabic dialogue responses. | Tier 1 – T1.1; Tier 2 – T2.1 |
| R2 | **Six Core Clinic Benchmark Scenarios**: `CLINIC_SCENARIOS` in `src/agent/scenarios.py` must define and verify 6 multi-turn clinic scenarios through `ClinicTurnEngine`: `booking` (check availability + atomic appointment booking with queue number), `manage` (lookup + reschedule/cancel appointment), `knowledge` (clinic KB search for preparation/fees/policies), `emergency` (life-threatening symptom → immediate emergency message + `transfer_to_receptionist`), `guardrail` (prompt injection & medical diagnosis refusal), and `unverified-booking` (caller with `caller_phone=None` attempting a booking → read succeeds, write is blocked and routed to receptionist). | Tier 1 – T1.2; Tier 2 – T2.1, T2.2, T2.3; Tier 7 – T7.1, T7.2, T7.3 |
| R3 | **Dual LLM Execution Modes (`--mock-llm` and `--live`)**: `scripts/test_call.py` must default to `--mock-llm` (offline, deterministic, using `ScriptedClinicLLMProvider` and an isolated seeded clinic DB) and support `--live` (routing through `LiteLLMProvider` to Groq/Gemini when API keys are configured). | Tier 1 – T1.3; Tier 3 – T3.1; Tier 7 – T7.1 |
| R4 | **CLI Modes (`--scenario`, `--interactive`, `--livekit`)**: `scripts/test_call.py` must support `--scenario <name|all>` (returning exit code `0` when all scenario assertions pass and `1` when any fail), `--interactive` (console turn-by-turn conversation with `--phone` and `--lang`), and `--livekit <console|dev|start>` (bridging to `src.agent.voice_agent`). | Tier 1 – T1.3; Tier 3 – T3.2; Tier 7 – T7.1, T7.4 |
| R5 | **Session Persistence & Telemetry Summary**: Each simulated scenario run must record turns, tool calls, latency breakdown, and FinOps token usage on a `CallSession`, optionally persist the PII-redacted session JSON via `SessionManager`, and return a structured `ScenarioRunReport`. | Tier 2 – T2.4; Tier 7 – T7.1 |

## 2. Non-Functional Requirements
| ID | Requirement | Validated by |
|:---|:---|:---|
| NFR1 | **100% Offline Determinism in `--mock-llm` Mode**: Running `uv run python scripts/test_call.py --scenario all` must succeed with zero outbound network requests and zero cloud API keys configured. | Tier 7 – T7.1 |
| NFR2 | **Engine Parity (`phase-overview.md` P2)**: The simulated call runner must execute turns exclusively through `ClinicTurnEngine`—never re-implementing separate guardrail, tool-dispatch, or FinOps logic in the script. | Tier 2 – T2.1 |

## 3. Constraints (must NOT do / change)
- C1: Must respect all `spec/tech.md` invariants (§1–§10), including PII redaction on persisted call reports and caller identity enforcement.
- C2: Must **not** contain any restaurant scenarios, menu queries, order tracking, or table reservation logic.

## 4. Dependencies & Assumptions
- **Depends on**: Feature 5.3 (legacy restaurant purge) and Feature 5.4 (`ClinicTurnEngine` and `voice_agent.py`).
- **Assumptions**: None.
