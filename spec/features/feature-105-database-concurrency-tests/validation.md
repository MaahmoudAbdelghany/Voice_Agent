# Validation Criteria: Feature 1.5 — Automated Database & Concurrency Test Suite

## 1. Success Definition
Feature 1.5 is successful when:
1. `tests/test_database.py` executes successfully and passes 100% of its test cases, rigorously demonstrating:
   - Zero duplicate queue numbers when multiple callers book concurrently.
   - Strict enforcement of shift `max_capacity` under race conditions with graceful `ShiftCapacityExceededError`.
   - Independent queue numbering per doctor on the same date.
   - Transaction rollback resilience during mid-booking failures.
   - Slot capacity recovery upon appointment cancellation and rescheduling.
2. The entire project regression test suite passes cleanly with zero broken tests.
3. Code style and linting pass with zero errors via `ruff check`.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- [x] **Queue Number Generator & Code Formatting**:
  - Verify that sequential queue numbers for a single session strictly increment from 1.
  - Verify unique booking code formatting `APT-<YYYYMMDD>-D{doctor_id}Q{queue}`.

### Tier 2: Integration Verification
- [x] **Concurrent Bookings via Multi-Session Tasks (`asyncio.gather`)**:
  - Spawn 6 concurrent caller tasks booking into the same shift.
  - Assert that all 6 bookings succeed with queue numbers $\{1, 2, 3, 4, 5, 6\}$.
  - Assert that all 6 booking codes are distinct.
- [x] **Multi-Doctor Independent Queue Isolation**:
  - Concurrently book appointments for Doctor A and Doctor B on the same date.
  - Assert Doctor A has queue numbers $\{1, 2, 3\}$ and Doctor B has queue numbers $\{1, 2, 3\}$.
- [x] **Operational Rescheduling Flow**:
  - Book an appointment for a patient in Shift 1.
  - Cancel that appointment and immediately book a new appointment in Shift 2.
  - Verify Shift 1 capacity is restored by 1, and Shift 2 capacity is decremented by 1.

### Tier 3: Error & Edge-Case Verification
- [x] **Race Condition Overbooking Rejection**:
  - Configure a shift with `max_capacity = 3`.
  - Concurrently execute 7 booking attempts.
  - Assert that exactly 3 bookings succeed and exactly 4 fail with `ShiftCapacityExceededError`.
  - Assert that total database records for that shift equal exactly 3 (no ghost rows).
- [x] **Atomic Rollback on Transaction Failure**:
  - Simulate an unhandled exception or constraint violation mid-booking.
  - Assert that no partial patient or appointment records remain in the database.

### Tier 4: Regression Checks
- [x] **Zero Regression Across Existing Modules**:
  - Run the entire test suite (`pytest tests/`) and confirm all 142 existing tests pass without regressions (100% pass rate).

### Tier 5: Build, Lint & Type Checks
- [x] **Lint & Code Style**:
  - Run `uv run ruff check tests/test_database.py` and confirm zero lint issues.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: This feature consists exclusively of an automated pytest concurrency and transaction test suite without visual frontend UI elements.

### Tier 7: API / CLI / Application Checks
- **Status**: Not Applicable
- **Technical Justification**: This feature is an automated test suite executed directly via the pytest test runner rather than an external CLI application command.

---

## 3. Automated Execution Commands

```powershell
# 1. Run database and concurrency test suite
.venv\Scripts\pytest.exe tests/test_database.py -v

# 2. Run full project regression suite
.venv\Scripts\pytest.exe -v

# 3. Run linting check
uv run ruff check tests/test_database.py
```
