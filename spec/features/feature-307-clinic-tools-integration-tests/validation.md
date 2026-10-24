# Validation Criteria: Feature 3.7 — Automated Unit & Integration Tests for Medical Tools

## 1. Success Definition
Feature 3.7 is successful when `tests/test_clinic_tools.py` exists, covers R1–R19, passes fully via `uv run pytest`, does not introduce regressions in the existing suite, passes `ruff`, and any production defect it exposed is fixed minimally and documented.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- [ ] Registry contract tests (R1–R4): registered names, schema binding, OpenAI definition shape, no internal params leaked, callables route to singletons.
- [ ] Harness sanity: frozen clock is effective in every tool module (date returned by availability equals frozen `TODAY` offset).

### Tier 2: Integration Verification
- [ ] Booking, reschedule, cancel and capacity journeys through `async_execute_tool` on a seeded temp SQLite DB (R5–R8).
- [ ] Cross-tool consistency of remaining slots and booking codes (R9–R10).
- [ ] Escalation ticket persisted and readable via `ClinicRepository` (R12).
- [ ] Knowledge search through dispatcher on in-memory Qdrant built from `clinic_kb.md` (R14–R15).

### Tier 3: Error & Edge-Case Verification
- [ ] Concurrent bookings on capacity-2 shift → exactly 2 successes, unique queue numbers (R11).
- [ ] No-availability booking offers reception (R13).
- [ ] Parametrized invalid / empty payloads for all 5 tools on both dispatchers → `ToolResult`, no exception, Arabic message, `error` present on failure (R16–R17).
- [ ] Wrong phone + valid booking code rejected (R10).
- [ ] No raw phone in captured logs (R19).

### Tier 4: Regression Checks
- [ ] Full existing suite passes with the same results as the pre-feature baseline (known pre-existing legacy failures, if any, listed explicitly and unchanged).
- [ ] If any `src/tools/*` file is touched (D2), its own per-tool test file passes.
- **Recorded baseline (2026-10-23, before Feature 3.7)**: `280 passed, 2 failed, 15 errors`.
  - Pre-existing failures (out of scope, must stay unchanged — not grow):
    - `tests/test_database_engine.py::test_clinic_settings_defaults`
    - `tests/test_rag.py::test_knowledge_ingestion_pipeline` (legacy restaurant KB)
    - `tests/test_agent.py` — 15 errors (`FileNotFoundError`, legacy Phase 5 debt)
  - Expected after feature: `280 + N new passed`, same 2 failed / 15 errors.

### Tier 5: Build, Lint & Type Checks
- [ ] `ruff check` and `ruff format --check` pass on the new test file and any touched source file.
- **Type checks**: Not Applicable — **Technical Justification**: no type checker (mypy/pyright) is configured in `pyproject.toml` or installed in the project environment; adding one would violate constraint C1.
- **Build**: Not Applicable — **Technical Justification**: pure Python project with no compile/bundle step; importability is proven by pytest collection.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: the feature adds only automated backend tests; there is no UI, audio, or visual output to inspect. Human review is limited to reading the pytest report.

### Tier 7: API / CLI / Application Checks
- [ ] Run the suite via the project CLI (`uv run pytest`) and inspect the verbose output showing each journey test name and result.
- [ ] `--durations` report confirms NFR-3 (file < 60s) and no single dispatcher call test is anomalously slow (NFR-4).

---

## 3. Automated Execution Commands
```powershell
# New suite (verbose + timings)
uv run pytest tests/test_clinic_tools.py -v --durations=10

# Per-tool suites (regression for Phase 3)
uv run pytest tests/test_medical_schemas.py tests/test_doctor_availability.py tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_knowledge_search.py tests/test_human_handoff.py tests/test_escalation_repository.py tests/test_tools.py -q

# Full regression
uv run pytest -q

# Lint & format
uv run ruff check tests/test_clinic_tools.py src/tools
uv run ruff format --check tests/test_clinic_tools.py src/tools
```
