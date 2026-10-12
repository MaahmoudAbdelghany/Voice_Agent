# Requirements: Feature 1.5 — Automated Database & Concurrency Test Suite

## 1. Functional Requirements

### FR-1: Concurrent Booking Integrity & Sequential Queue Numbers
- **FR-1.1**: When $N$ callers ($N = 5 \dots 10$) attempt to book appointments concurrently for the same doctor on the same date, the system MUST assign strictly unique queue numbers ($1, 2, \dots, N$) with zero duplicate numbers.
- **FR-1.2**: All created booking codes MUST be strictly unique with zero collisions.
- **FR-1.3**: The database MUST NOT raise unhandled `IntegrityError` collisions when concurrency is within shift capacity.

### FR-2: Race Condition Capacity Cap Enforcement
- **FR-2.1**: When $M$ concurrent callers ($M > \text{max\_capacity}$) attempt to book into a shift with capacity $K$, exactly $K$ bookings MUST succeed.
- **FR-2.2**: The remaining $M - K$ requests MUST be gracefully rejected with `ShiftCapacityExceededError`.
- **FR-2.3**: Under no circumstances shall total active bookings for that shift exceed $\text{max\_capacity}$.

### FR-3: Multi-Doctor Shift Isolation
- **FR-3.1**: When concurrent callers book appointments across multiple distinct doctors on the same date, each doctor's queue numbers MUST increment independently starting from 1.
- **FR-3.2**: A booking for Doctor A MUST NOT affect or decrement the remaining capacity of Doctor B.

### FR-4: Transaction Atomicity & Rollback Verification
- **FR-4.1**: If a booking transaction fails or raises an error before committing, all changes MUST be completely rolled back.
- **FR-4.2**: No orphaned records, partial appointment rows, or corrupted patient states shall persist following a rolled-back transaction.

### FR-5: Operational Rescheduling & Capacity Recovery
- **FR-5.1**: Cancelling an appointment MUST immediately free up 1 slot in the respective shift capacity.
- **FR-5.2**: Rescheduling (cancelling previous and booking new slot) MUST accurately decrement new shift capacity and increment old shift available capacity.

---

## 2. Non-Functional Requirements (NFR)

- **NFR-1 (Asynchronous Concurrency)**: All concurrency tests MUST use `asyncio.gather` with independent `AsyncSession` instances to faithfully simulate distributed voice agent sessions.
- **NFR-2 (Sub-Second Test Execution)**: Individual concurrency tests MUST complete within 2 seconds.
- **NFR-3 (Clean Tear-Down)**: Each test MUST execute against clean, isolated tables without state leakage to other tests.

---

## 3. Constraints

- MUST NOT lower SQLite transaction isolation or disable foreign key constraints to make tests pass artificially.
- MUST NOT modify production business rules or allow negative capacities.
- MUST ensure zero regressions across all 136 existing tests.
