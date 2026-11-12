# Validation Criteria: Feature 5.3 — Legacy Restaurant Purge & Codebase Sanitization

## 1. Success Definition
Feature 5.3 is successful when every legacy restaurant module, tool registration, schema, alias, config field, session attribute, RAG keyword, and dashboard demo seed is removed from the repository; the tool registry exposes strictly the 5 clinic tools; the dashboard cleanly handles an empty call directory and renders clinic-only session fixtures; and the entire automated test suite and linter pass with zero errors.

## 2. Requirement Traceability
| Requirement | Checks |
|:---|:---|
| R1 | T1.1, T1.2 |
| R2 | T1.3, T1.4, T3.1 |
| R3 | T1.5, T1.6, T3.2 |
| R4 | T1.7, T2.1 |
| R5 | T2.2, T2.3, T3.3 |
| R6 | T1.8 |
| NFR1 | T1.3, T3.1 |
| NFR2 | T4.1, T5.1 |

---

## 3. Verification Tiers

### Tier 1: Unit Verification
- [x] T1.1 — Deleted legacy modules (`src.tools.order_status`, `src.tools.reservation`, `src.tools.legacy_schemas`) raise `ModuleNotFoundError` on import (`tests/test_tools.py`).
- [x] T1.2 — Deleted legacy files (`scripts/ingest_knowledge.py`, `tests/test_order_status.py`, `tests/test_reservation.py`) do not exist on disk (`tests/test_tools.py`).
- [x] T1.3 — `get_registered_tools()`, `get_tool_definitions()`, and `get_session_scoped_tool_definitions()` return exactly the 5 clinic tools: `check_doctor_availability`, `book_appointment`, `manage_appointment`, `search_clinic_knowledge`, `transfer_to_receptionist` (`tests/test_tools.py::test_tool_registry_contains_all_tools`).
- [x] T1.4 — `src.tools.knowledge_search` does not expose `search_restaurant_knowledge` or `async_search_restaurant_knowledge` (`tests/test_knowledge_search.py`).
- [x] T1.5 — `ClinicCallContext` in `src/agent/session_manager.py` has no `order_id`, `reservation_draft`, `dietary_preferences`, or `allergies` fields (`tests/test_session_manager.py`).
- [x] T1.6 — `Settings` in `src/config.py` has no `restaurant_name`, `restaurant_phone`, `restaurant_address`, or `restaurant_hours` attributes (`tests/test_database_engine.py`).
- [x] T1.7 — `src/rag/ingestion.py` and `src/ai_core/cache.py` contain clinic-only keywords and classify `knowledge_base/clinic_kb.md` sections accurately (`tests/test_rag.py`, `tests/test_cache_ladder.py`).
- [x] T1.8 — Repository purity guard scans `src/` and `scripts/` to confirm zero occurrences of `order_status`, `book_reservation`, `search_restaurant_knowledge`, `legacy_schemas`, `restaurant_name`, `restaurant_phone`, `restaurant_address`, `restaurant_hours`, or `reservation_draft` (`tests/test_tools.py`).

### Tier 2: Integration Verification
- [x] T2.1 — Local Qdrant ingestion and retrieval pipeline ingests `knowledge_base/clinic_kb.md` and retrieves grounded clinic chunks (`tests/test_rag.py::test_knowledge_ingestion_pipeline`).
- [x] T2.2 — `load_call_sessions` and `compute_dashboard_analytics` in `src/dashboard/` process persisted clinic `CallSession` fixtures (`bookings`, `escalation`, clinic tool calls) and produce accurate clinic metrics (`tests/test_calls_page.py`, `tests/test_analytics_page.py`).
- [x] T2.3 — `tests/test_architecture_docs.py` verifies `spec/architecture.md` and `spec/adr/` links and file references remain valid after removing legacy files.

