# Requirements: Feature 5.3 — Legacy Restaurant Purge & Codebase Sanitization

> Decisions and behaviours, not implementation micro-details. Every requirement must be testable and map to at least one check in `validation.md`.

## 1. Functional Requirements
| ID | Requirement | Validated by |
|:---|:---|:---|
| R1 | **Legacy Tool & Module Deletion**: `src/tools/order_status.py`, `src/tools/reservation.py`, `src/tools/legacy_schemas.py`, `scripts/ingest_knowledge.py`, `src/agent/voice_agent.py`, `scripts/test_call.py`, `tests/test_order_status.py`, `tests/test_reservation.py`, and `tests/test_agent.py` must be removed from the repository. | Tier 1 – T1.1, T1.2 |
| R2 | **Clinic-Only Tool Registry**: `TOOL_REGISTRY`, `get_registered_tools()`, `get_tool_definitions()`, and `get_session_scoped_tool_definitions()` in `src/tools/__init__.py` must register and return **only** the 5 clinic tools (`check_doctor_availability`, `book_appointment`, `manage_appointment`, `search_clinic_knowledge`, `transfer_to_receptionist`). `src/tools/knowledge_search.py` must not export `search_restaurant_knowledge` or `async_search_restaurant_knowledge`. | Tier 1 – T1.3, T1.4; Tier 3 – T3.1 |
| R3 | **Session Context & Config Purity**: `ClinicCallContext` in `src/agent/session_manager.py` must not define legacy restaurant fields (`order_id`, `reservation_draft`, `dietary_preferences`, `allergies`), and `CallSession.record_tool_call()` must only track clinic tool outcomes. `Settings` in `src/config.py` must not define `restaurant_name`, `restaurant_phone`, `restaurant_address`, or `restaurant_hours` or map them via validator aliases. | Tier 1 – T1.5, T1.6; Tier 3 – T3.2 |
| R4 | **RAG & Cache Keyword Sanitization**: `src/rag/ingestion.py`, `src/rag/retriever.py`, and `src/ai_core/cache.py` must contain only clinic-domain keywords and documentation, with all restaurant/menu/table-reservation keywords removed. | Tier 1 – T1.7; Tier 2 – T2.1 |
| R5 | **Dashboard Demo Seed Removal & Clinic UI**: `src/dashboard/calls_data.py` must not generate synthetic/demo restaurant calls and must return an empty list when no persisted call JSON files exist in the storage directory. `src/dashboard/analytics_data.py`, `src/dashboard/i18n.py`, `src/dashboard/app.py`, and `src/dashboard/pages/01_calls.py` must reference clinic settings (`clinic_name`), clinic tools, and clinic session context fields (`bookings`, `escalation`, `patient_name`, `doctor_name`, `specialty`). | Tier 2 – T2.2, T2.3; Tier 3 – T3.3 |
| R6 | **Codebase & Documentation Purity Guard**: Active runtime modules under `src/`, `scripts/`, `README.md`, and `spec/architecture.md` must contain zero references to legacy restaurant tool names (`get_order_status`, `book_reservation`, `search_restaurant_knowledge`, `legacy_schemas`) or `restaurant_*` config attributes. | Tier 1 – T1.8 |

## 2. Non-Functional Requirements
| ID | Requirement | Validated by |
|:---|:---|:---|
| NFR1 | **Caller Tool Allowlist Safety (`spec/tech.md` §10)**: Removing non-clinic tools from `TOOL_REGISTRY` must ensure that an unprivileged `caller` session can never discover or invoke any restaurant tool schema or callable. | Tier 1 – T1.3; Tier 3 – T3.1 |
| NFR2 | **Zero Regression on Clinic Test Suite**: All existing clinic database, RAG, tool, AI core, prompt, session manager, and updated dashboard tests must pass with zero lint errors. | Tier 4 – T4.1; Tier 5 – T5.1 |

## 3. Constraints (must NOT do / change)
- C1: Must respect `spec/tech.md` §5 (Tool Execution & Error Resilience), §6 (Session State & Privacy Separation), and §10 (Identity & Tenant Isolation).
- C2: Must **not** alter the behavior, input/output schemas, or safety gates of the 5 clinic tools (`check_doctor_availability`, `book_appointment`, `manage_appointment`, `search_clinic_knowledge`, `transfer_to_receptionist`).
- C3: Must **not** remove negative safety assertions in `tests/test_prompts.py` or `tests/test_human_handoff.py` that check prompts/messages for the absence of forbidden restaurant words.
- C4: Must **not** edit historical completed feature specs (`spec/features/feature-102..512-*`) or `spec/archive/`.

## 4. Dependencies & Assumptions
- **Depends on**: Features 1.2–5.2 (all completed on `main`).
- **Assumptions**: No persisted legacy restaurant JSON files in `data/calls/` need migration (confirmed by human in Q3/Q5).
