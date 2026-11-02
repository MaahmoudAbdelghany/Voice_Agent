# Requirements Specification: Feature 4.7 — FinOps Token Budgets & Cost Circuit Breaker (`src/ai_core/finops.py`)

> Parent spec: `spec/features/feature-400-enterprise-ai-architecture-and-resilience/requirements.md` (R1.6, R14.1, R14.2, R14.3, R14.4, C4).

---

## 1. Functional Requirements

### R1: Per-Call Token Budget Enforcement & Remaining-Token Clamping (8,000 Tokens/Call)
- **R1.1**: The system must track cumulative token consumption (`prompt_tokens`, `completion_tokens`, `total_tokens`) and estimated USD cost (`total_cost_usd`) for each call session identified by `session_id` against a configurable per-call ceiling (`finops_call_token_budget`, default `8,000` tokens).
- **R1.2**: The active `session_id` must be resolved automatically in priority order without requiring manual parameter threading on every call:
  1. Explicit `session_id` argument or active `finops_session_scope(session_id)` (`contextvars`).
  2. Active trace context `get_current_trace().session_id` (`src/ai_core/tracing.py`).
  3. Active caller session `get_current_caller_session().session_id` or `caller_phone` (`src/tools/gates.py`).
- **R1.3**: When a call session has consumed `< 8,000` tokens and has `>= finops_min_turn_tokens` (default `16`) remaining, `FinOpsController.check_budget()` must allow the request and clamp `effective_max_tokens` to `min(stage_max_tokens, remaining_call_tokens)` so the final turn cannot overshoot the 8,000-token budget on completion tokens.
- **R1.4**: When a call session's cumulative tokens reach `>= 8,000` (or remaining tokens `< finops_min_turn_tokens`), `ModelGateway` must block further LLM provider calls for that session:
  - For `Stage.DIALOGUE`: yield a polite Egyptian Arabic wrap-up and receptionist handoff message (`DegradationTier.TIER_4_HUMAN_ESCALATION`, `escalate=True`, `error_class="call_token_budget_exceeded"`).
  - For `Stage.CLASSIFICATION` / `Stage.EXTRACTION`: return `GatewayResult(success=False, degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION, error_class="call_token_budget_exceeded")`.

### R2: Daily Spend Accumulator & 80% Early Alert ($10.00/Day Cap)
- **R2.1**: Every LLM invocation in `ModelGateway` that consumes tokens must record its prompt tokens, completion tokens, and deterministic USD cost (computed via `estimate_llm_cost_usd()` and `settings.llm_cost_per_1m_tokens`) into the daily spend bucket for the current Cairo calendar date (`Africa/Cairo`, `YYYY-MM-DD`).
- **R2.2**: When the Cairo calendar date rolls over at midnight, a fresh daily spend bucket (`$0.00`) must automatically become active without manual intervention.
- **R2.3**: When cumulative daily spend reaches or exceeds `finops_daily_spend_cap_usd * finops_daily_alert_ratio` (default `80%` = `$8.00` of `$10.00`), the controller must emit a structured `FinOpsAlert` (`level=AlertLevel.WARNING_80_PERCENT`) **exactly once per Cairo calendar day**, log a `WARNING`, store the alert in `recent_alerts`, and invoke any registered alert callbacks while continuing to allow Tier 1 / Tier 2 LLM calls until 100% is reached.

### R3: Cost Circuit Breaker & Graceful Tier 3 / Tier 4 Degradation
- **R3.1**: When cumulative daily spend reaches or exceeds `finops_daily_spend_cap_usd` (default `$10.00`), the controller must emit a `CRITICAL_100_PERCENT` `FinOpsAlert` (once per Cairo day) and trip the **Cost Circuit Breaker** (`DAILY_CAP_EXCEEDED`).
- **R3.2**: While the Cost Circuit Breaker is tripped (`DAILY_CAP_EXCEEDED`), `ModelGateway` must bypass all paid LLM providers (Groq Tier 1 and Gemini Tier 2) and degrade gracefully without dropping calls:
  1. If `Stage != Stage.DIALOGUE`: return `GatewayResult(success=False, degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION, error_class="daily_cost_cap_exceeded")`.
  2. If `Stage == Stage.DIALOGUE` and the caller utterance matches `detect_emergency()`: immediately escalate to `DegradationTier.TIER_4_HUMAN_ESCALATION` (`escalate=True`, `error_class="emergency_detected"`) with emergency hotline `123` instructions.
  3. If `Stage == Stage.DIALOGUE` (non-emergency): execute the Tier 3 knowledge base search fallback (`_execute_search_fallback` within 400ms). If a grounded snippet is found, yield it with `degradation_tier=DegradationTier.TIER_3_SEARCH_ONLY` and `error_class="daily_cost_cap_exceeded"`.
  4. If the Tier 3 search fallback returns no snippet: escalate to the human receptionist (`degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION`, `escalate=True`, `error_class="daily_cost_cap_exceeded"`).

