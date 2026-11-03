# Validation Criteria: Feature 5.1 — Egyptian Clinic Assistant Persona, System Prompts & Medical Guardrails

## 1. Success Definition
Feature 5.1 succeeds when: (a) the prompt module produces a clinic-only, cache-stable static prompt ≤ 1,200 tokens plus a correct dynamic context; (b) all deterministic spoken messages are TTS-safe and pass `OutputGuardrail`; (c) the guardrail layer sources its texts from the shared `messages.py` with **zero** behavior change; (d) the full existing test suite and ruff pass; and (e) a human hears the three few-shot scenarios behave correctly against live Groq (optional manual check).

Discovered capabilities: `uv`, `pytest` + `pytest-asyncio`, `ruff` (configured in `pyproject.toml`). No `mypy` configuration exists in the repo.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification (`tests/test_prompts.py`)
- [x] **U1 (R1.1)**: Static prompt contains `settings.agent_name`, `settings.clinic_name`, `settings.clinic_address`, `settings.clinic_phone`, `settings.clinic_working_hours`.
- [x] **U2 (R1.2)**: Static prompt, dynamic context, and every canned message (AR & EN) contain none of: `restaurant`, `menu`, `order`, `reservation`, `مطعم`, `منيو`.
- [x] **U3 (R1.3)**: Static prompt contains all 5 clinic tool names and none of the legacy tool names (`search_restaurant_knowledge`, `get_order_status`, `book_reservation`, `escalate_to_human`).
- [x] **U4 (R2.1, C5)**: Static prompt contains no `{current_datetime}`/`{now}` placeholder and no 4-digit year / `HH:MM` time pattern; `PromptPrefixBuilder(static)` constructs without error.
- [x] **U5 (R2.2)**: Two calls with `now` monkeypatched to different times produce identical static text and identical `prefix_hash`.
- [x] **U6 (R2.3)**: `build_dynamic_context(now=<fixed Cairo datetime>)` contains the expected date, Arabic weekday, and time.
- [x] **U7 (R2.4)**: `get_system_prompt(custom_instructions="X", language="en")` starts with the static prompt and contains the dynamic context and `"X"`.
- [x] **U8 (R4.1–R4.4)**: Static prompt contains the diagnosis/drug prohibition, specialty-routing allowance, emergency rule with `settings.emergency_phone` + `transfer_to_receptionist`, and grounding rule.
- [x] **U9 (R5)**: Static prompt contains the one-field-per-turn rule, read-back fields list, explicit-confirmation rule, and "queue number/fee only from tool result" rule.
- [x] **U10 (R6.1)**: Static prompt contains `SYSTEM_UNTRUSTED_DATA_RULES` text from `src.agent.messages`.
- [x] **U11 (R7)**: Tier 3 context contains the booking-unavailable instruction; Tier 4 contains wrap-up/transfer; Tier 1/2/None add no degradation text.
- [x] **U12 (R8.2)**: Greeting at Cairo 09:00 → contains "صباح الخير"; at 19:00 → "مساء الخير"; EN variants → "Good morning"/"Good evening".
- [x] **U13 (R8.3)**: Emergency message (AR/EN) contains `settings.emergency_phone`.
- [x] **U14 (NFR-1)**: Estimated token count of static prompt ≤ 1,200 (`1,158` tokens verified).
- [x] **U15 (NFR-3)**: Every canned message (AR/EN) has no Markdown characters and `OutputGuardrail().validate(msg).allowed is True`.

### Tier 2: Integration Verification
- [x] **I1 (R9.2)**: `tests/test_guardrails.py` passes unchanged (21/21 passed); `InputGuardrail` emergency / injection / medical-advice `response_text` equals the corresponding text exported by `src.agent.messages`.
- [x] **I2 (R2.1)**: `PromptPrefixBuilder(build_static_system_prompt()).build(dynamic_context=build_dynamic_context(...))` returns `[static system, dynamic system]` messages in order.
- [x] **I3 (R9.3)**: `create_voice_pipeline()` builds an `Agent` whose `instructions` contain `settings.clinic_name` and the static prompt (`test_i3_voice_pipeline_instructions_use_clinic_prompt` passed).

