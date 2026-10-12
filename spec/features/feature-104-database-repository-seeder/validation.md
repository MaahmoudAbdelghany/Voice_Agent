# Validation Criteria: Feature 1.4 — Clinic Database Seeder & Repository Layer

## 1. Success Definition
Feature 1.4 is successful when:
1. `ClinicRepository` provides fully asynchronous, robust data access methods covering specialties, doctors, availability, patient registration, atomic appointment booking, and cancellations.
2. Atomic appointment booking properly computes the next sequential queue number per doctor per date, creates unique booking codes, and prevents exceeding shift `max_capacity`.
3. `scripts/seed_clinic_db.py` executes successfully via CLI with `--reset`, seeding 5 specialties, 10 Egyptian doctors, and recurring weekly shifts with realistic fees and capacity caps.
4. Idempotent re-run of the seeder without `--reset` executes cleanly without unique constraint errors or destroying active data.
5. All 128 existing tests continue to pass without regressions, and lint checks pass clean.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- [ ] **Data Access Queries**:
  - Test `get_specialties()` returns all active specialties sorted by Arabic name.
  - Test `get_specialty_by_code()` returns correct specialty or `None`.
  - Test `get_doctors()` filtering by specialty code.
  - Test `get_patient_by_phone()` cleans prefixes (`010`, `+2010`) and retrieves matching patient.
- [ ] **Booking Code & Sequence Generator**:
  - Test that sequential queue numbers increment properly (1, 2, 3...).
  - Test formatting of `booking_code` matches `APT-<YYYYMMDD>-<QUEUE>`.

### Tier 2: Integration Verification
- [ ] **End-to-End Booking Transaction**:
  - Register a new patient via `get_or_create_patient()`.
  - Check doctor availability via `get_doctor_availability()`.
  - Create appointment via `create_appointment()` inside an async session.
  - Verify appointment state is persisted with correct relationships and queue number 1.
- [ ] **Appointment Management Flow**:
  - Query appointments by patient phone number via `get_patient_appointments()`.
  - Cancel appointment via `cancel_appointment()` and verify status is updated to `"cancelled"`.

### Tier 3: Error & Edge-Case Verification
- [ ] **Shift Capacity Cap Enforcement**:
  - Populate a shift schedule with `max_capacity = 2`.
  - Book 2 consecutive appointments successfully.
  - Attempt to book a 3rd appointment on the same date and assert `ValueError` / `ShiftCapacityExceededError` is raised.
- [ ] **Missing Entity Handling**:
  - Attempt to book an appointment with a non-existent doctor ID and verify graceful error handling.
  - Query availability on a day where the doctor has no scheduled shift and verify `is_available=False`.

### Tier 4: Regression Checks
- [ ] **Zero Regression Across Existing Modules**:
  - Run the entire test suite (`pytest tests/`) and confirm all 128 existing tests pass without regressions.

### Tier 5: Build, Lint & Type Checks
- [ ] **Lint & Code Style**:
  - Run `uv run ruff check src/db/ scripts/ tests/test_clinic_repository.py` and confirm zero lint issues.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: This feature consists of a backend async repository class and a CLI database seeding script with no frontend UI, Streamlit pages, or human-facing graphical interfaces.

### Tier 7: API / CLI / Application Checks
- [ ] **CLI Database Seeding Execution**:
  - Run `python scripts/seed_clinic_db.py --reset` and verify exit code 0.
  - Verify SQLite / PostgreSQL database contains 5 specialties, 10 doctors, and associated schedules.
  - Run `python scripts/seed_clinic_db.py` (idempotent re-run) and verify exit code 0 without duplicate key violations.

---

## 3. Automated Execution Commands

```powershell
# 1. Run unit, integration, and edge-case tests for clinic repository
.venv\Scripts\pytest.exe tests/test_clinic_repository.py -v

# 2. Run CLI seeder execution test with --reset
.venv\Scripts\python.exe scripts/seed_clinic_db.py --reset

# 3. Run idempotent CLI seeder re-run
.venv\Scripts\python.exe scripts/seed_clinic_db.py

# 4. Run full regression test suite
.venv\Scripts\pytest.exe -v

# 5. Run linting check
uv run ruff check src/db/ scripts/ tests/test_clinic_repository.py
```
