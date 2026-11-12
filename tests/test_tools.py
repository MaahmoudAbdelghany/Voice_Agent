"""
Unit Tests for Centralized Clinic Tools Registry and Function Calling Dispatchers.
"""

import importlib
from pathlib import Path

import pytest

from src.rag.ingestion import KnowledgeIngestionPipeline
from src.rag.retriever import QdrantKnowledgeRetriever
from src.tools import (
    ToolDefinition,
    ToolResult,
    appointment_booking_tool,
    async_execute_tool,
    clinic_knowledge_search_tool,
    doctor_availability_tool,
    execute_tool,
    get_registered_tools,
    get_session_scoped_tool_definitions,
    get_tool_definitions,
    knowledge_search_tool,
    manage_appointment_tool,
    receptionist_handoff_tool,
)

EXPECTED_CLINIC_TOOLS = {
    "check_doctor_availability",
    "book_appointment",
    "manage_appointment",
    "search_clinic_knowledge",
    "transfer_to_receptionist",
}


@pytest.fixture(scope="module", autouse=True)
def setup_knowledge_tool():
    """Ensure knowledge_search_tool has an in-memory collection for tool execution tests."""
    kb_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "clinic_kb.md"
    pipeline = KnowledgeIngestionPipeline()
    chunks = pipeline.parse_markdown(kb_path)

    test_retriever = QdrantKnowledgeRetriever(collection_name="test_registry_knowledge_kb")
    test_retriever.upsert_chunks(chunks)

    # Attach to singleton instance for centralized dispatcher testing
    original_retriever = knowledge_search_tool.retriever
    knowledge_search_tool.retriever = test_retriever
    yield knowledge_search_tool
    knowledge_search_tool.retriever = original_retriever


