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
- [ ] T1.1 — Deleted legacy modules (`src.tools.order_status`, `src.tools.reservation`, `src.tools.legacy_schemas`) raise `ModuleNotFoundError` on import (`tests/test_tools.py`).
- [ ] T1.2 — Deleted legacy files (`scripts/ingest_knowledge.py`, `tests/test_order_status.py`, `tests/test_reservation.py`) do not exist on disk (`tests/test_tools.py`).
- [ ] T1.3 — `get_registered_tools()`, `get_tool_definitions()`, and `get_session_scoped_tool_definitions()` return exactly the 5 clinic tools: `check_doctor_availability`, `book_appointment`, `manage_appointment`, `search_clinic_knowledge`, `transfer_to_receptionist` (`tests/test_tools.py::test_tool_registry_contains_all_tools`).
- [ ] T1.4 — `src.tools.knowledge_search` does not expose `search_restaurant_knowledge` or `async_search_restaurant_knowledge` (`tests/test_knowledge_search.py`).
- [ ] T1.5 — `ClinicCallContext` in `src/agent/session_manager.py` has no `order_id`, `reservation_draft`, `dietary_preferences`, or `allergies` fields (`tests/test_session_manager.py`).
- [ ] T1.6 — `Settings` in `src/config.py` has no `restaurant_name`, `restaurant_phone`, `restaurant_address`, or `restaurant_hours` attributes (`tests/test_database_engine.py`).
- [ ] T1.7 — `src/rag/ingestion.py` and `src/ai_core/cache.py` contain clinic-only keywords and classify `knowledge_base/clinic_kb.md` sections accurately (`tests/test_rag.py`, `tests/test_cache_ladder.py`).
- [ ] T1.8 — Repository purity guard scans `src/` and `scripts/` to confirm zero occurrences of `order_status`, `book_reservation`, `search_restaurant_knowledge`, `legacy_schemas`, `restaurant_name`, `restaurant_phone`, `restaurant_address`, `restaurant_hours`, or `reservation_draft` (`tests/test_tools.py`).

### Tier 2: Integration Verification
- [ ] T2.1 — Local Qdrant ingestion and retrieval pipeline ingests `knowledge_base/clinic_kb.md` and retrieves grounded clinic chunks (`tests/test_rag.py::test_knowledge_ingestion_pipeline`).
- [ ] T2.2 — `load_call_sessions` and `compute_dashboard_analytics` in `src/dashboard/` process persisted clinic `CallSession` fixtures (`bookings`, `escalation`, clinic tool calls) and produce accurate clinic metrics (`tests/test_calls_page.py`, `tests/test_analytics_page.py`).
- [ ] T2.3 — `tests/test_architecture_docs.py` verifies `spec/architecture.md` and `spec/adr/` links and file references remain valid after removing legacy files.

### Tier 3: Error & Edge-Case Verification
- [ ] T3.1 — Calling `execute_tool` or `async_execute_tool` with `"get_order_status"`, `"book_reservation"`, or `"search_restaurant_knowledge"` returns a graceful `ToolResult(success=False)` for an unregistered tool without raising an unhandled exception (`tests/test_tools.py`).
- [ ] T3.2 — Passing legacy field names (`order_id`, `reservation_draft`) to `ClinicCallContext` or `session.update_context()` is ignored/rejected without mutating session state (`tests/test_session_manager.py`).
- [ ] T3.3 — When the call storage directory is empty (zero call JSON files), `load_call_sessions(storage_dir=empty_dir)` returns `[]` (no synthetic demo seeds generated) and `compute_dashboard_analytics([])` returns zeroed metrics without raising `ZeroDivisionError` (`tests/test_calls_page.py`, `tests/test_analytics_page.py`).

### Tier 4: Regression Checks
- [ ] T4.1 — Full test suite passes: `uv run pytest -v`

### Tier 5: Build, Lint & Type Checks
- [ ] T5.1 — `uv run ruff check .` clean
- Type checks: Status: Not Applicable — no type checker (`mypy`/`pyright`) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: Feature 5.3 is a codebase purge and sanitization task verified deterministically by AST/text scans, unit tests, and empty-state/fixture integration tests on the dashboard data layer. Visual Streamlit rendering is covered in Phase 7.

### Tier 7: API / CLI / Application Checks
- [ ] T7.1 — `uv run python -c "from src.tools import get_registered_tools; print(sorted(get_registered_tools().keys()))"` prints `['book_appointment', 'check_doctor_availability', 'manage_appointment', 'search_clinic_knowledge', 'transfer_to_receptionist']`.

---

## 4. Automated Execution Commands
```bash
uv run pytest tests/test_tools.py tests/test_rag.py tests/test_knowledge_search.py tests/test_database_engine.py tests/test_session_manager.py tests/test_calls_page.py tests/test_analytics_page.py tests/test_architecture_docs.py -v
uv run pytest -v
uv run ruff check .
```

## 5. Execution Results (filled in execute mode)
| Check | Result (✅ / ❌ / ⏭ N/A) | Evidence (command output summary, counts) |
|:---|:---|:---|
