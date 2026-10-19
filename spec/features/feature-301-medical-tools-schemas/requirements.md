# Requirements Specification: Feature 3.1 — Clinic Domain Tool Schemas (`src/tools/schemas.py`)

## 1. Overview
This document specifies the exact functional and non-functional requirements for the Pydantic schemas defining the interface between the Voice AI Agent (LLM Function Calling) and Clinic Domain Tools.

---

## 2. Functional Requirements (FR)

### FR-1: Base Execution Envelope (`ToolResult`)
- **FR-1.1**: The system must provide a generic `ToolResult` model containing:
  - `success: bool` (default True)
  - `message: str` (natural, spoken Arabic message suitable for TTS synthesis)
  - `data: Optional[Dict[str, Any]]` (structured data payload)
  - `error: Optional[str]` (error description if failed)
- **FR-1.2**: Extra attributes provided by the LLM must be ignored gracefully via `ConfigDict(extra="ignore")`.

### FR-2: Egyptian Phone & Colloquial Date Normalizers
- **FR-2.1**: The system must normalize Egyptian mobile phone numbers to standard 11-digit format starting with `010`, `011`, `012`, or `015`.
- **FR-2.2**: The system must provide a date validator/parser that resolves:
  - Standard ISO format strings (`YYYY-MM-DD`).
  - Python `datetime.date` objects.
  - Colloquial Egyptian expressions:
    - `"اليوم"` or `"النهاردة"` -> Current date.
    - `"بكرة"` or `"غدا"` or `"غداً"` -> Current date + 1 day.
    - `"بعد بكرة"` or `"بعد غد"` -> Current date + 2 days.
    - Arabic weekday names (`السبت`, `الأحد`, `الاثنين`, `الثلاثاء`, `التلات`, `الأربعاء`, `الخميس`, `الجمعة`) -> The next immediate occurrence of that day (within 7 days).

### FR-3: Doctor Availability & Shift Lookup Schemas
- **FR-3.1 (`DoctorAvailabilityInput`)**:
  - `doctor_name_or_id: Optional[str]` (Doctor name or numeric ID).
  - `specialty: Optional[str]` (Specialty code or Arabic name).
  - `date: Optional[Union[date, str]]` (Target date or relative date string).
  - At least one of `doctor_name_or_id` or `specialty` must be provided.
- **FR-3.2 (`DoctorAvailabilityOutput`)**:
  - `doctor_id: int`
  - `doctor_name_ar: str`
  - `specialty_name_ar: str`
  - `target_date: str` (ISO format string)
  - `day_name_ar: str` (e.g., "السبت")
  - `has_shift: bool`
  - `shift_hours: Optional[str]` (e.g., "06:00 PM - 09:00 PM")
  - `remaining_capacity: int`
  - `is_available: bool`
  - `examination_fee: float`
  - `consultation_fee: float`
  - `message: str` (Spoken summary in Egyptian Arabic)

### FR-4: Appointment Booking Schemas
- **FR-4.1 (`AppointmentBookingInput`)**:
  - `patient_name: str` (min length 2, patient full name)
  - `patient_phone: str` (validated Egyptian phone)
  - `doctor_id: Optional[int]`
  - `doctor_name: Optional[str]`
  - `date: Union[date, str]` (colloquial or ISO date)
  - `visit_type: VisitType` (default `VisitType.EXAMINATION`, accepts `examination` / `consultation` or `كشف` / `استشارة`)
  - `notes: Optional[str]` (symptoms or notes)
- **FR-4.2 (`AppointmentBookingOutput`)**:
  - `booking_code: str` (e.g. "CLINIC-20261014-04")
  - `patient_name: str`
  - `doctor_name_ar: str`
  - `specialty_name_ar: str`
  - `appointment_date: str`
  - `queue_number: int` (نمرة الحجز)
  - `shift_window: str`
  - `visit_type_ar: str`
  - `fee: float` (EGP)
  - `message: str` (Polite, spoken confirmation message with queue number)

### FR-5: Appointment Management Schemas (Lookup, Reschedule, Cancel)
- **FR-5.1 (`AppointmentLookupInput`)**:
  - `booking_code: Optional[str]`
  - `phone: Optional[str]` (validated Egyptian phone)
  - Must provide either `booking_code` or `phone`.
