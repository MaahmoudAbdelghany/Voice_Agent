# Validation Criteria: Feature 3.1 — Clinic Domain Tool Schemas (`src/tools/schemas.py`)

## 1. Success Definition
Feature 3.1 is completely successful when all Pydantic schemas in `src/tools/schemas.py` are strictly defined for the Egyptian clinic domain, obsolete restaurant models are fully removed, Egyptian phone and colloquial date validators resolve correctly, valid OpenAI/Groq function calling JSON schemas are generated without error, and all automated unit and regression tests pass cleanly.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification (التحقق المعزول)
- **Scope**: Isolated Pydantic schema validation, date parsing logic, phone normalization, and model serialization.
- **Test Cases**:
  - `test_tool_result_envelope`: Verify generic `ToolResult` serialization with success, error, message, and data payloads.
  - `test_egyptian_phone_normalizer`: Verify normalization of `+2010...`, `011...`, `2012...`, `015...` to canonical 11-digit format `01XXXXXXXXX`.
  - `test_colloquial_date_parser`: Verify relative date parsing (`"اليوم"`, `"النهاردة"`, `"بكرة"`, `"بعد بكرة"`, `"السبت"`, `"التلات"`, etc.) and ISO dates (`"2026-10-15"`).
  - `test_doctor_availability_schemas`: Verify valid inputs, optional doctor/specialty fallbacks, and output formatting.
  - `test_appointment_booking_schemas`: Verify patient info validation, visit type parsing (`examination`/`consultation`), and confirmation output structure.
  - `test_appointment_management_schemas`: Verify individual models (`Lookup`, `Cancel`, `Reschedule`) and unified `ManageAppointmentInput`.
  - `test_clinic_knowledge_search_schemas`: Verify query bounds, category filtering, and snippet chunk serialization.
  - `test_receptionist_handoff_schemas`: Verify urgency/department enums, ticket creation, and emergency escalation fields.

### Tier 2: Integration Verification (تحقق تكامل العقود مع أدوات LLM)
- **Scope**: Generation of OpenAI/Groq compatible JSON Function Calling Schemas from Pydantic models.
- **Test Cases**:
  - `test_tool_json_schema_generation`: Verify `model_json_schema()` executes cleanly for all tool input models (`DoctorAvailabilityInput`, `AppointmentBookingInput`, `ManageAppointmentInput`, `ClinicKnowledgeSearchInput`, `ReceptionistHandoffInput`) producing valid OpenAPI 3.1 / JSON Schema schemas with all required field descriptions.
  - `test_extra_arguments_tolerance`: Verify schemas configured with `extra="ignore"` discard unexpected fields without validation errors.

### Tier 3: Error & Edge-Case Verification (تحقق الحالات الشاذة والحدودية)
- **Scope**: Malformed inputs, invalid phone numbers, nonsensical dates, missing mandatory fields.
- **Test Cases**:
  - `test_invalid_phone_rejection`: Reject invalid numbers (e.g., landline `02...`, letters, numbers with incorrect digit counts) raising `ValueError` or `ValidationError`.
  - `test_invalid_colloquial_date_rejection`: Reject unparsable strings (e.g., `"في الصيف"`, `"مشمش"`) raising `ValueError`.
  - `test_booking_validation_missing_patient`: Assert booking requires patient name (min length 2) and valid phone.
  - `test_manage_appointment_requires_identifier`: Reject lookup without either booking code or phone number.

### Tier 4: Regression Checks (تحقق منع الانحدار)
- **Scope**: Ensure changes in `src/tools/` do not break existing database or RAG test suites.
- **Verification**:
  - Run existing database tests (`tests/test_database.py`) to confirm database schemas remain unaffected.
  - Run existing RAG tests (`tests/test_clinic_rag.py`) to confirm vector store retrieval remains intact.

### Tier 5: Build, Lint & Type Checks (تحقق البناء وتكامل الأنواع والأنماط)
- **Scope**: Code style, linting, and syntax validity.
- **Commands**:
  - Static analysis: `ruff check src/tools/schemas.py tests/test_medical_schemas.py`
  - Code formatting check: `ruff format --check src/tools/schemas.py tests/test_medical_schemas.py`

### Tier 6: Manual or Visual Verification (التحقق اليدوي والبصري)
- **Status**: Not Applicable
- **Technical Justification**: Feature 3.1 consists entirely of backend Pydantic validation models and data transfer contracts without any user interface, audio playback, or visual presentation components.

### Tier 7: API / CLI / Application Checks (تحقق واجهات التطبيق المباشرة)
- **Scope**: Execution of test runner via project virtual environment.
- **Command**:
  - Run the complete new schema test suite via `pytest tests/test_medical_schemas.py -v`.

---

## 3. Automated Execution Commands

```powershell
# 1. Run Feature 3.1 Unit & Integration Tests
.venv\Scripts\pytest.exe tests/test_medical_schemas.py -v

# 2. Run Linting and Code Style Checks
.venv\Scripts\ruff.exe check src/tools/schemas.py tests/test_medical_schemas.py

# 3. Run Regression Suite across Existing Features
.venv\Scripts\pytest.exe tests/test_database.py tests/test_clinic_rag.py -v
```
