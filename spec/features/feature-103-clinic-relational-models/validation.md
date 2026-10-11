# Validation Criteria: Feature 1.3 — Clinic Relational ORM Models & Pydantic Schemas

## 1. Success Definition
Feature 1.3 is successful when:
1. All 5 core relational models (`Specialty`, `Doctor`, `DoctorSchedule`, `Patient`, `Appointment`) are declared using SQLAlchemy 2.0 mapped columns and successfully instantiate tables in SQLite via `init_db()`.
2. Relationships between models allow bi-directional traversal (`specialty.doctors`, `doctor.schedules`, `doctor.appointments`, `patient.appointments`).
3. Constraints are enforced: `booking_code` is unique, `specialty.code` is unique, and duplicate queue numbers on the same date for the same doctor are prevented.
4. Pydantic validation schemas in `src/db/schemas.py` correctly validate and serialize valid payloads, while rejecting invalid Egyptian phone numbers and negative fees.
5. All 119 existing tests continue to pass without any regressions.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- [ ] **Model Field & Default Tests**:
  - Test instantiating each model (`Specialty`, `Doctor`, `DoctorSchedule`, `Patient`, `Appointment`) in isolation.
  - Verify default values (`is_active=True`, `status="confirmed"`, `created_at` timestamp).
- [ ] **Pydantic Schemas Validation**:
  - Test valid Egyptian mobile numbers (`01012345678`, `+201123456789`) parse correctly.
  - Test invalid phone numbers (too short, letters, invalid prefixes) raise `ValidationError`.
  - Test Enums validation (`DayOfWeek`, `DoctorTitle`, `VisitType`, `AppointmentStatus`).

### Tier 2: Integration Verification
- [ ] **Schema Creation & Foreign Keys**:
  - Run `init_db(engine)` on in-memory SQLite and verify all 5 tables are created.
  - Insert a `Specialty`, link a `Doctor` to it, add a `DoctorSchedule`, create a `Patient`, and book an `Appointment`.
  - Verify relationship queries: `specialty.doctors[0].name_ar`, `doctor.schedules[0].max_capacity`, `patient.appointments[0].booking_code`.
- [ ] **Cascade Behavior**:
  - Verify deleting a doctor cascades or handles associated schedules properly.

### Tier 3: Error & Edge-Case Verification
- [ ] **Unique Constraint Enforcement**:
  - Attempt to insert two appointments with the same `booking_code` (e.g. `"APT-1001"`) and assert `IntegrityError` is raised.
  - Attempt to insert two specialties with the same `code` and assert `IntegrityError` is raised.
- [ ] **Boundary Value Handling**:
  - Verify negative fees or zero queue numbers are rejected by Pydantic schemas.

### Tier 4: Regression Checks
- [ ] **Zero Regression Across Existing Modules**:
  - Run the entire test suite (`pytest tests/`) and confirm all 119 existing tests pass without regressions.

### Tier 5: Build, Lint & Type Checks
- [ ] **Lint & Code Style**:
  - Run `uv run ruff check src/db/ tests/test_database_models.py` and confirm zero lint issues.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: This feature consists exclusively of SQLAlchemy ORM models and Pydantic validation schemas with no frontend UI, Streamlit pages, or human-facing graphical interfaces.

### Tier 7: API / CLI / Application Checks
- **Status**: Not Applicable
- **Technical Justification**: This feature defines database data structures. Database seeders and CLI ingestion tools will interact with these models starting in Features 1.4 and 2.2.

---

## 3. Automated Execution Commands

```powershell
# 1. Run unit, integration, and error tests for relational models & schemas
.venv\Scripts\pytest.exe tests/test_database_models.py -v

# 2. Run full regression suite to ensure zero breaking changes
.venv\Scripts\pytest.exe -v

# 3. Run linting check
uv run ruff check src/db/ tests/test_database_models.py
```
