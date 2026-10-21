# Requirements: Feature 3.3 — Appointment Booking Tool (`src/tools/appointment_booking.py`)

## 1. Overview
Functional and non-functional requirements and constraints for the `book_appointment` tool that reserves a confirmed queue slot for a patient with a doctor on a given date.

---

## 2. Functional Requirements

### FR-1: Input & Doctor Resolution
- **FR-1.1**: The tool accepts the fields of `AppointmentBookingInput` (Feature 3.1): `patient_name`, `patient_phone`, `doctor_id` or `doctor_name`, `date`, `visit_type`, `notes`.
- **FR-1.2**: If `doctor_id` is given, it is used directly; an unknown or inactive ID returns `success=False` with a polite message.
- **FR-1.3**: If only `doctor_name` is given, matching reuses Feature 3.2 normalization and fuzzy matching (titles, hamza, ة/ه, diacritics, partial names).
- **FR-1.4**: An unknown name returns `success=False` with a polite message. A name matching more than one active doctor returns `success=False` with `data["candidates"]` (ID, Arabic name, specialty) and never books.

### FR-2: Date Rules (Africa/Cairo)
- **FR-2.1**: Dates before Cairo "today" are rejected with a polite message.
- **FR-2.2**: Booking for today is rejected if the doctor's shift end time has already passed in Cairo time.
- **FR-2.3**: Dates more than 30 days after Cairo "today" are rejected.
- **FR-2.4**: Raw colloquial date strings passed directly to the tool are resolved with Cairo "today" as the base.

### FR-3: Availability & Alternative Suggestion
- **FR-3.1**: If the doctor has no active shift on the date, or the shift is full, the tool returns `success=False`, does **not** book, and includes the nearest available day within the next 7 days (weekday, date, shift hours) in the message and in `data["next_available"]`.
- **FR-3.2**: If no alternative exists within 7 days, the message advises contacting reception.

### FR-4: Duplicate Booking Guard
- **FR-4.1**: If the normalized phone already has a `confirmed` appointment with the same doctor on the same date, the tool returns `success=False`, does not create a new booking, and returns the existing booking code and queue number in the message and in `data["existing_appointment"]`.

### FR-5: Visit Type & Consultation Eligibility
- **FR-5.1**: `examination` bookings use the doctor's `examination_fee`.
- **FR-5.2**: `consultation` is accepted only if the patient has a non-cancelled `examination` with the same doctor dated within the 14 days before the booking date; then `consultation_fee` applies.
- **FR-5.3**: If not eligible, the booking proceeds as `examination` with the examination fee, the spoken message states the change, and `data["visit_type_downgraded"]` is `true`.

### FR-6: Atomic Booking & Queue Number
- **FR-6.1**: Patient get-or-create and appointment creation happen in a single DB session using `ClinicRepository.create_appointment` (per-shift lock, capacity check, sequential queue number starting at 1, unique booking code, commit).
- **FR-6.2**: Concurrent bookings for the same shift never produce duplicate queue numbers and never exceed `max_capacity`.
- **FR-6.3**: On a DB uniqueness conflict the tool rolls back and retries once; a second failure returns `success=False` politely.
- **FR-6.4**: Repository errors (`ShiftNotFoundError`, `ShiftCapacityExceededError`) raised at booking time (race) are converted into polite `success=False` responses.

### FR-7: Result Envelope
- **FR-7.1**: On success: `ToolResult(success=True)` with `message` = spoken confirmation including doctor name, weekday and date, shift window, queue number, booking code, visit type, and fee; `data` = serialized `AppointmentBookingOutput` plus `visit_type` (final machine value: `examination` / `consultation`, since the 3.1 output only carries the Arabic label) and `visit_type_downgraded`.
- **FR-7.2**: Every failure returns `ToolResult(success=False)` with a spoken `message` and a short `error` code; no unhandled exceptions.

---

## 3. Non-Functional Requirements
- **NFR-1 (Latency)**: Successful booking completes in < 400ms on the local SQLite database.
- **NFR-2 (Sync & async)**: Provide `book_appointment` (sync) and `async_book_appointment` (async), safe to call from a running event loop.
- **NFR-3 (Spoken Egyptian Arabic)**: Messages are short, polite, TTS-friendly Egyptian Arabic; numbers spoken as plain digits; the booking code is included once.
- **NFR-4 (Privacy)**: Phone numbers and patient names are not written to logs at INFO level or above.

---

## 4. Constraints
- **C-1**: Do not modify Feature 3.1 contracts (`AppointmentBookingInput`, `AppointmentBookingOutput`, `ToolResult`).
- **C-2**: Do not change the public behavior of `ClinicRepository`.
- **C-3**: Never create a booking that is not backed by an active `DoctorSchedule` with remaining capacity.
- **C-4**: Never book automatically on an alternative date the caller did not request.
- **C-5**: Do not remove or alter legacy restaurant tools in this feature.
- **C-6**: Never give medical advice or diagnosis; `notes` are stored as administrative text only.
