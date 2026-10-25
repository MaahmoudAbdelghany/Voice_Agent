# Validation Criteria: Feature 3.6 — Human Receptionist Escalation Tool with Dashboard Alert (`src/tools/human_handoff.py`)

## 1. Success Definition
The feature is complete when: `transfer_to_receptionist` creates persistent tickets in the `escalations` table with `ESC-YYYYMMDD-NNNN` IDs; emergency phrases are always upgraded to `emergency` with a 123 message and `status=transferred` at any hour; non-emergency calls are `queued` with a deterministic wait during reception hours and `callback` outside them; repeated calls from the same phone within 10 minutes reuse (and only upgrade) the ticket; DB failures/timeouts still return a reassuring transfer result with `persisted=False`; the repository exposes open-ticket listing/counting/status updates for the dashboard; the tool is registered (legacy `escalate_to_human` entry removed, aliases importable); and unit, integration, edge-case, regression, lint, and CLI checks pass.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: pure helpers, no DB. File: `tests/test_human_handoff.py`.
- **Test cases**:
  - `test_detect_emergency_positive` (parametrized): `"عندي ألم جامد في صدري"`, `"مش قادر أتنفس"`, `"ابني بينزف جامد"`, `"والدي أغمى عليه"`, `"عنده تشنجات"`, `"chest pain"`, MSA `"ضيق في التنفس"`, with tashkeel/hamza variants → `True`.
  - `test_detect_emergency_negative`: `"عايز أكلم حد من الاستقبال"`, `"عندي شكوى في الحساب"`, `"عايز أغير ميعاد الكشف"` → `False`.
  - `test_is_reception_open`: Saturday 08:59 → False; 09:00 → True; 21:59 → True; 22:00 → False; Friday 13:59 → False; Friday 14:00 → True (Cairo-aware datetimes).
  - `test_estimate_wait_seconds`: emergency → 0; urgent/0 ahead → 30; medium/2 ahead → 120; low/0 → 120; medium/50 ahead → 600 (cap).
  - `test_ticket_id_format`: generator for 2026-10-24 seq 7 → `ESC-20261024-0007`.
  - `test_mask_phone_for_speech`: `"01012345678"` → only last 3 digits present in spoken text.
  - `test_messages_no_markdown_no_restaurant_words`: all message builders → no `*`, `#`, `|`; none of `مطعم`, `مطبخ`, `توصيل`, `شيف`; length ≤ 300.
  - `test_legacy_value_mapping`: `high`→`urgent`, `critical`→`emergency`, `kitchen_manager`→`reception`, `billing`→`billing`.

### Tier 2: Integration Verification
- **Scope**: tool → `ClinicRepository` → real async SQLAlchemy on an isolated **file-based SQLite** DB in `tmp_path` (same fixture style as `tests/test_manage_appointment.py`); Cairo clock patched; `timeout_s` set generously (e.g. 5s) except for the timeout test.
- **Test cases** (`tests/test_human_handoff.py`):
  - `test_queued_during_hours_persists_ticket`: Saturday 10:00, medium/reception → `success=True`, `status="queued"`, `transfer_requested=True`, `persisted=True`, ID matches `ESC-\d{8}-\d{4}`, row exists in `escalations` with same fields and `session_id` when given.
  - `test_emergency_upgrade_overrides_llm`: reason `"عندي ألم في صدري ومش قادر أتنفس"` with `urgency="low"`, `department="billing"` → stored `urgency=emergency`, `department=emergency`, `status=transferred`, wait 0, message contains `123`, `emergency_detected=True`.
  - `test_emergency_outside_hours_still_transferred`: same at 02:00 → `transferred`, not `callback`.
  - `test_llm_emergency_not_downgraded`: `urgency="emergency"` with neutral reason → stays `emergency`.
  - `test_callback_outside_hours_with_phone`: 23:00, medium → `status="callback"`, `transfer_requested=False`, `needs_phone=False`, message has masked phone + reception hours.
  - `test_callback_outside_hours_without_phone`: → `needs_phone=True`, message asks for mobile number.
  - `test_wait_grows_with_open_queue`: create 2 open medium tickets (different phones), then a third → wait = 60 + 2×30 = 120.
  - `test_dedup_same_phone_within_10_min`: two calls same phone 3 min apart → same `ticket_id`, second `deduplicated=True`, exactly 1 row.
  - `test_dedup_upgrades_priority`: first medium, second emergency phrase → same ticket now `emergency` / `transferred`; summary contains second reason.
  - `test_dedup_never_downgrades`: first urgent, second low → remains urgent.
  - `test_no_dedup_after_10_min_or_without_phone`: 11 min later → new ticket; two calls without phone → 2 rows.
  - `test_daily_sequence_increments`: 3 tickets same day → `…-0001`, `…-0002`, `…-0003`.
  - `test_sync_and_async_execution`: `execute` and `aexecute` both return `ToolResult` with persisted tickets (sync called both inside and outside a running loop).
  - `test_registry_dispatch` (`tests/test_tools.py`): `execute_tool("transfer_to_receptionist", {...})` → `success=True`, `data["ticket_id"]` present; registry has `transfer_to_receptionist` with the 3.1 schemas and no `escalate_to_human`.
- **Repository** (`tests/test_escalation_repository.py`):
  - `test_create_and_find_recent_open`, `test_count_open_with_min_urgency`, `test_list_open_order_emergency_first_then_oldest`, `test_update_status_acknowledged_and_resolved_sets_timestamps`, `test_resolved_excluded_from_open_lists`.

