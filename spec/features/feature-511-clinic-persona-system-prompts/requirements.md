# Requirements Specification: Feature 5.1 — Egyptian Clinic Assistant Persona, System Prompts & Medical Guardrails (`src/agent/prompts.py`)

> Plan: `spec/features/feature-511-clinic-persona-system-prompts/plan.md`
> Invariants: `spec/tech.md` §2.3 (Medical Safety), §2.5 (Tool outputs in Egyptian Arabic), §2.8 (FinOps), §2.9 (Untrusted Content).

---

## 1. Functional Requirements

### R1: Clinic Persona (Zero Restaurant Residue)
- **R1.1**: The system prompt must identify the assistant by `settings.agent_name` as the voice receptionist of `settings.clinic_name`, including clinic tagline, address, phone, and working hours sourced from `src/config.py`.
- **R1.2**: No user-facing prompt or canned message produced by `src/agent/prompts.py` or `src/agent/messages.py` may contain restaurant-domain terms (e.g. `restaurant`, `menu`, `order`, `reservation`, `مطعم`, `منيو`).
- **R1.3**: The prompt must reference exactly the five clinic tools by name: `check_doctor_availability`, `book_appointment`, `manage_appointment`, `search_clinic_knowledge`, `transfer_to_receptionist`, with a policy for when each is used.

### R2: Static / Dynamic Prompt Split (Prefix-Cache Compatibility)
- **R2.1**: `build_static_system_prompt()` must return text containing no date, time, session, caller, or degradation data, and must be accepted by `PromptPrefixBuilder` without raising.
- **R2.2**: For identical settings, repeated calls to `build_static_system_prompt()` must return byte-identical text (stable `PromptPrefixBuilder.prefix_hash`), regardless of the wall-clock time.
- **R2.3**: `build_dynamic_context(language, degradation_tier, now=None)` must include the current Cairo (`Africa/Cairo`) date, weekday, and time, plus the caller's preferred language.
- **R2.4**: `get_system_prompt(custom_instructions=None, language="ar", ...)` must return a single string = static prompt followed by dynamic context (and custom instructions when provided), for use as LiveKit `Agent(instructions=...)`. Its existing keyword arguments `custom_instructions` and `language` must remain supported.

### R3: Language & Voice Style
- **R3.1**: Instructions are written in English; the prompt must direct the model to reply by default in polite Egyptian Arabic (العامية المصرية المهذبة) and to mirror the caller's language (MSA or English).
- **R3.2**: The prompt must forbid Markdown and symbols in spoken output, limit replies to 1–3 short sentences, ask one question per turn, and require spoken-friendly numbers, times, and currency.

### R4: Medical Safety Guardrails (Prompt Layer)
- **R4.1**: The prompt must prohibit medical diagnosis, naming possible conditions, recommending drugs or dosages, and offering medical reassurance.
- **R4.2**: The prompt must allow **administrative specialty routing only** — suggesting which specialty/doctor to book, framed as "the doctor will assess the case".
- **R4.3**: The prompt must instruct that on emergency symptoms (e.g. chest pain, severe bleeding, difficulty breathing) the assistant tells the caller to call `settings.emergency_phone` or go to the nearest emergency department, and immediately calls `transfer_to_receptionist`.
- **R4.4**: The prompt must require that fees, preparation instructions, insurance, doctor credentials, availability, and queue numbers come only from tool results, never from model knowledge.

### R5: Write Confirmation Protocol
- **R5.1**: The prompt must instruct the assistant to collect booking data one field per turn.
- **R5.2**: Before `book_appointment` or a cancel/reschedule via `manage_appointment`, the assistant must read back doctor, day, shift, visit type (كشف / استشارة), patient name, and mobile number in digit groups, and obtain an explicit confirmation.
- **R5.3**: The queue number (نمرة الحجز) and fee may only be spoken from the returned tool result.

### R6: Untrusted Data Boundaries
- **R6.1**: The static prompt must include the untrusted-data rules for `<caller_utterance>` and `<retrieved_context>` from the single shared source (`src/agent/messages.py`).
- **R6.2**: The static prompt must contain no secrets, API keys, or credentials.

### R7: Degradation Awareness
- **R7.1**: When `degradation_tier` is `TIER_3_SEARCH_ONLY`, the dynamic context must state that booking is temporarily unavailable and instruct the assistant to provide information and offer the receptionist.
- **R7.2**: When `degradation_tier` is `TIER_4_HUMAN_ESCALATION`, the dynamic context must instruct the assistant to wrap up politely and transfer.
- **R7.3**: For `TIER_1_PRIMARY` / `TIER_2_BACKUP` or `None`, no degradation instruction is added.

### R8: Deterministic Spoken Messages (AR / EN)
- **R8.1**: Provide Arabic and English builders for: greeting, receptionist handoff, tool error fallback, tool filler (>400 ms), emergency, out-of-scope / medical refusal, goodbye, and interruption acknowledgment.
- **R8.2**: The greeting must use "صباح الخير" or "مساء الخير" (Good morning / Good evening) based on Cairo local hour, and include clinic and agent names.
- **R8.3**: The emergency message must include `settings.emergency_phone` (default `123`).
- **R8.4**: An unknown `language` value falls back to Arabic; an unknown tool name in the filler builder returns a generic filler.

### R9: Single Source of Truth & Backward Compatibility
- **R9.1**: `src/agent/messages.py` must not import any `src.*` module.
- **R9.2**: `src/ai_core/guardrails.py` must source its emergency, injection, and medical-refusal response texts and `SYSTEM_UNTRUSTED_DATA_RULES` from `messages.py`; `from src.ai_core.guardrails import SYSTEM_UNTRUSTED_DATA_RULES` must keep working.
- **R9.3**: `src/agent/voice_agent.py` must still import successfully and build a pipeline using `get_system_prompt()`.

---

## 2. Non-Functional Requirements
- **NFR-1 (Token budget)**: The static prompt must be ≤ **1,200 tokens** by the project's estimation method (approx. chars/4 heuristic or the tokenizer already available in the repo), including the 3 few-shot examples.
- **NFR-2 (Latency)**: Building the full prompt (`get_system_prompt`) must take < **5 ms** CPU; no I/O, network, or DB access.
- **NFR-3 (TTS safety)**: All canned messages must be free of Markdown characters (`*`, `#`, `` ` ``, `|`, list bullets) and must pass `OutputGuardrail.validate()`.
- **NFR-4 (Determinism)**: Canned messages are pure functions of their inputs (plus Cairo hour for the greeting when `now` is not supplied).
- **NFR-5 (Encoding)**: Source files are UTF-8; Arabic text renders correctly.

## 3. Constraints
- **C1**: Must not change `src/ai_core/finops.py` or the 8,000 tokens/call budget (open risk R-1, resolved in 5.2/5.3).
- **C2**: Must not register, remove, or rename tools in `voice_agent.py` (Feature 5.3).
- **C3**: Must not change guardrail decision logic (regex patterns, actions, categories) — text sourcing only.
- **C4**: Prompt instructions are defense-in-depth; they must not replace deterministic gates, guardrails, or finops enforcement.
- **C5**: No dynamic values (date/time, caller data, tier) may enter the static prefix.
- **C6**: No new third-party dependencies.
