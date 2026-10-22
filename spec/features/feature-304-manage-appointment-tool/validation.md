# Validation Criteria: Feature 3.4 — Appointment Query, Cancellation & Rescheduling Tool (`src/tools/manage_appointment.py`)

## 1. Success Definition
The feature is complete when `manage_appointment` correctly looks up appointments by code and phone, cancels only eligible bookings (including the phone-only single-booking path), reschedules atomically to the same doctor with 3.3 date rules and next-available suggestions, never leaves a half-applied reschedule, is registered in `TOOL_REGISTRY`, and passes unit, integration, edge-case, regression, lint, CLI, and latency checks.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: pure helpers and the schema change.
- **Test cases**:
  - `test_is_modifiable_rule`: confirmed future → yes; today before shift start → yes; today at/after start → no (`shift_started`); past → no; cancelled → no.
  - `test_schema_cancel_accepts_phone_only` (in `tests/test_medical_schemas.py`): cancel with only `phone` validates; cancel with neither still raises.
  - `test_spoken_list_limited_to_three`: list message mentions at most 3 appointments.

### Tier 2: Integration Verification
- **Scope**: tool + `ClinicRepository` + per-test file-based SQLite DB (same fixture approach as 3.3).
- **Test cases**:
  - `test_lookup_by_code`: returns the appointment with Arabic status.
  - `test_lookup_by_phone_upcoming_only`: past and cancelled bookings excluded; sorted nearest first.
  - `test_cancel_by_code_success`: status becomes `cancelled`, reason stored in notes, slot freed (availability remaining +1).
  - `test_cancel_by_phone_single_booking`: phone-only cancel works when exactly one cancellable booking exists.
  - `test_reschedule_success_atomic_swap`: old `cancelled` with reference to new code; new `confirmed` with new queue/code, same visit type and doctor.
  - `test_reschedule_rollback_keeps_old`: new booking fails inside the transaction (patched capacity error) → old stays `confirmed`, no new row.
  - `test_sync_and_async_execution`: both entrypoints work.
  - `test_tool_registered_in_registry`: `manage_appointment` registered with `ManageAppointmentInput` / `ManageAppointmentOutput`.

### Tier 3: Error & Edge-Case Verification
- **Test cases**:
  - `test_lookup_unknown_code` / `test_lookup_phone_none`.
  - `test_phone_mismatch_rejected`: code + wrong phone → `phone_mismatch`, no details leaked.
  - `test_cancel_by_phone_multiple_asks_for_code`: `multiple_appointments`, nothing cancelled.
  - `test_cancel_already_cancelled` / `test_cancel_past_appointment` / `test_cancel_after_shift_started`.
  - `test_reschedule_same_date_rejected`.
  - `test_reschedule_no_shift_suggests_next_available` and `test_reschedule_full_shift_suggests_next_available`: old unchanged.
  - `test_reschedule_duplicate_on_new_date`.
  - `test_reschedule_date_rules`: past, > 30 days, today after shift end.
  - `test_unexpected_db_error_graceful`.

### Tier 4: Regression Checks
- `tests/test_medical_schemas.py` (schema validator modified).
- `tests/test_appointment_booking.py` (3.3 helpers reused).
- `tests/test_doctor_availability.py`, `tests/test_database.py`, `tests/test_clinic_repository.py`, `tests/test_tools.py`.
- **Note (verified baseline at HEAD `8b02373`)**: pre-existing unrelated failures (8 failed + 5 errors in `test_clinic_rag.py`, `test_rag.py`, `test_knowledge_search.py`, `test_database_engine.py`; `test_agent.py` collection error from missing livekit DLL) are not regressions.

### Tier 5: Build, Lint & Type Checks
- `uv run ruff check src/tools/manage_appointment.py tests/test_manage_appointment.py src/tools/schemas.py`
- `uv run ruff format --check src/tools/manage_appointment.py tests/test_manage_appointment.py`
- Type checking: **Not Applicable** — no type checker configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: backend tool logic with no UI or audio output; spoken messages are asserted in tests and printed in Tier 7.

### Tier 7: API / CLI / Application Checks
- Against the real seeded local database (re-seed afterwards to clean up):
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/seed_clinic_db.py
  # book (3.3), then lookup by phone, reschedule by code, cancel by phone, via execute_tool
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "from src.tools import execute_tool as e; b=e('book_appointment',{'patient_name':'محمد علي','patient_phone':'01012345678','doctor_name':'الشريف','date':'2026-10-24'}); print(b.message); print(e('manage_appointment',{'action':'lookup','phone':'01012345678'}).message); r=e('manage_appointment',{'action':'reschedule','booking_code':b.data['booking_code'],'new_date':'2026-10-26'}); print(r.message); print(e('manage_appointment',{'action':'cancel','phone':'01012345678'}).message)"
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/seed_clinic_db.py
  ```
- **Expected**: booking confirmation → lookup lists one booking → reschedule confirmation with a new code on 2026-10-26 → cancel-by-phone confirmation for the rescheduled booking.
- **Latency (NFR-1)**: scratch timing script over 10 warm runs per action; median and max < 400ms.

---

## 3. Automated Execution Commands

```powershell
# 1. Feature tests
uv run pytest tests/test_manage_appointment.py -v

# 2. Lint and format
uv run ruff check src/tools/manage_appointment.py tests/test_manage_appointment.py src/tools/schemas.py
uv run ruff format --check src/tools/manage_appointment.py tests/test_manage_appointment.py

# 3. Regression
uv run pytest tests/test_medical_schemas.py tests/test_appointment_booking.py tests/test_doctor_availability.py tests/test_database.py tests/test_clinic_repository.py tests/test_tools.py -v
```