### R4: Schema-Aware Tool Payload Pruning (`prune_tool_payload`)
- **R4.1**: `prune_tool_payload(tool_name, payload, settings=None)` must accept a `ToolResult` instance, dictionary, or JSON string and return a compact dictionary suitable for appending to LLM message state.
- **R4.2**: The pruned output must always preserve top-level `success` (`bool`), `message` (`str`), and `error` (`str | None` when present), while filtering `data` to a deterministic per-tool allowlist of essential fields:
  - `check_doctor_availability`: `found`, `doctor_id`, `doctor_name`, `specialty`, `date`, `day_of_week`, `shift_start`, `shift_end`, `available_slots`, `max_capacity`, `examination_fee_egp`, `consultation_fee_egp`, `doctors`, `schedules`, `next_available_dates`.
  - `book_appointment`: `booking_code`, `appointment_id`, `queue_number`, `doctor_id`, `doctor_name`, `specialty`, `appointment_date`, `shift_start`, `shift_end`, `visit_type`, `fee_egp`, `status`, `idempotent_replay`.
  - `manage_appointment`: `action`, `booking_code`, `appointment_id`, `queue_number`, `doctor_name`, `specialty`, `appointment_date`, `new_date`, `shift_start`, `shift_end`, `status`, `appointments`.
  - `search_clinic_knowledge`: `found`, `category`, `top_score`, `results` (pruned to `title`/`section`, `text`/`content`, `category`, `score`).
  - `transfer_to_receptionist`: `handoff_id`, `alert_id`, `priority`, `reason`, `department`, `reception_open`, `emergency_detected`, `emergency_phone`.
- **R4.3**: Lists inside `data` must be truncated to at most `finops_max_tool_list_items` (default `5`), string fields inside `data` must be truncated to `finops_max_tool_field_chars` (default `300`), and the serialized JSON representation via `format_pruned_tool_message()` must not exceed `finops_max_tool_payload_chars` (default `1,200`).

---

## 2. Non-Functional Requirements

### NFR1: Sub-Millisecond Hot-Path Gate Overhead (< 0.5ms)
- Executing `FinOpsController.check_budget()`, `FinOpsController.record_usage()`, and `prune_tool_payload()` are pure in-memory Python operations and must add **< 0.5ms** of CPU overhead per turn.

### NFR2: Bounded Memory Footprint
- Per-call session ledgers must be stored in a bounded LRU structure (`finops_max_tracked_sessions = 2000`), evicting the oldest inactive session when full so long-running processes never leak memory.

### NFR3: Concurrency & Thread/Async Safety
- Token and spend accumulation across concurrent async turns (`asyncio.gather`) must be deterministic with zero lost updates or race conditions.

---

## 3. Constraints & Invariants

- **C1 (Deterministic Code > Prompts)**: Token caps, call budgets, and daily spend circuit breakers must be enforced in deterministic Python code inside `FinOpsController` and `ModelGateway`, never delegated to prompt instructions (`spec/tech.md` Invariant 8).
- **C2 (Centralized Configuration)**: All FinOps thresholds (`8,000` call tokens, `150` voice turn tokens, `$10.00` daily cap, `0.80` alert ratio, tool pruning limits) must reside in `src/config.py`.
- **C3 (Zero Call Drops on Budget Breach)**: Breaching either the per-call budget or the daily spend cap must always return a valid `GatewayResult` (`success=True` on `Stage.DIALOGUE`) with a polite Egyptian Arabic voice message and appropriate `DegradationTier` (`TIER_3_SEARCH_ONLY` or `TIER_4_HUMAN_ESCALATION`).

