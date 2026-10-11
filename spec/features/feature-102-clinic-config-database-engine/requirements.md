# Requirements: Feature 1.2 — Clinic Configuration & Async Database Engine

## 1. Functional Requirements

### R1: Clinic Domain Settings in `src/config.py`
- **R1.1**: The `Settings` class must define Egyptian polyclinic configuration attributes:
  - `clinic_name`: string, default `"مجمع عيادات النور التخصصي"`.
  - `clinic_tagline`: string, default `"رعايتكم أولويتنا"`.
  - `clinic_phone`: string, default `"+20 2 3345 6789"`.
  - `clinic_address`: string, default `"شارع النصر، المعادي، القاهرة، مصر"`.
  - `clinic_working_hours`: string, default `"السبت - الخميس: 9:00 ص - 10:00 م | الجمعة: 2:00 م - 10:00 م"`.
  - `agent_name`: string, default `"نور"`.
  - `emergency_phone`: string, default `"123"`.
- **R1.2**: The default Qdrant vector database collection must be changed from `"restaurant_kb"` to `"clinic_kb"`.
- **R1.3**: The settings must support backward-compatibility aliases (`restaurant_name`, `restaurant_phone`, `restaurant_address`, `restaurant_hours`) that delegate to their clinic counterparts to ensure existing legacy tests continue passing without regression.

### R2: Relational Database Settings
- **R2.1**: The `Settings` class must define:
  - `database_url`: string, default `"sqlite+aiosqlite:///./data/clinic.db"`.
  - `database_echo`: boolean, default `False` (for SQL query logging in debug mode).
- **R2.2**: The settings must provide a validation helper `is_database_configured() -> bool`.
- **R2.3**: For local SQLite paths, the settings must provide a helper to extract and ensure the parent directory (`./data`) exists.

### R3: Declarative ORM Base (`src/db/base.py`)
- **R3.1**: Must define and export `Base = declarative_base()` (or `class Base(DeclarativeBase)`) inheriting from SQLAlchemy 2.0 conventions.
- **R3.2**: Must configure naming conventions for indexes, unique constraints, and foreign keys to prevent migration conflicts across database dialects.

### R4: Asynchronous Engine & Session Factory (`src/db/session.py`)
- **R4.1**: Must provide a singleton/cached `AsyncEngine` via `get_engine(database_url: Optional[str] = None)`.
- **R4.2**: Must support both `sqlite+aiosqlite` and `postgresql+asyncpg` connection schemes.
- **R4.3**: For SQLite URLs, the engine must inject `connect_args={"check_same_thread": False}` and configure appropriate timeouts.
- **R4.4**: Must provide an async session factory using `async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)`.
- **R4.5**: Must provide an async context manager `get_async_session() -> AsyncGenerator[AsyncSession, None]` that:
  - Yields an active `AsyncSession`.
  - Automatically rolls back uncommitted changes if an exception is raised within the context.
  - Guarantees session closure in a `finally` block.
- **R4.6**: Must provide lifecycle utilities `init_db(engine=None)` (to create all tables registered with `Base.metadata`) and `close_db(engine=None)` (to dispose of the engine connection pool).

---

## 2. Non-Functional Requirements

### NFR1: Performance & Latency
- Engine initialization must take less than **50ms**.
- Session creation and checkout must take less than **5ms** overhead to satisfy the voice assistant's sub-800ms turn turnaround budget.

### NFR2: Thread Safety & Concurrency
- The session factory must be safe for concurrent coroutines in an asyncio event loop.
- SQLite connections must not block event loop threads during I/O operations.

### NFR3: Clean Architecture & Extensibility
- Database modules must reside in a dedicated `src/db/` package.
- The engine must be easily re-bindable or configurable via environment variables (`DATABASE_URL`) without modifying code.

---

## 3. Constraints

### C1: Zero Legacy Regression
- Modifying `src/config.py` must NOT break existing tests in the test suite (all 110 tests must continue to pass).
- Aliases must seamlessly handle references to old restaurant settings.

### C2: No Schema Migrations at This Stage
- Alembic or dynamic migration scripts are out of scope for Feature 1.2; schema initialization is handled via `Base.metadata.create_all` through `init_db()`.

### C3: No Domain Models in Feature 1.2
- Entity definitions (`Doctor`, `Specialty`, `Appointment`, etc.) are strictly prohibited in this feature and belong to Feature 1.3.