@pytest.fixture(autouse=True)
async def isolate_clinic_db_tools(tmp_path: Path):
    """Bind all 4 relational clinic tool singletons to an isolated tmp_path SQLite database."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from src.db.base import Base

    db_file = (tmp_path / "isolated_tools_test.db").as_posix()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    tools = (
        doctor_availability_tool,
        appointment_booking_tool,
        manage_appointment_tool,
        receptionist_handoff_tool,
    )
    prev_factories = [t.session_factory for t in tools]
    for t in tools:
        t.session_factory = factory
    try:
        yield factory
    finally:
        for t, prev in zip(tools, prev_factories):
            t.session_factory = prev
        await engine.dispose()


def test_deleted_legacy_modules_raise_module_not_found():
    """T1.1: Deleted legacy restaurant modules must not be importable."""
    for mod_name in (
        "src.tools.order_status",
        "src.tools.reservation",
        "src.tools.legacy_schemas",
    ):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(mod_name)


def test_deleted_legacy_files_absent_on_disk():
    """T1.2: Deleted legacy restaurant scripts, tools, and tests do not exist on disk."""
    repo_root = Path(__file__).resolve().parent.parent
    deleted_rel_paths = (
        "src/tools/order_status.py",
        "src/tools/reservation.py",
        "src/tools/legacy_schemas.py",
        "scripts/ingest_knowledge.py",
        "tests/test_order_status.py",
        "tests/test_reservation.py",
    )
    for rel_path in deleted_rel_paths:
        assert not (repo_root / rel_path).exists(), f"Legacy file still exists: {rel_path}"


def test_tool_registry_contains_all_tools():
    """T1.3: Registry and schema generators expose strictly the 5 clinic tools."""
    registry = get_registered_tools()
    assert set(registry.keys()) == EXPECTED_CLINIC_TOOLS

    for tool_name, tool_def in registry.items():
        assert isinstance(tool_def, ToolDefinition)
        assert tool_def.name == tool_name
        assert len(tool_def.description) > 10
        assert tool_def.input_schema is not None
        assert tool_def.output_schema is not None
        assert callable(tool_def.sync_callable)
        assert callable(tool_def.async_callable)

    definitions = get_tool_definitions()
    assert {d["function"]["name"] for d in definitions} == EXPECTED_CLINIC_TOOLS

    scoped_definitions = get_session_scoped_tool_definitions()
    assert {d["function"]["name"] for d in scoped_definitions} == EXPECTED_CLINIC_TOOLS


def test_get_tool_definitions_openai_format():
    """Verify tool definitions match OpenAI / Groq function calling specification."""
    definitions = get_tool_definitions()
    assert len(definitions) == 5

    for item in definitions:
        assert item["type"] == "function"
        assert "function" in item
        func = item["function"]
        assert "name" in func
        assert "description" in func
        assert "parameters" in func
        params = func["parameters"]
        assert params.get("type") == "object"
        assert "properties" in params


def test_execute_transfer_to_receptionist_success():
    """Verify synchronous execution of transfer_to_receptionist via central dispatcher."""
    result = execute_tool(
        tool_name="transfer_to_receptionist",
        arguments={
            "reason": "المريض يرغب في الاستفسار عن كشف منزلي",
            "caller_name": "إيهاب جلال",
            "caller_phone": "01234567890",
            "department": "reception",
            "urgency": "medium",
        },
    )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "ESC-" in result.data["ticket_id"]
    assert result.data["status"] in ["queued", "transferred", "callback"]
    assert "إيهاب جلال" in result.message


def test_execute_knowledge_search_tool_success():
    """Verify synchronous execution of search_clinic_knowledge via central dispatcher."""
    query = "ما هي مواعيد العيادة ومواعيد العمل؟"
    result = execute_tool(
        tool_name="search_clinic_knowledge",
        arguments={"query": query},
    )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.data["found"] is True
    assert len(result.data["chunks"]) > 0


def test_execute_unregistered_and_legacy_tools():
    """T3.1: Calling removed legacy tools or unknown tools returns graceful ToolResult(success=False)."""
    for removed_name in (
        "non_existent_tool",
        "get_order_status",
        "book_reservation",
        "search_restaurant_knowledge",
    ):
        result = execute_tool(
            tool_name=removed_name,
            arguments={"param": 123},
        )
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "غير متاحة حالياً" in result.message
        assert removed_name in (result.error or "")


def test_execute_tool_invalid_arguments(caplog: pytest.LogCaptureFixture):
    """Verify validation errors return safe ToolResult and redact PII in log output."""
    import logging

    raw_phone = "01099887766"
    with caplog.at_level(logging.INFO):
        result = execute_tool(
            tool_name="book_appointment",
            arguments={
                "visit_type": "examination",
                "patient_phone": raw_phone,
            },  # Missing required patient_name, doctor, date
        )
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "حدث خطأ أثناء تنفيذ هذا الإجراء" in result.message
    assert result.error is not None
    for rec in caplog.records:
        assert raw_phone not in rec.getMessage()


@pytest.mark.asyncio
async def test_async_execute_tool_success():
    """Verify asynchronous execution dispatcher (non-blocking for LiveKit turns)."""
    result = await async_execute_tool(
        tool_name="search_clinic_knowledge",
        arguments={"query": "عنوان المركز ومواعيد العمل"},
    )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.data["found"] is True


@pytest.mark.asyncio
async def test_async_execute_tool_unverified_lookup_masks_patient_pii(isolate_clinic_db_tools):
    """Verify unverified lookup by booking_code succeeds without leaking patient_name or patient_phone."""
    import datetime as dt

    from src.db.models import Doctor, DoctorSchedule, Specialty
    from src.db.repository import ClinicRepository
    from src.db.schemas import DayOfWeek, VisitType
    from src.tools.doctor_availability import get_cairo_today

    today = get_cairo_today()
    target_date = today + dt.timedelta(days=1)
    dow = DayOfWeek.from_date(target_date).value

    async with isolate_clinic_db_tools() as db:
        spec = Specialty(code="cardio", name_ar="القلب", name_en="Cardiology")
        db.add(spec)
        await db.flush()
        doc = Doctor(
            specialty_id=spec.id,
            name_ar="د. حسام موافي",
            name_en="Dr. Hossam",
            examination_fee=400.0,
            consultation_fee=200.0,
            is_active=True,
        )
        db.add(doc)
        await db.flush()
        sched = DoctorSchedule(
            doctor_id=doc.id,
            day_of_week=dow,
            start_time=dt.time(18, 0),
            end_time=dt.time(22, 0),
            max_capacity=10,
        )
        db.add(sched)
        await db.commit()

        repo = ClinicRepository(db)
        patient = await repo.get_or_create_patient("سري للغاية", "01055443322")
        await db.commit()
        appt = await repo.create_appointment(
            patient_id=patient.id,
            doctor_id=doc.id,
            appointment_date=target_date,
            visit_type=VisitType.EXAMINATION,
        )
        await db.commit()
        b_code = appt.booking_code

    # Unverified lookup (no CallerSessionContext phone)
    res = await async_execute_tool(
        "manage_appointment",
        {"action": "lookup", "booking_code": b_code},
    )
    assert res.success is True
    assert res.data is not None
    appts = res.data["appointments"]
    assert len(appts) == 1
    appt_item = appts[0]
    assert appt_item["booking_code"] == b_code
    assert appt_item["queue_number"] == 1
    assert "patient_name" not in appt_item
    assert "patient_phone" not in appt_item
    assert "سري للغاية" not in res.message
    assert "01055443322" not in res.message


@pytest.mark.asyncio
async def test_async_execute_tool_unregistered_and_legacy():
    """T3.1: Asynchronous dispatcher rejects removed legacy tools gracefully."""
    for removed_name in (
        "unknown_async_tool",
        "get_order_status",
        "book_reservation",
        "search_restaurant_knowledge",
    ):
        result = await async_execute_tool(
            tool_name=removed_name,
            arguments={},
        )
        assert isinstance(result, ToolResult)
        assert result.success is False
        assert "غير متاحة حالياً" in result.message
        assert removed_name in (result.error or "")


def test_singletons_exported():
    """Verify clinic singleton tool instances are properly exported and accessible."""
    assert doctor_availability_tool is not None
    assert appointment_booking_tool is not None
    assert manage_appointment_tool is not None
    assert clinic_knowledge_search_tool is not None
    assert receptionist_handoff_tool is not None


def test_repository_purity_guard_no_legacy_restaurant_symbols():
    """T1.8: Scan src/, scripts/, README.md, and spec/architecture.md for zero legacy restaurant identifiers."""
    repo_root = Path(__file__).resolve().parent.parent
    forbidden_tokens = (
        "order_status",
        "book_reservation",
        "search_restaurant_knowledge",
        "legacy_schemas",
        "restaurant_name",
        "restaurant_phone",
        "restaurant_address",
        "restaurant_hours",
        "reservation_draft",
        "kitchen_manager",
        "delivery_dispatch",
    )

    files_to_scan: list[Path] = []
    for folder_name in ("src", "scripts"):
        folder = repo_root / folder_name
        if folder.exists():
            files_to_scan.extend(p for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts)

    for doc_rel in ("README.md", "spec/architecture.md"):
        doc_path = repo_root / doc_rel
        if doc_path.exists():
            files_to_scan.append(doc_path)

    violations: list[str] = []
    for file_path in sorted(files_to_scan):
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for token in forbidden_tokens:
            if token in content:
                rel = file_path.relative_to(repo_root)
                violations.append(f"{rel}: contains '{token}'")

    assert not violations, "Legacy restaurant identifiers found:\n" + "\n".join(violations)

