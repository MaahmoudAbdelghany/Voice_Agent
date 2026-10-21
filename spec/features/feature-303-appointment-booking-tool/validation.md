# Validation Criteria: Feature 3.3 — Appointment Booking Tool (`src/tools/appointment_booking.py`)

## 1. Success Definition
The feature is complete when `book_appointment` resolves doctors reliably, enforces Cairo date rules, refuses unavailable/duplicate bookings with helpful alternatives, applies consultation eligibility, creates bookings atomically with correct sequential queue numbers under concurrency, returns polite Egyptian Arabic confirmations, is registered in `TOOL_REGISTRY`, and passes unit, integration, edge-case, regression, lint, and CLI checks.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: pure helpers inside the tool (no DB).
- **Test cases**:
  - `test_date_rules_reject_past_and_far_future`: yesterday and today+31 rejected; today and today+30 accepted.
  - `test_today_after_shift_end_rejected`: with a frozen Cairo "now" after the shift end, today is rejected; before the end, accepted.
  - `test_raw_colloquial_date_uses_cairo_today`: "بكرة" resolves relative to Cairo date (e.g. 23:30 UTC → next Cairo day).
  - `test_confirmation_message_contents`: message includes doctor name, date, shift window, queue number, booking code, and fee.

### Tier 2: Integration Verification
- **Scope**: tool + `ClinicRepository` + per-test file-based SQLite clinic DB (one connection per session, so concurrent transactions are truly isolated; `StaticPool` in-memory would share a single connection).
- **Test cases**:
  - `test_book_by_doctor_id_success`: confirmed booking, queue number 1, correct fee, row persisted.
  - `test_book_by_doctor_name_success`: fuzzy name (e.g. "الشريف") books the right doctor.
  - `test_sequential_queue_numbers`: two different patients get queue numbers 1 and 2.
  - `test_concurrent_bookings_respect_capacity`: N > capacity concurrent calls → exactly `max_capacity` successes, unique queue numbers 1..capacity.
  - `test_consultation_eligible_uses_consultation_fee`: prior examination 7 days earlier → consultation fee applied.
  - `test_consultation_not_eligible_downgraded`: no prior examination → booked as examination, `visit_type_downgraded=True`, message mentions it.
  - `test_existing_patient_reused`: booking with a known phone reuses the patient record.
  - `test_async_execution` / `test_sync_execution`: `async_book_appointment` and the sync `execute` entrypoint both work.
  - `test_tool_registered_in_registry`: `book_appointment` in `TOOL_REGISTRY` with `AppointmentBookingInput` / `AppointmentBookingOutput`.

### Tier 3: Error & Edge-Case Verification
- **Test cases**:
  - `test_no_shift_suggests_next_available_without_booking`: `success=False`, `data["next_available"]` present, no row created.
  - `test_full_shift_suggests_next_available`: same for a full shift.
  - `test_no_alternative_within_seven_days`: message advises contacting reception.
  - `test_duplicate_booking_returns_existing`: second booking same phone/doctor/date → `success=False`, `data["existing_appointment"]` with original code and queue number.
  - `test_cancelled_booking_not_counted_as_duplicate`: after cancellation the same phone can book again.
  - `test_unknown_doctor_id_and_name`: polite `success=False`, no exception.
  - `test_ambiguous_doctor_name_returns_candidates`: `data["candidates"]`, no booking.
  - `test_integrity_conflict_retry`: a simulated uniqueness conflict on first attempt → retry succeeds.
  - `test_integrity_conflict_twice_fails_politely`: two conflicts → polite `booking_conflict` failure, no rows.
  - `test_today_after_shift_end_rejected_by_tool`: Cairo now 23:00 on a shift day → `shift_ended` + next available day.
  - `test_invalid_inputs_graceful` (parametrized): past date, >30 days, unparseable date, invalid phone, too-short name.
  - `test_unexpected_db_error_graceful`: patched repository exception → `success=False` with polite message.

### Tier 4: Regression Checks
- `tests/test_medical_schemas.py` (3.1 contracts untouched).
- `tests/test_doctor_availability.py` (shared helpers reused).
- `tests/test_database.py`, `tests/test_clinic_repository.py` (repository unchanged).
- `tests/test_tools.py` (registry modified).
- **Note (verified baseline at HEAD `977e302`)**: the full suite has pre-existing, unrelated failures that are identical with and without this feature — 8 failed + 5 errors across `tests/test_clinic_rag.py`, `tests/test_rag.py`, `tests/test_knowledge_search.py` (deleted legacy restaurant KB), and `tests/test_database_engine.py`; plus `tests/test_agent.py` fails at collection (livekit native DLL missing on this machine). These are not regressions of this feature.

### Tier 5: Build, Lint & Type Checks
- `uv run ruff check src/tools/appointment_booking.py tests/test_appointment_booking.py`
- `uv run ruff format --check src/tools/appointment_booking.py tests/test_appointment_booking.py`
- Type checking: **Not Applicable** — no type checker (e.g. `mypy`) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: backend tool logic (DB transaction + text formatting) with no UI, layout, or audio output; the spoken message content is verified by Tier 1/7 assertions and CLI output.

### Tier 7: API / CLI / Application Checks
- Against the real seeded local database:
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/seed_clinic_db.py
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "from src.tools.appointment_booking import book_appointment as b; r=b(patient_name='محمد علي', patient_phone='01012345678', doctor_name='الشريف', date='بكرة'); print(r.success, r.message)"
  ```
- **Expected**: either a confirmation with queue number and booking code, or (if no shift tomorrow) `False` with the nearest available day. Running the same command twice after a success returns the duplicate message with the same booking code.

---

## 3. Automated Execution Commands

```powershell
# 1. Feature tests
uv run pytest tests/test_appointment_booking.py -v

# 2. Lint and format
uv run ruff check src/tools/appointment_booking.py tests/test_appointment_booking.py
uv run ruff format --check src/tools/appointment_booking.py tests/test_appointment_booking.py

# 3. Regression
uv run pytest tests/test_medical_schemas.py tests/test_doctor_availability.py tests/test_database.py tests/test_clinic_repository.py tests/test_tools.py -v
```
