# Feature Plan: Feature 1.3 — Clinic Relational ORM Models & Pydantic Schemas

## 1. Objective & Why
Design and implement the core relational entity models and data validation schemas for the Egyptian polyclinic domain in `src/db/models.py` and `src/db/schemas.py`.

### Why:
- The voice AI assistant requires structured, strongly-typed relational entities to query doctor shifts, check remaining queue capacities, look up existing patient bookings, and execute appointments.
- Egyptian polyclinics operate on **weekly recurring shift windows** (e.g. Saturday 18:00–21:00) with first-come first-served queue numbers (**نمرة الكشف**) and capped capacity per shift to protect doctor consultation time.
- Decoupling ORM models (`src/db/models.py`) and Pydantic DTO schemas (`src/db/schemas.py`) ensures strict data validation, clean serialization for LiveKit tool calls, and API/dashboard compatibility.

---

## 2. Scope & Boundaries

### In Scope:
- **SQLAlchemy 2.0 ORM Models (`src/db/models.py`)**:
  - `Specialty` (التخصص الطبي): `id`, `name_ar`, `name_en`, `code`, `description`, relationship to doctors.
  - `Doctor` (الطبيب / الاستشاري): `id`, `name_ar`, `name_en`, `title` (أخصائي / استشاري), `specialty_id`, `examination_fee`, `consultation_fee`, `is_active`, relationships.
  - `DoctorSchedule` (مواعيد العيادة والورديات الأسبوعية): `id`, `doctor_id`, `day_of_week` (0=Saturday..6=Friday), `start_time`, `end_time`, `max_capacity`, `is_active`.
  - `Patient` (المريض): `id`, `name`, `phone` (indexed for instant phone lookup), `gender`, `created_at`, relationship to appointments.
  - `Appointment` (الحجز والموعد): `id`, `booking_code` (e.g. `APT-1001`, unique), `patient_id`, `doctor_id`, `schedule_id`, `appointment_date`, `queue_number` (نمرة الحجز), `visit_type` (`examination` / `consultation`), `status` (`confirmed`, `completed`, `cancelled`, `no_show`), `fee`, `notes`, timestamps.
- **Pydantic Validation & DTO Schemas (`src/db/schemas.py`)**:
  - Schemas for Create, Read, and Update operations for each entity with Egyptian phone number formatting and validation.
  - Enum classes for `DayOfWeek`, `DoctorTitle`, `VisitType`, and `AppointmentStatus`.
- **Database Package Exports (`src/db/__init__.py`)**:
  - Export all models and schema enums alongside existing engine and session helpers.
- **Automated Tests (`tests/test_database_models.py`)**:
  - Verification of entity instantiation, default values, and foreign key relationships.
  - Unique constraint enforcement (`booking_code`, `specialty.code`).
  - Validation of Pydantic schemas against valid and invalid payloads.

### Out of Scope:
- Database repositories and query helpers (`src/db/repository.py`) — deferred to **Feature 1.4**.
- Realistic clinic database seeders (`scripts/seed_clinic_db.py`) — deferred to **Feature 1.4**.
- Voice tools connecting to models — deferred to **Phase 3**.

---

## 3. Relevant Existing Architecture
- `src/db/base.py`: Defines SQLAlchemy 2.0 `Base` (`DeclarativeBase`) with standard constraint naming conventions.
- `src/db/session.py`: Provides `AsyncEngine`, `async_sessionmaker`, `get_async_session()`, and `init_db()`.
- `src/config.py`: Contains polyclinic configuration (`clinic_name`, `database_url`, etc.).
- Currently passes 119/119 tests across the repository.

---

## 4. Entity-Relationship Architecture

```mermaid
erDiagram
    SPECIALTY ||--o{ DOCTOR : "has"
    DOCTOR ||--o{ DOCTOR_SCHEDULE : "operates"
    DOCTOR ||--o{ APPOINTMENT : "attends"
    PATIENT ||--o{ APPOINTMENT : "books"
    DOCTOR_SCHEDULE ||--o{ APPOINTMENT : "allocates"

    SPECIALTY {
        int id PK
        string code UK
        string name_ar
        string name_en
        string description
    }

    DOCTOR {
        int id PK
        int specialty_id FK
        string name_ar
        string name_en
        string title
        decimal examination_fee
        decimal consultation_fee
        boolean is_active
    }

    DOCTOR_SCHEDULE {
        int id PK
        int doctor_id FK
        int day_of_week
        time start_time
        time end_time
        int max_capacity
        boolean is_active
    }

    PATIENT {
        int id PK
        string name
        string phone UK_INDEX
        string gender
        datetime created_at
    }

    APPOINTMENT {
        int id PK
        string booking_code UK
        int patient_id FK
        int doctor_id FK
        int schedule_id FK
        date appointment_date
        int queue_number
        string visit_type
        string status
        decimal fee
        datetime created_at
    }
```

---

## 5. Expected Files Affected
| File Path | Action | Description |
|:---|:---:|:---|
| `src/db/models.py` | Create | SQLAlchemy 2.0 ORM models for Specialty, Doctor, DoctorSchedule, Patient, Appointment |
| `src/db/schemas.py` | Create | Pydantic validation schemas & Enums for data transfer and validation |
| `src/db/__init__.py` | Modify | Export models and schema types |
| `tests/test_database_models.py` | Create | Unit tests for ORM relationships, constraints, and Pydantic schemas |
| `TASK_PLAN.md` | Modify | Track progress |
| `spec/roadmap.md` | Modify | Track progress after completion |

---

## 6. Execution Breakdown (Atomic Steps)
1. **Execution Group 1: Enums & Pydantic Schemas (`src/db/schemas.py`)**:
   - Define `DayOfWeek`, `DoctorTitle`, `VisitType`, `AppointmentStatus` enums.
   - Define Pydantic models for Specialty, Doctor, Schedule, Patient, and Appointment.
2. **Execution Group 2: SQLAlchemy ORM Models (`src/db/models.py`)**:
   - Implement `Specialty`, `Doctor`, `DoctorSchedule`, `Patient`, `Appointment` using SQLAlchemy 2.0 mapped columns and relationships.
   - Update `src/db/__init__.py` to export models.
3. **Execution Group 3: Automated Verification (`tests/test_database_models.py`)**:
   - Verify table generation via `init_db()`.
   - Verify relationship cascades, foreign key integrity, and unique constraints.
   - Run full regression test suite (`pytest`) to ensure zero breaking changes.

---

## 7. Risks & Trade-offs
- **SQLite Foreign Key Enforcement**: SQLite does not enforce foreign keys by default unless `PRAGMA foreign_keys = ON` is executed on connection.
  - *Mitigation*: Ensure relationship definitions in SQLAlchemy use proper `ForeignKey` and back-populates, and include foreign key test verification in memory.
- **Date/Time Handling across Dialects**: SQLite stores `Time` and `Date` types as strings internally.
  - *Mitigation*: Use standard Python `datetime.date` and `datetime.time` objects and verify conversions in unit tests.
