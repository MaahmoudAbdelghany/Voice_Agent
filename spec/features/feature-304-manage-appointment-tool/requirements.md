# Requirements: Feature 3.4 — Appointment Query, Cancellation & Rescheduling Tool (`src/tools/manage_appointment.py`)

## 1. Overview
Requirements for the unified `manage_appointment` tool with actions `lookup`, `cancel`, and `reschedule`.

---

## 2. Functional Requirements

### FR-1: Input
- **FR-1.1**: The tool accepts the fields of `ManageAppointmentInput`: `action`, `booking_code`, `phone`, `new_date`, `reason`.
- **FR-1.2**: `lookup` requires `booking_code` or `phone`; `cancel` requires `booking_code` or `phone` (changed from code-only, D1); `reschedule` requires `booking_code` and `new_date`.
- **FR-1.3**: Booking codes are normalized (spaces removed, upper-case) and phones normalized to the Egyptian `01XXXXXXXXX` form (existing 3.1 behavior).

### FR-2: Lookup
- **FR-2.1**: By code: returns the appointment (any status) with doctor, specialty, date, weekday, shift window, queue number, visit type, fee, and Arabic status label. Unknown code → `success=False`, `error="not_found"`.
- **FR-2.2**: By phone (no code): returns only `confirmed` appointments dated Cairo today or later, sorted by date then queue number. The spoken message mentions at most 3; `data["appointments"]` contains all of them. None → `success=True`, `status="none"`, polite message.
- **FR-2.3**: If both code and phone are given and they do not match the same booking, return `success=False`, `error="phone_mismatch"` without revealing booking details.

### FR-3: Ownership & Cancellable Rule
- **FR-3.1**: When `phone` is provided together with `booking_code`, it must match the booking's patient phone; otherwise `phone_mismatch`.
- **FR-3.2**: An appointment is cancellable/reschedulable only if: status is `confirmed`, AND date > Cairo today, OR date == Cairo today and Cairo now is before the shift start time.
- **FR-3.3**: Violations return `success=False` with a specific error (`not_confirmed`, `past_appointment`, `shift_started`) and a polite message; already-cancelled bookings say so.

### FR-4: Cancel
- **FR-4.1**: By code: cancel the booking (status `cancelled`, optional reason appended to notes) and confirm in Arabic with doctor, date, and booking code.
- **FR-4.2**: By phone only: if exactly one cancellable upcoming booking exists, cancel it and name the patient, doctor, and date in the message. If several exist, return `success=False`, `error="multiple_appointments"` with the list in `data["appointments"]` and ask for the booking code (max 3 spoken). If none, `success=False`, `error="not_found"`.
- **FR-4.3**: Cancelling frees a capacity slot (cancelled bookings are not counted by availability).

### FR-5: Reschedule
- **FR-5.1**: The new date is resolved with Cairo today as the base (colloquial strings supported when called directly) and must satisfy 3.3 date rules: not past, ≤ 30 days ahead, not today after shift end.
- **FR-5.2**: New date equal to the current appointment date → `success=False`, `error="same_date"`.
- **FR-5.3**: The doctor must have an active shift with remaining capacity on the new date; otherwise `success=False` with the nearest available day within 7 days in the message and `data["next_available"]`; never auto-books.
- **FR-5.4**: If the same phone already has a confirmed booking with the same doctor on the new date → `success=False`, `error="duplicate_booking"`.
- **FR-5.5**: On success, in **one transaction**: the old appointment becomes `cancelled` (notes reference the new code) and a new `confirmed` appointment is created for the same patient, doctor, and visit type with a new queue number and booking code. If creating the new appointment fails, the old one remains `confirmed`.
- **FR-5.6**: The success message includes old and new dates, new shift window, new queue number, and new booking code.

### FR-6: Result Envelope
- **FR-6.1**: All results are `ToolResult` with `message` (spoken) and `data` = serialized `ManageAppointmentOutput` (`action`, `status`, `appointments`, `message`) plus extra keys where specified (`next_available`).
- **FR-6.2**: Each appointment dict includes: `booking_code`, `patient_name`, `doctor_name_ar`, `specialty_name_ar`, `appointment_date`, `day_name_ar`, `shift_window`, `queue_number`, `visit_type`, `visit_type_ar`, `fee`, `status`, `status_ar`. Phone numbers are not included.
- **FR-6.3**: Every failure returns `success=False` with a polite message and a short `error` code; no unhandled exceptions.

---

## 3. Non-Functional Requirements
- **NFR-1 (Latency)**: Each action completes in < 400ms on the local SQLite database.
- **NFR-2 (Sync & async)**: `manage_appointment` (sync) and `async_manage_appointment` (async), safe inside a running event loop.
- **NFR-3 (Spoken Egyptian Arabic)**: short, polite, TTS-friendly; at most 3 appointments read aloud.
- **NFR-4 (Privacy)**: no phone numbers or patient names in logs at INFO or above; phone numbers never read back in messages.

---

## 4. Constraints
- **C-1**: The only 3.1 contract change is the cancel rule in `ManageAppointmentInput` (code **or** phone). No other schema changes.
- **C-2**: Do not change the public behavior of `ClinicRepository`.
- **C-3**: Reschedule never changes the doctor and never books a date the caller did not request.
- **C-4**: Never leave a state where the old booking is cancelled but the new booking was not created.
- **C-5**: Never give medical advice or diagnosis.