### Tier 3: Error & Edge-Case Verification
- **Test cases**:
  - `test_db_exception_falls_back_to_temp_ticket`: session factory raising `OperationalError` → `success=True`, `persisted=False`, ID starts `ESC-TMP-`, message still reassuring; no exception.
  - `test_db_timeout_falls_back`: repository stub sleeping 1s with `timeout_s=0.05` → returns in < 0.5s with `persisted=False`.
  - `test_empty_reason_direct_call_uses_default`: `reason="   "` → `success=True`, stored reason is the default text.
  - `test_unknown_enum_values_direct_call`: `department="kitchen"`, `urgency="weird"` → `reception` / `medium`.
  - `test_malformed_phone_kept`: `caller_phone="12345"` → escalation succeeds; phone stored as given.
  - `test_schema_rejects_short_reason_via_dispatcher`: `execute_tool` with `reason="x"` → `success=False`, no exception (documented risk 6).
  - `test_update_status_unknown_ticket_raises` / `test_resolved_cannot_reopen` (repository).
  - `test_summary_append_bounded`: repeated dedup appends keep summary ≤ 1000 chars.
  - `test_no_pii_in_info_logs`: `caplog` at INFO → phone, name, reason not present.
  - `test_deprecated_aliases_importable`: `HumanHandoffTool`, `human_handoff_tool`, `escalate_to_human`, `async_escalate_to_human` import from `src.tools.human_handoff` and `src.tools`; `escalate_to_human(reason=..., customer_phone=..., urgency="critical")` → `ToolResult` with `urgency="emergency"`.

### Tier 4: Regression Checks
- Must still pass: `tests/test_database.py`, `tests/test_database_models.py`, `tests/test_clinic_repository.py`, `tests/test_medical_schemas.py`, `tests/test_doctor_availability.py`, `tests/test_appointment_booking.py`, `tests/test_manage_appointment.py`, `tests/test_knowledge_search.py`, `tests/test_tools.py` (modified), `tests/test_session_manager.py`, `tests/test_prompts.py`.
- Seeder/`init_db` on a fresh SQLite file creates the new `escalations` table alongside existing ones without errors.
- **Known pre-existing legacy failures (not regressions)**: `tests/test_rag.py` (restaurant KB missing), `tests/test_database_engine.py` (3.4 baseline), `tests/test_agent.py` (livekit DLL / restaurant tool assertions — Phase 5 debt). Baseline is recorded before implementation and compared after.

### Tier 5: Build, Lint & Type Checks
- `uv run ruff check src/tools/human_handoff.py src/tools/__init__.py src/db/models.py src/db/schemas.py src/db/repository.py src/db/__init__.py src/config.py tests/test_human_handoff.py tests/test_escalation_repository.py tests/test_tools.py`
- `uv run ruff format --check src/tools/human_handoff.py tests/test_human_handoff.py tests/test_escalation_repository.py`
- Build: `uv run python -c "import src.tools, src.db"` imports cleanly.
- Type checking: **Not Applicable** — no type checker (mypy/pyright) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable (UI) — this feature adds no dashboard UI (deferred to Feature 7.5 per D9) and produces no audio. The supervisor reviews the spoken messages printed by the Tier 7 CLI checks for tone, politeness, and correctness of the 123 guidance.

### Tier 7: API / CLI / Application Checks
- **Live dispatcher calls on the real dev DB** (`data/clinic.db`, after `init_db` creates the table):
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "import asyncio; from src.db.session import init_db; asyncio.run(init_db()); from src.tools import execute_tool as e; [print(a['reason'], '->', (r:=e('transfer_to_receptionist', a)).data['status'], r.data['urgency'], r.data['ticket_id'], r.data['persisted'], '|', r.message) for a in [{'reason':'عايز أكلم حد من الاستقبال','caller_phone':'01012345678','caller_name':'منى'}, {'reason':'والدي عنده ألم جامد في صدره ومش قادر يتنفس','urgency':'low'}, {'reason':'عايز أكلم حد من الاستقبال','caller_phone':'01012345678'}]]"
  ```
  **Expected**: 1st → `queued` (or `callback` if run outside reception hours) with a persisted `ESC-…` ID; 2nd → `transferred`, `emergency`, message contains `123`; 3rd → same ticket ID as the 1st (de-duplicated).
- **Dashboard data layer check**:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "import asyncio; from src.db.session import get_async_session; from src.db.repository import ClinicRepository as R; exec('async def m():\n async with get_async_session() as s:\n  r=R(s); print(await r.count_open_escalations()); [print(x.ticket_id, x.urgency, x.status) for x in await r.list_open_escalations()]'); asyncio.run(m())"
  ```
  **Expected**: emergency ticket listed first.
- **Latency (NFR-1)**: scratch timing script — 10 warm `aexecute` calls on a temp SQLite DB; report median and max (target median < 400ms).

---

## 3. Automated Execution Commands

```powershell
# 1. Feature tests
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_human_handoff.py tests/test_escalation_repository.py tests/test_tools.py -v

# 2. Lint and format
uv run ruff check src/tools/human_handoff.py src/tools/__init__.py src/db/models.py src/db/schemas.py src/db/repository.py src/db/__init__.py src/config.py tests/test_human_handoff.py tests/test_escalation_repository.py tests/test_tools.py
uv run ruff format --check src/tools/human_handoff.py tests/test_human_handoff.py tests/test_escalation_repository.py

# 3. Regression
$env:PYTHONIOENCODING="utf-8"; uv run pytest tests/test_database.py tests/test_database_models.py tests/test_clinic_repository.py tests/test_medical_schemas.py tests/test_doctor_availability.py tests/test_appointment_booking.py tests/test_manage_appointment.py tests/test_knowledge_search.py tests/test_session_manager.py tests/test_prompts.py -v
```