- **FR-5.2 (`AppointmentCancelInput`)**:
  - `booking_code: str`
  - `phone: Optional[str]`
  - `reason: Optional[str]`
- **FR-5.3 (`AppointmentRescheduleInput`)**:
  - `booking_code: str`
  - `new_date: Union[date, str]`
  - `phone: Optional[str]`
  - `reason: Optional[str]`
- **FR-5.4 (`ManageAppointmentInput`)**:
  - `action: ManageAppointmentAction` (`lookup`, `cancel`, `reschedule`)
  - `booking_code: Optional[str]`
  - `phone: Optional[str]`
  - `new_date: Optional[Union[date, str]]`
  - `reason: Optional[str]`
- **FR-5.5 (`ManageAppointmentOutput`)**:
  - `action: str`
  - `status: str`
  - `appointments: List[Dict[str, Any]]`
  - `message: str` (Spoken summary in Egyptian Arabic)

### FR-6: Clinic Knowledge Search Schemas (RAG)
- **FR-6.1 (`ClinicKnowledgeSearchInput`)**:
  - `query: str` (min length 2, max 500)
  - `limit: int` (default 3, range 1-10)
  - `score_threshold: float` (default 0.35, range 0.0-1.0)
  - `category: Optional[str]` (e.g. `lab_radiology`, `insurance`, `pricing`, `specialties`)
- **FR-6.2 (`ClinicKnowledgeSearchOutput`)**:
  - `query: str`
  - `found: bool`
  - `total_results: int`
  - `chunks: List[KnowledgeChunk]`
  - `context_text: str`
  - `message: str`

### FR-7: Human Receptionist Escalation Schemas
- **FR-7.1 (`ReceptionistHandoffInput`)**:
  - `caller_name: Optional[str]`
  - `caller_phone: Optional[str]`
  - `reason: str` (min length 3)
  - `department: HandoffDepartmentEnum` (default `reception`)
  - `urgency: HandoffUrgencyEnum` (default `medium`)
  - `summary: Optional[str]` (Brief context for human receptionist)
- **FR-7.2 (`ReceptionistHandoffOutput`)**:
  - `ticket_id: str`
  - `status: str`
  - `urgency: str`
  - `department: str`
  - `estimated_wait_seconds: int`
  - `message: str` (Comforting, polite reassurance in Egyptian Arabic)

### FR-8: Deprecation & Cleanup of Legacy Schemas
- **FR-8.1**: All obsolete restaurant schemas (`OrderStatusEnum`, `OrderItem`, `OrderStatusInput`, `OrderStatusOutput`, `ReservationStatusEnum`, `ReservationInput`, `ReservationOutput`) must be removed from `src/tools/schemas.py`.

---

## 3. Non-Functional Requirements (NFR)

- **NFR-1 (Validation Latency)**: Schema parsing and validation must complete in under **2ms** per payload.
- **NFR-2 (LLM Serialization Compatibility)**: Every schema must generate valid OpenAPI / JSON Schema with detailed field descriptions for OpenAI/Groq function calling.
- **NFR-3 (Defensive Tolerance)**: Schemas must tolerate extra fields (`extra="ignore"`) commonly introduced by LLM hallucinations without raising unexpected validation errors.
- **NFR-4 (Arabic Spoken Formatting)**: Messages generated in outputs must use natural, polite Egyptian Arabic (العامية المصرية المهذبة) suitable for ElevenLabs streaming speech synthesis.

---

## 4. Constraints

- **C-1**: Must use Pydantic V2 syntax (`model_config = ConfigDict(...)`, `@field_validator`, `@model_validator`).
- **C-2**: Must not introduce external heavy dependencies (e.g. external date parsing libraries like `dateparser` or `arrow`); keep the date parsing lightweight using Python standard library `datetime` and regex.
- **C-3**: Must strictly reuse database enums from `src.db.schemas` (`VisitType`, `AppointmentStatus`, `DayOfWeek`, `DoctorTitle`) to avoid enum discrepancies across layers.
