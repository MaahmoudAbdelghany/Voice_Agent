# Requirements: Feature 3.2 — Doctor Availability & Shift Lookup Tool (`src/tools/doctor_availability.py`)

## 1. Overview
This document defines the functional and non-functional requirements and constraints for the tool that answers questions about doctor availability, shift hours, remaining capacity, and fees in Egyptian polyclinics.

---

## 2. Functional Requirements

### FR-1: Fuzzy & Resilient Matching
- **FR-1.1**: The tool accepts doctors through the single field `doctor_name_or_id` in `DoctorAvailabilityInput`. A numeric value is treated as a `doctor_id`; anything else is treated as a name.
- **FR-1.2**: Name matching must tolerate Arabic spelling variants:
  - Ignore titles ("د.", "دكتور", "دكتورة", "أستاذ دكتور", "استشاري", "أخصائي").
  - Unify hamza forms ("أحمد", "إبراهيم", "آدم" → "ا").
  - Unify final ة/ه ("مروة/مروه", "فاطمة/فاطمه").
  - Remove diacritics and extra whitespace.
  - Support partial matches (e.g. "الشريف" matches "د. أحمد محمود الشريف").
- **FR-1.3**: Specialty matching must accept Arabic and English forms (e.g. "باطنة", "الباطنة والجهاز الهضمي", "internal_medicine", "أطفال", "عظام", "نساء وتوليد", "أسنان").
- **FR-1.4 (Disambiguation)**: If a name matches more than one active doctor (after narrowing by specialty, if given), the tool returns `ToolResult(success=False)` with `data["candidates"]` listing ID, Arabic name, and specialty for each candidate, plus a spoken message asking the caller which doctor they mean. The tool must not auto-select a doctor in this case.

### FR-2: Specific Doctor Availability
- **FR-2.1**: For a given doctor and date, the tool:
  - Maps the date to the Egyptian weekday (Saturday=0 .. Friday=6).
  - Checks for an active `DoctorSchedule` shift on that day.
  - Counts confirmed, non-cancelled bookings against `max_capacity`.
  - Computes remaining capacity and sets `is_available = remaining > 0`.
- **FR-2.2**: When the doctor is available, the tool returns a `DoctorAvailabilityOutput` with doctor ID, Arabic name, specialty, target date, Arabic weekday name, formatted shift hours, remaining capacity, examination and consultation fees, and a polite spoken confirmation message.

### FR-3: Next Available Slot Recommendation
- **FR-3.1**: If the doctor has **no shift** on the requested date, or the shift is **fully booked** (`remaining_capacity == 0`), the tool:
  - Scans the next 7 days automatically.
  - Finds the nearest future date with a non-full shift for the same doctor.
  - Includes that alternative (weekday, date, shift hours, remaining capacity) explicitly in the `message`, so the agent can offer it directly without the caller guessing working days.

### FR-4: Specialty-Wide Availability
- **FR-4.1**: When a specialty is given without a doctor (e.g. "عايز دكتور باطنة بكرة"), the tool:
  - Fetches all active doctors in the specialty.
  - Checks their shifts on the requested date.
  - Keeps up to 3 available doctors.
  - Builds a single clear spoken message with each doctor's name, shift hours, and examination fee.
  - Returns `ToolResult(success=True, message=..., data={"doctors": [DoctorAvailabilityOutput, ...]})` without adding or changing Feature 3.1 schemas.
- **FR-4.2**: If no doctor in the specialty is available that day, the tool scans the next 7 days for the nearest day with available doctors and tells the caller.

### FR-5: Graceful Failures
- **FR-5.1**: If the doctor or specialty is not found, the tool returns `ToolResult(success=False)` with a natural spoken message saying the name isn't registered and suggesting available specialties or doctors, without crashing the call or raising unhandled exceptions.
- **FR-5.2**: Invalid input (e.g. neither doctor nor specialty provided) or unexpected database errors return `ToolResult(success=False)` with a polite message instead of raising.

### FR-6: Default Date in Cairo Time
- **FR-6.1**: When no date is given, the tool uses today's date in `Africa/Cairo` (not UTC), without modifying the date parser in `schemas.py`.

### FR-7: Single-Doctor Result Envelope
- **FR-7.1**: For a specific-doctor query, the tool returns a `ToolResult` where `message` is the spoken text and `data` is the serialized `DoctorAvailabilityOutput`, plus `data["next_available"]` when an alternative date is suggested.

---

## 3. Non-Functional Requirements

- **NFR-1 (Latency)**: Full tool execution must stay under **400ms** on the local database to fit the overall voice budget (< 800ms).
- **NFR-2 (Sync & async)**: Provide both `check_doctor_availability` (sync) and `async_check_doctor_availability` (async) for LiveKit Agents integration and direct testing.
- **NFR-3 (Spoken Egyptian Arabic)**: All `message` values must be in familiar, polite Egyptian Arabic that is easy to pronounce, avoiding symbols that TTS cannot read naturally.

---

## 4. Constraints

- **C-1**: Never invent or assume schedules that are not recorded in `DoctorSchedule`.
- **C-2**: Use only the Feature 3.1 contracts (`DoctorAvailabilityInput`, `DoctorAvailabilityOutput`, `ToolResult`); do not modify them.
- **C-3**: Never give medical advice or diagnosis when answering about specialties or doctors.