### Tier 3: Error & Edge-Case Verification
- [x] T3.1 — Calling `execute_tool` or `async_execute_tool` with `"get_order_status"`, `"book_reservation"`, or `"search_restaurant_knowledge"` returns a graceful `ToolResult(success=False)` for an unregistered tool without raising an unhandled exception (`tests/test_tools.py`).
- [x] T3.2 — Passing legacy field names (`order_id`, `reservation_draft`) to `ClinicCallContext` or `session.update_context()` is ignored/rejected without mutating session state (`tests/test_session_manager.py`).
- [x] T3.3 — When the call storage directory is empty (zero call JSON files), `load_call_sessions(storage_dir=empty_dir)` returns `[]` (no synthetic demo seeds generated) and `compute_dashboard_analytics([])` returns zeroed metrics without raising `ZeroDivisionError` (`tests/test_calls_page.py`, `tests/test_analytics_page.py`).

### Tier 4: Regression Checks
- [x] T4.1 — Full test suite passes: `uv run pytest -v`

### Tier 5: Build, Lint & Type Checks
- [x] T5.1 — `uv run ruff check .` clean
- Type checks: Status: Not Applicable — no type checker (`mypy`/`pyright`) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: Feature 5.3 is a codebase purge and sanitization task verified deterministically by AST/text scans, unit tests, and empty-state/fixture integration tests on the dashboard data layer. Visual Streamlit rendering is covered in Phase 7.

### Tier 7: API / CLI / Application Checks
- [x] T7.1 — `uv run python -c "from src.tools import get_registered_tools; print(sorted(get_registered_tools().keys()))"` prints `['book_appointment', 'check_doctor_availability', 'manage_appointment', 'search_clinic_knowledge', 'transfer_to_receptionist']`.

---

## 4. Automated Execution Commands
```bash
uv run pytest tests/test_tools.py tests/test_rag.py tests/test_knowledge_search.py tests/test_database_engine.py tests/test_session_manager.py tests/test_cache_ladder.py tests/test_calls_page.py tests/test_analytics_page.py tests/test_dashboard_app.py tests/test_architecture_docs.py -v
uv run pytest -v
uv run ruff check .
```

