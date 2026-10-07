# Validation Criteria: Feature 5.2 — Call Logs, Audio Playback & Transcript Viewer

## 1. Success Definition
Success is proven when an operator can open the Streamlit Call Logs page (`src/dashboard/pages/01_calls.py`), filter and select call sessions loaded from disk or auto-seeded demo storage, inspect conversation transcripts formatted in bilingual chat bubbles with per-turn latency indicators, review tool execution arguments and outputs, and play call audio without unhandled errors or layout distortion.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Target Module**: `src/dashboard/calls_data.py` and `src/dashboard/i18n.py`
- **Verification Cases**:
  - `test_seed_sessions_creation`: Verify that `seed_demo_calls()` produces valid `CallSession` instances conforming to `src.agent.session_manager` schemas with both Arabic and English conversations.
  - `test_session_filtering_logic`: Verify that filtering by status (`active`, `ended`, `escalated`), language (`ar`, `en`), and query string (phone, order ID, text) returns exact matches.
  - `test_audio_resolver_with_existing_file`: Verify that `resolve_call_audio()` detects an audio file on disk (`.wav` or `.mp3`) and returns the file path.
  - `test_audio_resolver_synthetic_fallback`: Verify that `resolve_call_audio()` returns valid synthetic fallback audio bytes and a fallback flag when no file exists on disk.
  - `test_i18n_calls_page_keys`: Verify that all new translation keys introduced for the calls page exist in both `en` and `ar` dictionaries in `src/dashboard/i18n.py`.

### Tier 2: Integration Verification
- **Target Module**: `src/dashboard/pages/01_calls.py` via `streamlit.testing.v1.AppTest`
- **Verification Cases**:
  - `test_calls_page_renders_cleanly`: Run `AppTest.from_file("src/dashboard/pages/01_calls.py")` and verify `at.exception` is completely empty.
  - `test_calls_page_displays_table_and_metrics`: Verify summary KPI cards and call list are rendered.
  - `test_calls_page_session_selection`: Simulate selecting a specific call session ID and verify that detail components (chat transcript, customer slots, tool cards) render correctly.
  - `test_calls_page_language_toggle`: Switch `session_state.lang` to `ar` and verify that localized headers and RTL containers render properly.

### Tier 3: Error & Edge-Case Verification
- **Target Module**: `src/dashboard/calls_data.py` & `src/dashboard/pages/01_calls.py`
- **Verification Cases**:
  - `test_empty_storage_triggers_auto_seed`: Ensure an empty `data/calls/` directory automatically seeds demo sessions without throwing errors.
  - `test_corrupted_json_file_handled_gracefully`: Place a malformed JSON file into `data/calls/` and verify that the loader logs a warning, skips the broken file, and does not crash the UI.
  - `test_call_with_no_messages`: Verify that a session with an empty `messages` list renders an informative "No conversation turns recorded" placeholder instead of throwing an index error.
  - `test_tool_turn_without_result`: Verify that a turn with `role == TOOL` but null `tool_result` renders cleanly with a pending/empty badge.

### Tier 4: Regression Checks
- **Target Suite**: All existing project test suites (`tests/test_rag.py`, `tests/test_tools.py`, `tests/test_agent.py`, `tests/test_dashboard_app.py`)
- **Verification Rule**: Zero regressions. All existing 25+ tests must continue to pass 100% green without modification.

### Tier 5: Build, Lint & Type Checks
- **Scope**: Repository-wide Python syntax and type check.
- **Verification Command**: Run `uv run pytest tests/` and verify clean importability of all dashboard modules.

### Tier 6: Manual / Visual Verification
- **Test Protocol**:
  1. Launch Streamlit dashboard:
     ```powershell
     uv run streamlit run src/dashboard/app.py
     ```
  2. Navigate via sidebar to **01_calls** (or directly `uv run streamlit run src/dashboard/pages/01_calls.py`).
  3. Verify the Call History Table:
     - Check status badges (Green for Ended/Success, Amber for Active, Red for Escalated).
     - Test the search bar: type "ORD-7821" and confirm filtering works.
     - Switch filter from "All" to "Escalated" and verify filtered rows.
  4. Inspect Call Details:
     - Select a call from the selector.
     - Verify customer card (Name, Phone, Sentiment, Order ID).
     - Test Audio Player: press Play and verify sound plays (recording or demo synth).
     - Inspect Chat Transcript: verify user turns and assistant turns are distinct.
     - Expand a Tool Call accordion: verify input parameters and JSON output.
     - Check per-turn latency badge (STT / LLM / TTS ms).
  5. Toggle language to Arabic:
     - Verify RTL orientation, Cairo font, and translated labels.

### Tier 7: API / CLI / Application Checks
- **Test Protocol**:
  - Verify that persisting a live session via `session_manager.save_session()` makes it immediately discoverable and readable by `calls_data.py`.

---

## 3. Automated Execution Commands
```powershell
# Run the complete test suite for the Call Logs & Transcript Viewer feature
uv run pytest tests/test_calls_page.py -v --tb=short

# Run full project regression check
uv run pytest tests/ -v --tb=short
```
