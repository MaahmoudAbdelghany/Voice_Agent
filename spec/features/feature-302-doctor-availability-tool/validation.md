# Validation Criteria: Feature 3.2 — Doctor Availability & Shift Lookup Tool (`src/tools/doctor_availability.py`)

## 1. Success Definition
The feature is complete when the `doctor_availability` tool matches doctor and specialty names flexibly, reads shifts and remaining capacity accurately from the relational database, suggests the nearest alternative within 7 days when unavailable, returns up to 3 doctors for specialty queries, asks for clarification on ambiguous names, and passes all unit, integration, edge-case, regression, lint, and CLI checks.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- **Scope**: standalone normalization and fuzzy-matching helpers inside the tool.
- **Test cases**:
  - `test_normalize_name_ar`: strips titles ("دكتور / د."), unifies hamza and ة/ه, removes diacritics.
  - `test_match_doctor_by_name`: partial or titled names match (e.g. "الشريف" matches "د. أحمد محمود الشريف").
  - `test_match_specialty_by_code_and_name`: specialty matches by code ("internal_medicine") or Arabic ("باطنة").
  - `test_default_date_uses_cairo_timezone`: default date uses `Africa/Cairo` (e.g. 23:30 UTC maps to the next day in Cairo).

### Tier 2: Integration Verification
- **Scope**: tool integration with `ClinicRepository` and an in-memory clinic database.
- **Test cases**:
  - `test_doctor_availability_found_and_available`: a doctor on a shift day returns correct remaining capacity, fees, and spoken message.
  - `test_doctor_has_no_shift_suggests_next_available`: a day without a shift triggers the 7-day scan and suggests the nearest working day.
  - `test_doctor_shift_fully_booked_suggests_next_available`: when `booked == max_capacity`, the next available day is suggested.
  - `test_specialty_lookup_multiple_doctors`: a specialty query ("باطنة") on a given day returns up to 3 available doctors with fees and hours in `data["doctors"]`.
  - `test_sync_and_async_execution`: `check_doctor_availability` and `async_check_doctor_availability` return the same result.
  - `test_tool_registered_in_registry`: the tool is registered in `TOOL_REGISTRY` in `src/tools/__init__.py`.

### Tier 3: Error & Edge-Case Verification
- **Scope**: invalid queries, unknown doctors and specialties, ambiguity.
- **Test cases**:
  - `test_doctor_not_found_graceful_message`: an unknown name (e.g. "د. فلان الفلاني") returns a friendly message with no exception.
  - `test_specialty_not_found_graceful_message`: an unknown specialty returns a polite reply suggesting registered specialties.
  - `test_no_shift_and_no_slots_within_seven_days`: with no shift in the next 7 days, the caller is told to contact reception.
  - `test_ambiguous_doctor_name_returns_candidates`: a name matching several doctors (e.g. two doctors named "أحمد" in test data) returns `success=False` with `data["candidates"]` and no auto-selection.
  - `test_missing_doctor_and_specialty_graceful`: calling with neither doctor nor specialty returns `success=False` with a polite message and no exception.

### Tier 4: Regression Checks
- **Scope**: make sure existing features still work.
- **Actions**:
  - Run Feature 3.1 contract tests: `tests/test_medical_schemas.py`.
  - Run database and repository tests: `tests/test_database.py`, `tests/test_clinic_repository.py`.
  - Run tool registry tests: `tests/test_tools.py` (because `src/tools/__init__.py` is modified).
- **Note**: there are 3 known, pre-existing failures in `tests/test_knowledge_search.py` (legacy restaurant tests). They fail without any change from this feature and are not counted as regressions.

### Tier 5: Build, Lint & Type Checks
- **Commands**:
  - `uv run ruff check src/tools/doctor_availability.py tests/test_doctor_availability.py`
  - `uv run ruff format --check src/tools/doctor_availability.py tests/test_doctor_availability.py`
- Type checking: **Not Applicable** — no type checker (e.g. `mypy`) is configured in `pyproject.toml`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: this feature is backend tool logic (database queries and text matching) with no UI, layout, or audio playback to inspect.

### Tier 7: API / CLI / Application Checks
- **Commands** (against the real local database after seeding):
  ```powershell
  $env:PYTHONIOENCODING="utf-8"; uv run python scripts/seed_clinic_db.py
  $env:PYTHONIOENCODING="utf-8"; uv run python -c "from src.tools.doctor_availability import check_doctor_availability as c; print(c(doctor_name_or_id='الشريف').message); print(c(specialty='باطنة').message)"
  ```
- **Expected**: two Egyptian Arabic spoken messages; the first about د. أحمد محمود الشريف (shift or nearest alternative + fees), the second listing available internal-medicine doctors or the nearest available day.

---

## 3. Automated Execution Commands

```powershell
# 1. Doctor availability tool tests
uv run pytest tests/test_doctor_availability.py -v

# 2. Lint and format
uv run ruff check src/tools/doctor_availability.py tests/test_doctor_availability.py
uv run ruff format --check src/tools/doctor_availability.py tests/test_doctor_availability.py

# 3. Regression tests
uv run pytest tests/test_medical_schemas.py tests/test_database.py tests/test_clinic_repository.py tests/test_tools.py -v
```
