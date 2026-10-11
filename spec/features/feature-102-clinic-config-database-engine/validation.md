# Validation Criteria: Feature 1.2 — Clinic Configuration & Async Database Engine

## 1. Success Definition
Feature 1.2 is successful when:
1. `src/config.py` correctly parses Egyptian polyclinic parameters and database URLs with zero breaking changes to existing tests.
2. `src/db/base.py` and `src/db/session.py` successfully provide an asynchronous SQLAlchemy engine, session maker, context manager, and lifecycle functions.
3. Automated unit and integration tests prove that sessions can be acquired, execute queries, handle rollbacks on exceptions, and close without leaks.
4. All existing 110 tests in the project continue to pass with zero regressions.

---

## 2. Applicable Verification Categories

### Tier 1: Unit Verification
- [ ] **Config Unit Tests**:
  - Test default values for `clinic_name`, `clinic_phone`, `clinic_address`, `clinic_working_hours`, and `emergency_phone`.
  - Test backward-compatibility property aliases (`restaurant_name` delegates to `clinic_name`).
  - Test default `qdrant_collection` is `"clinic_kb"`.
  - Test default `database_url` is `"sqlite+aiosqlite:///./data/clinic.db"`.
  - Test `is_database_configured()` returns `True` for valid database URLs.
- [ ] **Declarative Base Unit Tests**:
  - Verify `Base` is an instance of SQLAlchemy DeclarativeBase with custom naming conventions.
- [ ] **Engine & Factory Unit Tests**:
  - Verify `get_engine()` initializes an `AsyncEngine`.
  - Verify SQLite connection arguments include `check_same_thread: False`.
  - Verify `get_session_factory()` returns an `async_sessionmaker`.

### Tier 2: Integration Verification
- [ ] **Session & Execution Flow**:
  - Test `get_async_session()` against an in-memory SQLite database (`sqlite+aiosqlite:///:memory:`).
  - Execute an async scalar query (`SELECT 1`) within the session context and verify the result.
  - Test `init_db(engine)` creates tables defined on `Base.metadata`.
  - Test `close_db(engine)` disposes the connection pool cleanly.

### Tier 3: Error & Edge-Case Verification
- [ ] **Transaction Rollback on Error**:
  - Ensure that when an exception occurs inside the `get_async_session()` context block, changes are rolled back automatically and the exception is propagated without leaving dangling transactions.
- [ ] **Directory Creation for SQLite File**:
  - Verify that when a file-based SQLite URL in a non-existent subdirectory is configured, the directory is created automatically without raising a `FileNotFoundError`.

### Tier 4: Regression Checks
- [ ] **Zero Regression Across Existing Modules**:
  - Run the entire test suite (`pytest tests/`) and confirm all 110 existing tests pass.

### Tier 5: Build, Lint & Type Checks
- [ ] **Lint & Style Check**:
  - Run `uv run ruff check src/db/ src/config.py tests/test_database_engine.py` to ensure clean code style.
- [ ] **Dependency Specification**:
  - Verify `pyproject.toml` contains `sqlalchemy>=2.0.0` and `aiosqlite>=0.20.0`.

### Tier 6: Manual / Visual Verification
- **Status**: Not Applicable
- **Technical Justification**: This feature consists exclusively of backend configuration models and an asynchronous database engine/session infrastructure. It contains no frontend user interfaces, Streamlit pages, or graphical elements. Manual UI verification applies in Phase 5 (Dashboard).

### Tier 7: API / CLI / Application Checks
- **Status**: Not Applicable
- **Technical Justification**: This feature does not introduce public network endpoints, REST routes, or standalone CLI application entry points. CLI runners for database seeding and knowledge ingestion will be introduced in Features 1.4 and 2.2.

---

## 3. Automated Execution Commands

```powershell
# 1. Run unit, integration, and error tests for database engine & configuration
.venv\Scripts\pytest.exe tests/test_database_engine.py -v

# 2. Run full regression suite to ensure zero breaking changes
.venv\Scripts\pytest.exe -v

# 3. Run linting check
uv run ruff check src/config.py src/db/ tests/test_database_engine.py
```
