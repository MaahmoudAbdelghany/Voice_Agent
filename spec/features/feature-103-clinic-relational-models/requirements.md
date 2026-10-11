# Requirements: Feature 1.3 — Clinic Relational ORM Models & Pydantic Schemas

## 1. Functional Requirements

### R1: Specialty Entity & Schema (التخصص الطبي)
- **R1.1**: The ORM model `Specialty` must define:
  - `id`: Integer primary key, autoincrement.
  - `code`: Unique string identifier (e.g. `"cardiology"`, `"pediatrics"`).
  - `name_ar`: Arabic name (e.g. `"أمراض القلب والأوعية الدموية"`).
  - `name_en`: English name (e.g. `"Cardiology"`).
  - `description`: Optional text describing common symptoms or services treated under this specialty.
- **R1.2**: Must establish a one-to-many relationship with `Doctor` (`doctors = relationship("Doctor", back_populates="specialty")`).

### R2: Doctor Entity & Schema (الطبيب / الاستشاري)
- **R2.1**: The ORM model `Doctor` must define:
  - `id`: Integer primary key, autoincrement.
  - `specialty_id`: Foreign key referencing `specialties.id`, indexed.
  - `name_ar`: Arabic name with honorific (e.g. `"د. أحمد محمود"`).
  - `name_en`: English name (e.g. `"Dr. Ahmed Mahmoud"`).
  - `title`: Professional title enum (`"specialist"` / أخصائي, `"consultant"` / استشاري, `"professor"` / أستاذ دكتور).
  - `examination_fee`: Float/Numeric fee for first-time / regular examination (كشف جديد) in EGP.
  - `consultation_fee`: Float/Numeric fee for follow-up / consultation (استشارة) in EGP.
  - `is_active`: Boolean flag indicating if the doctor is currently practicing at the clinic (default: `True`).
- **R2.2**: Must define relationships to `Specialty`, `DoctorSchedule` (schedules), and `Appointment` (appointments).

### R3: Doctor Schedule Entity & Weekly Shift Windows (مواعيد العيادة والورديات)
- **R3.1**: The ORM model `DoctorSchedule` must define:
  - `id`: Integer primary key, autoincrement.
  - `doctor_id`: Foreign key referencing `doctors.id`, indexed.
  - `day_of_week`: Integer representing day of week using Egyptian clinic standard (0=Saturday, 1=Sunday, 2=Monday, 3=Tuesday, 4=Wednesday, 5=Thursday, 6=Friday).
  - `start_time`: Time object for shift start (e.g. `18:00:00`).
  - `end_time`: Time object for shift end (e.g. `21:00:00`).
  - `max_capacity`: Integer cap for maximum patient appointments allowed in this shift (default: `20`).
  - `is_active`: Boolean flag for temporary hiatus or vacation (default: `True`).
- **R3.2**: Must define a helper or property returning shift duration and human-friendly time string (e.g. `"06:00 PM - 09:00 PM"`).

### R4: Patient Entity & Schema (المريض)
- **R4.1**: The ORM model `Patient` must define:
  - `id`: Integer primary key, autoincrement.
  - `name`: Full patient name.
  - `phone`: Contact mobile number, indexed for fast lookup during incoming phone calls.
  - `gender`: Optional string (`"male"`, `"female"`).
  - `created_at`: Datetime of first registration (default: UTC now).
- **R4.2**: Must establish relationship to `Appointment` (`appointments`).

### R5: Appointment Entity & Schema (الحجز والموعد)
- **R5.1**: The ORM model `Appointment` must define:
  - `id`: Integer primary key, autoincrement.
  - `booking_code`: Unique human-readable booking code for caller verbal confirmation (e.g. `"APT-1001"`).
  - `patient_id`: Foreign key referencing `patients.id`, indexed.
  - `doctor_id`: Foreign key referencing `doctors.id`, indexed.
  - `schedule_id`: Foreign key referencing `doctor_schedules.id`, indexed.
  - `appointment_date`: Date object of the appointment.
  - `queue_number`: Integer sequential queue number within the doctor's shift (نمرة الكشف: 1, 2, 3...).
  - `visit_type`: Enum string (`"examination"` / كشف جديد, `"consultation"` / استشارة).
  - `status`: Enum string (`"confirmed"` / مؤكد, `"completed"` / تم الكشف, `"cancelled"` / ملغي, `"no_show"` / لم يحضر). Default: `"confirmed"`.
  - `fee`: Float fee charged for this specific visit.
  - `notes`: Optional string notes (e.g. symptoms described by caller or receptionist notes).
  - `created_at`: Datetime timestamp.
- **R5.2**: Must enforce unique constraint or composite index on `(doctor_id, appointment_date, queue_number)` to prevent duplicate queue allocations.

### R6: Pydantic Validation & DTO Schemas (`src/db/schemas.py`)
- **R6.1**: Must define typed Enums: `DayOfWeek`, `DoctorTitle`, `VisitType`, `AppointmentStatus`.
- **R6.2**: Must provide Pydantic Base, Create, and Response schemas for `Specialty`, `Doctor`, `DoctorSchedule`, `Patient`, and `Appointment`.
- **R6.3**: Patient schema must validate phone numbers (allowing Egyptian formats: `010xxxxxxxx`, `011xxxxxxxx`, `012xxxxxxxx`, `015xxxxxxxx`, `+201xxxxxxxxx`).

---

## 2. Non-Functional Requirements

### NFR1: Indexing & Fast Retrieval
- `phone` in `Patient` and `(doctor_id, appointment_date)` in `Appointment` must be indexed to ensure caller lookup and shift availability queries execute in under **10ms**.

### NFR2: Modern SQLAlchemy 2.0 Syntax
- Models must utilize `Mapped[T]` and `mapped_column()` declarative syntax.
- All relationships must have reciprocal `back_populates` and appropriate cascade delete rules where applicable (e.g. cascading schedules on doctor delete).

---

## 3. Constraints

### C1: Scope Isolation
- Repository query functions (`get_doctor_by_id`, `book_appointment_tx`, etc.) and database seeders belong to **Feature 1.4** and must NOT be included in Feature 1.3.

### C2: Zero Regression
- Introducing models and schemas must NOT break any existing tests in the test suite (all 119 tests must continue to pass).