## 5. Execution Results (filled in execute mode)
| Check | Result (✅ / ❌ / ⏭ N/A) | Evidence (command output summary, counts) |
|:---|:---|:---|
| T1.1 | ✅ | `tests/test_tools.py::test_deleted_legacy_modules_raise_module_not_found` PASSED (`importlib.import_module` raises `ModuleNotFoundError` for `src.tools.order_status`, `src.tools.reservation`, `src.tools.legacy_schemas`). |
| T1.2 | ✅ | `tests/test_tools.py::test_deleted_legacy_files_absent_on_disk` PASSED (confirmed `src/tools/order_status.py`, `src/tools/reservation.py`, `src/tools/legacy_schemas.py`, `scripts/ingest_knowledge.py`, `tests/test_order_status.py`, `tests/test_reservation.py` do not exist on disk; plus `src/agent/voice_agent.py`, `scripts/test_call.py`, `tests/test_agent.py` deleted per `git status`). |
| T1.3 | ✅ | `tests/test_tools.py::test_tool_registry_contains_all_tools` & `test_get_tool_definitions_openai_format` PASSED (`get_registered_tools()`, `get_tool_definitions()`, and `get_session_scoped_tool_definitions()` return strictly the 5 clinic tools). |
| T1.4 | ✅ | `tests/test_knowledge_search.py::test_clinic_aliases_and_restaurant_aliases_removed` PASSED (`hasattr(knowledge_search, "search_restaurant_knowledge")` and `hasattr(knowledge_search, "async_search_restaurant_knowledge")` are `False`). |
| T1.5 | ✅ | `tests/test_session_manager.py::test_u13_clinic_call_context_has_no_legacy_restaurant_fields` PASSED (`ClinicCallContext.model_fields` and `to_summary_dict()` contain zero `order_id`, `reservation_draft`, `dietary_preferences`, or `allergies` keys). |
| T1.6 | ✅ | `tests/test_database_engine.py::test_no_legacy_restaurant_attributes_or_aliases` PASSED (`Settings` has no `restaurant_name`, `restaurant_phone`, `restaurant_address`, or `restaurant_hours` attributes/fields). |
| T1.7 | ✅ | `tests/test_rag.py::test_knowledge_ingestion_pipeline` & `tests/test_cache_ladder.py::test_deny_personal_words_ar_en` PASSED (`clinic_kb.md` chunks classified strictly into `VALID_CLINIC_CATEGORIES`; `"my queue number"` denied as personal, `"my reservation"` removed). |
| T1.8 | ✅ | `tests/test_tools.py::test_repository_purity_guard_no_legacy_restaurant_symbols` PASSED (scanned all `.py` files under `src/` and `scripts/` plus `README.md` and `spec/architecture.md` — 0 forbidden legacy restaurant identifiers). |
| T2.1 | ✅ | `tests/test_rag.py::test_knowledge_ingestion_pipeline` PASSED (ingested `knowledge_base/clinic_kb.md` into local Qdrant and retrieved grounded clinic chunks). |
| T2.2 | ✅ | `tests/test_calls_page.py` (12 passed), `tests/test_analytics_page.py` (14 passed), `tests/test_dashboard_app.py` (11 passed) — persisted clinic `CallSession` fixtures (`BookingRef`, `EscalationInfo`, clinic tools) load and render accurate clinic KPIs and tables. |
| T2.3 | ✅ | `tests/test_architecture_docs.py` (22 passed, including `test_architecture_doc_mermaid_diagrams_and_clinic_purity`) — all ADR links, code references, and 6 Mermaid diagrams valid with zero legacy restaurant artifact references. |
| T3.1 | ✅ | `tests/test_tools.py::test_execute_unregistered_and_legacy_tools` & `test_async_execute_tool_unregistered_and_legacy` PASSED (`get_order_status`, `book_reservation`, `search_restaurant_knowledge` return `ToolResult(success=False)` gracefully without raising). |
| T3.2 | ✅ | `tests/test_session_manager.py::test_e8_legacy_restaurant_fields_ignored_without_mutating_session` PASSED (`ClinicCallContext` ignores unknown legacy fields and `session.update_context(order_id=..., reservation_draft=...)` does not mutate session state). |
| T3.3 | ✅ | `tests/test_calls_page.py::TestCallsPageTier3EdgeCases::test_empty_storage_returns_empty_list_without_seeding` & `tests/test_analytics_page.py::TestAnalyticsTier3EdgeCases::test_zero_calls_graceful_kpis` PASSED (`load_call_sessions(empty_dir)` returns `[]` with 0 files created on disk; `compute_dashboard_analytics([])` returns zeroed KPIs with no `ZeroDivisionError`). |
| T4.1 | ✅ | `uv run pytest -v` → `533 passed, 1 skipped, 3 warnings in 71.43s` (exit code `0`; targeted Feature 5.3 suite: `160 passed in 20.33s`; `test_i3_voice_pipeline_instructions_use_clinic_prompt` skipped via `importorskip` until Feature 5.4 recreates `src/agent/voice_agent.py`). |
| T5.1 | ✅ | `uv run ruff check .` → `All checks passed!` (exit code `0`; type checks N/A per `pyproject.toml`). |
| T6 | ⏭ N/A | Technical justification documented in §3 Tier 6 (codebase purge & sanitization verified via deterministic AST/text scans, unit/integration fixtures, and AppTest headless checks). |
| T7.1 | ✅ | `uv run python -c "from src.tools import get_registered_tools; print(sorted(get_registered_tools().keys()))"` → `['book_appointment', 'check_doctor_availability', 'manage_appointment', 'search_clinic_knowledge', 'transfer_to_receptionist']` (exit code `0`). |