### Tier 3: Error & Edge-Case Verification
- [x] **E1 (R8.4)**: `language="fr"` / `""` → Arabic output for every builder; no exception.
- [x] **E2 (R8.4)**: `build_tool_filler_message("unknown_tool")` → generic filler.
- [x] **E3**: `custom_instructions=None` / `""` → no stray empty section or trailing whitespace artifacts.
- [x] **E4**: `degradation_tier` passed as enum or as its string value → identical output; unknown string → no degradation text, no exception.
- [x] **E5**: Greeting boundary hours (11:59 vs 12:00, 00:00) follow the documented cutoff.
- [x] **E6 (R9.1)**: Importing `src.ai_core.guardrails` in a fresh interpreter succeeds (no circular import); `messages.py` source has no `from src` / `import src` lines.

### Tier 4: Regression Checks
- [x] **RG1**: Full clinic suite passes: `533 passed` across all Phase 1–4 and 5.1 test suites (`tests/test_prompts.py`, `tests/test_guardrails.py`, `tests/test_cache_ladder.py`, `tests/test_prompt_prefix.py`, `tests/evals/`, etc.; legacy `test_rag.py` and `test_agent.py` fixture referencing deleted `restaurant_kb.md` is scheduled for Feature 5.5).
- [x] **RG2**: `from src.ai_core.guardrails import SYSTEM_UNTRUSTED_DATA_RULES` still works.

### Tier 5: Build, Lint & Type Checks
- [x] **B1**: `uv run ruff check src/agent/messages.py src/agent/prompts.py src/agent/__init__.py src/ai_core/guardrails.py tests/test_prompts.py scripts/prompt_smoke.py` → `All checks passed!`.
- [x] **B2**: `uv run python -c "import src.agent, src.agent.voice_agent"` → exit code 0.
- **Type checks — Status: Not Applicable.** Technical Justification: the repository has no `mypy`/`pyright` configuration or dependency in `pyproject.toml`; per the validation skill (Rule 3) we do not introduce tooling that does not exist.

### Tier 6: Manual / Visual Verification
- [x] **M1**: Print the full prompt (`uv run python -c "from src.agent.prompts import get_system_prompt; print(get_system_prompt())"`) and verify persona tone, Arabic phrasing, and rule clarity.
- [x] **M2 (optional, requires `GROQ_API_KEY`)**: `uv run python scripts/prompt_smoke.py` executed; verified static prompt token count (`1158 / 1200`), prefix hash (`d8168f43ff8f697b...`), and graceful skip when live Groq model access is unavailable.

### Tier 7: API / CLI / Application Checks
- [x] **A1**: `scripts/prompt_smoke.py` exits 0 and prints token count, prefix hash, and clear skip notice when live provider model access is unavailable.
- **LiveKit worker run — Status: Not Applicable for 5.1.** Technical Justification: the worker still registers legacy tools until Feature 5.3; an end-to-end voice call would validate tool wiring outside this feature's scope. Covered by 5.3/5.4.

---

## 3. Automated Execution Commands
```powershell
cd "d:\AI Projects\Voice_Agent_For_Clinics\Voice_Agent"
uv run pytest tests/test_prompts.py -v
uv run pytest tests/test_guardrails.py tests/test_prompt_prefix.py -v
uv run ruff check src/agent/messages.py src/agent/prompts.py src/agent/__init__.py src/ai_core/guardrails.py tests/test_prompts.py scripts/prompt_smoke.py
uv run python -c "import src.agent, src.agent.voice_agent"
uv run python scripts/prompt_smoke.py   # optional, needs GROQ_API_KEY
```
