# Requirements: Feature 1.4 — Clinic Database Seeder & Repository Layer

## 1. Functional Requirements

### FR-1: Specialty Data Access
- **FR-1.1**: `get_specialties(active_only=True)` MUST return all active medical specialties ordered by `name_ar`.
- **FR-1.2**: `get_specialty_by_code(code)` MUST return the specialty matching the given unique code or `None` if not found.

### FR-2: Doctor & Schedule Data Access
- **FR-2.1**: `get_doctors(specialty_code=None, active_only=True)` MUST return doctors, optionally filtered by specialty.
- **FR-2.2**: `get_doctor_by_id(doctor_id)` MUST return the doctor record including loaded specialty and schedules.
- **FR-2.3**: `get_doctor_availability(doctor_id, date)` MUST calculate:
  - Day of week for the target date.
  - Active shift schedule for that day of week.
  - Total confirmed bookings count for that date.
  - Remaining capacity (`max_capacity - booked_count`).
  - Flag `is_available` (True if remaining capacity > 0, False if fully booked).

### FR-3: Patient Management
- **FR-3.1**: `get_patient_by_phone(phone_number)` MUST clean and standardize the phone number using Egyptian phone normalization rules before lookup.
- **FR-3.2**: `get_or_create_patient(name, phone_number, ...)` MUST return existing patient if found by phone; otherwise, create and persist a new `Patient` record.

### FR-4: Atomic Appointment Booking & Queue Numbering
- **FR-4.1**: `create_appointment(...)` MUST execute within an atomic transaction.
- **FR-4.2**: MUST verify shift existence and ensure current bookings have not reached `max_capacity`. If fully booked, MUST raise a clear `ValueError` or domain exception (`ShiftCapacityExceededError`).
- **FR-4.3**: MUST calculate next sequential queue number (`current_max_queue + 1`) starting at 1 for that doctor on that date.
- **FR-4.4**: MUST generate a unique, human-readable booking code formatted as `APT-<YYYYMMDD>-<QUEUE_PAD3>` (e.g., `APT-20261015-001`).
- **FR-4.5**: MUST persist the `Appointment` record and return the created entity.

### FR-5: Appointment Management
- **FR-5.1**: `get_appointment_by_code(booking_code)` MUST return the appointment with patient and doctor relationship details.
- **FR-5.2**: `get_patient_appointments(phone_number)` MUST return active appointments for the given patient.
- **FR-5.3**: `cancel_appointment(booking_code, reason=None)` MUST update status to `"cancelled"` and record cancellation notes.

### FR-6: Database Seeding CLI Pipeline
- **FR-6.1**: `scripts/seed_clinic_db.py` MUST support a `--reset` flag that drops and recreates all tables via `init_db()`.
- **FR-6.2**: MUST seed 5 core specialties:
  1. `internal_medicine` (الباطنة والجهاز الهضمي)
  2. `pediatrics` (الأطفال وحديثي الولادة)
  3. `orthopedics` (العظام والمفاصل)
  4. `obstetrics_gynecology` (النساء والتوليد)
  5. `dentistry` (الأسنان وجراحة الفم)
- **FR-6.3**: MUST seed 10 realistic Egyptian doctors (2 per specialty) with realistic consultation/examination fees (200 - 450 EGP), titles, bio, and phone numbers.
- **FR-6.4**: MUST seed recurring weekly shifts for each doctor covering standard clinic shift windows (e.g. 10:00–14:00, 18:00–22:00) with capacity limits (15–20 patients per shift).
- **FR-6.5**: MUST support idempotent execution when run without `--reset` (updates existing or inserts missing without duplicating or crashing).

---

## 2. Non-Functional Requirements (NFR)

- **NFR-1 (Async Execution)**: All repository methods MUST be strictly asynchronous (`async def`) and compatible with `AsyncSession`.
- **NFR-2 (Sub-400ms Query Latency)**: Repository queries for availability and lookup MUST execute in under 100ms on SQLite/PostgreSQL to fit within the overall voice latency budget (<400ms tool budget).
- **NFR-3 (Eager Relationship Loading)**: Critical relationships MUST be pre-loaded via `selectinload` or model defaults to prevent `MissingGreenlet` exceptions during attribute access.

---

## 3. Constraints

- MUST NOT introduce synchronous blocking database calls.
- MUST NOT alter pre-existing configuration or break legacy restaurant settings aliases.
- MUST NOT allow negative queue numbers or negative fees.
