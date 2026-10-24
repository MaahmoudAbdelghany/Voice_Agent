"""
Feature 3.7: Automated Unit & Integration Tests for Medical Tools (Cross-Tool Suite).

Tests the collaboration, dispatcher paths, multi-step patient journeys,
cross-cutting invariants, and concurrency of all 5 Egyptian clinic domain tools
as called through the centralized TOOL_REGISTRY:
- check_doctor_availability
- book_appointment
- manage_appointment
- search_clinic_knowledge
- transfer_to_receptionist

Requirements covered: R1 through R19, NFR-1 through NFR-6.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from qdrant_client import QdrantClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.base import Base
from src.db.models import Appointment, Doctor, DoctorSchedule, Specialty
from src.db.repository import ClinicRepository
from src.rag.embeddings import embedding_service
from src.rag.ingestion import KnowledgeIngestionPipeline
from src.rag.retriever import QdrantKnowledgeRetriever
from src.tools import (
    TOOL_REGISTRY,
    AppointmentBookingInput,
    AppointmentBookingOutput,
    ClinicKnowledgeSearchInput,
    ClinicKnowledgeSearchOutput,
    DoctorAvailabilityInput,
    DoctorAvailabilityOutput,
    ManageAppointmentInput,
    ManageAppointmentOutput,
    ReceptionistHandoffInput,
    ReceptionistHandoffOutput,
    ToolResult,
    appointment_booking_tool,
    async_execute_tool,
    clinic_knowledge_search_tool,
    doctor_availability_tool,
    execute_tool,
    get_tool_definitions,
    manage_appointment_tool,
    receptionist_handoff_tool,
)
from src.tools.doctor_availability import CAIRO_TZ

logger = logging.getLogger(__name__)

# ==============================================================================
# Reference Constants & Frozen Cairo Clock (2026-10-24 Saturday)
# ==============================================================================

TODAY_SAT = dt.date(2026, 10, 24)  # Saturday (day_of_week = 0)
SUN = dt.date(2026, 10, 25)  # Sunday (day_of_week = 1)
MON = dt.date(2026, 10, 26)  # Monday (day_of_week = 2)
WED = dt.date(2026, 10, 28)  # Wednesday (day_of_week = 4)
NEXT_MON = dt.date(2026, 11, 2)  # Next Monday (day_of_week = 2)

NOW_MORNING = dt.datetime(2026, 10, 24, 10, 0, 0, tzinfo=CAIRO_TZ)
ARABIC_RE = re.compile(r"[\u0600-\u06FF]")

CLINIC_TOOLS = [
    "check_doctor_availability",
    "book_appointment",
    "manage_appointment",
    "search_clinic_knowledge",
    "transfer_to_receptionist",
]


# ==============================================================================
# Shared Fixtures (Harness & Isolation - NFR-1, NFR-2)
# ==============================================================================


@pytest.fixture(scope="module")
def clinic_kb_retriever() -> QdrantKnowledgeRetriever | None:
    """Build in-memory Qdrant collection once for module tests if embeddings available."""
    if not getattr(embedding_service, "is_semantic", True):
        return None
    try:
        kb_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "clinic_kb.md"
        if not kb_path.exists():
            return None
        pipeline = KnowledgeIngestionPipeline()
        chunks = pipeline.parse_markdown(kb_path)
        if not chunks:
            return None

        retriever = QdrantKnowledgeRetriever.__new__(QdrantKnowledgeRetriever)
        retriever.collection_name = "test_clinic_tools_suite_kb"
        retriever.client = QdrantClient(":memory:")
        retriever.embeddings = embedding_service
        retriever._ensure_collection()
        retriever.upsert_chunks(chunks)
        return retriever
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not build in-memory Qdrant collection for test suite: %s", exc)
        return None


@pytest.fixture
async def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clinic_kb_retriever):
    """
    Sets up isolated SQLite DB with deterministic seed data, patches Cairo clock,
    and safely rebinds all module singletons so TOOL_REGISTRY dispatches to this harness.
    """
    db_file = tmp_path / "clinic_tools_integration.db"
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 30},
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    # 1. Seed deterministic clinic data
    async with factory() as session:
        internal = Specialty(
            code="internal_medicine",
            name_ar="الباطنة والجهاز الهضمي",
            name_en="Internal Medicine",
            description="عيادة أمراض الباطنة والكبد",
        )
        peds = Specialty(
            code="pediatrics",
            name_ar="الأطفال",
            name_en="Pediatrics",
            description="عيادة طب الأطفال وحديثي الولادة",
        )
        session.add_all([internal, peds])
        await session.flush()

        sherif = Doctor(
            specialty_id=internal.id,
            name_ar="د. أحمد محمود الشريف",
            name_en="Dr. Ahmed El-Sherif",
            title="consultant",
            examination_fee=350.0,
            consultation_fee=150.0,
            is_active=True,
        )
        marwa = Doctor(
            specialty_id=internal.id,
            name_ar="د. مروة كمال الدين",
            name_en="Dr. Marwa Kamal",
            title="specialist",
            examination_fee=250.0,
            consultation_fee=100.0,
            is_active=True,
        )
        tarek = Doctor(
            specialty_id=peds.id,
            name_ar="د. طارق العوضي",
            name_en="Dr. Tarek El-Awady",
            title="consultant",
            examination_fee=300.0,
            consultation_fee=120.0,
            is_active=True,
        )
        session.add_all([sherif, marwa, tarek])
        await session.flush()

        # Doctor schedules:
        # Sherif: Saturday (day 0, 18:00-22:00, cap 2) -> Low-capacity shift for testing
        # Sherif: Monday (day 2, 18:00-22:00, cap 5)
        # Marwa: Wednesday (day 4, 17:00-20:00, cap 5)
        # Tarek: Sunday (day 1, 16:00-19:00, cap 4)
        sched_sat = DoctorSchedule(
            doctor_id=sherif.id,
            day_of_week=0,
            start_time=dt.time(18, 0),
            end_time=dt.time(22, 0),
            max_capacity=2,
            is_active=True,
        )
        sched_mon = DoctorSchedule(
            doctor_id=sherif.id,
            day_of_week=2,
            start_time=dt.time(18, 0),
            end_time=dt.time(22, 0),
            max_capacity=5,
            is_active=True,
        )
        sched_wed = DoctorSchedule(
            doctor_id=marwa.id,
            day_of_week=4,
            start_time=dt.time(17, 0),
            end_time=dt.time(20, 0),
            max_capacity=5,
            is_active=True,
        )
        sched_sun = DoctorSchedule(
            doctor_id=tarek.id,
            day_of_week=1,
            start_time=dt.time(16, 0),
            end_time=dt.time(19, 0),
            max_capacity=4,
            is_active=True,
        )
        session.add_all([sched_sat, sched_mon, sched_wed, sched_sun])
        await session.commit()

    # 2. Rebind singletons to isolated test session_factory
    monkeypatch.setattr(doctor_availability_tool, "session_factory", factory)
    monkeypatch.setattr(appointment_booking_tool, "session_factory", factory)
    monkeypatch.setattr(manage_appointment_tool, "session_factory", factory)
    monkeypatch.setattr(receptionist_handoff_tool, "session_factory", factory)

    if clinic_kb_retriever is not None:
        monkeypatch.setattr(clinic_knowledge_search_tool, "retriever", clinic_kb_retriever)

    # 3. Freeze Cairo clock in every module using patch (which resolves correctly via sys.modules)
    with (
        patch("src.tools.doctor_availability.get_cairo_today", return_value=TODAY_SAT),
        patch("src.tools.appointment_booking.get_cairo_today", return_value=TODAY_SAT),
        patch("src.tools.appointment_booking.get_cairo_now", return_value=NOW_MORNING),
        patch("src.tools.manage_appointment.get_cairo_today", return_value=TODAY_SAT),
        patch("src.tools.manage_appointment.get_cairo_now", return_value=NOW_MORNING),
        patch("src.tools.human_handoff.get_cairo_today", return_value=TODAY_SAT),
        patch("src.tools.human_handoff.get_cairo_now", return_value=NOW_MORNING),
    ):
        yield factory
    await engine.dispose()


# ==============================================================================
# Group 1: Registry Contract (R1 - R4)
# ==============================================================================


def test_tool_registry_contains_all_five_clinic_tools():
    """R1: Verify TOOL_REGISTRY exposes all 5 clinic tools bound to their 3.1 schemas."""
    expected = {
        "check_doctor_availability": (
            DoctorAvailabilityInput,
            DoctorAvailabilityOutput,
        ),
        "book_appointment": (
            AppointmentBookingInput,
            AppointmentBookingOutput,
        ),
        "manage_appointment": (
            ManageAppointmentInput,
            ManageAppointmentOutput,
        ),
        "search_clinic_knowledge": (
            ClinicKnowledgeSearchInput,
            ClinicKnowledgeSearchOutput,
        ),
        "transfer_to_receptionist": (
            ReceptionistHandoffInput,
            ReceptionistHandoffOutput,
        ),
    }

    for name, (in_schema, out_schema) in expected.items():
        assert name in TOOL_REGISTRY, f"Tool '{name}' must be registered in TOOL_REGISTRY"
        tdef = TOOL_REGISTRY[name]
        assert tdef.input_schema is in_schema
        assert tdef.output_schema is out_schema
        assert callable(tdef.sync_callable)
        assert callable(tdef.async_callable)
        assert len(tdef.description) >= 20


def test_get_tool_definitions_openai_format_compliance():
    """R2: Verify get_tool_definitions returns valid OpenAI/Groq function schemas."""
    definitions = get_tool_definitions()
    by_name = {d["function"]["name"]: d for d in definitions if "function" in d}

    for tool_name in CLINIC_TOOLS:
        assert tool_name in by_name, f"Tool '{tool_name}' missing from get_tool_definitions"
        entry = by_name[tool_name]
        assert entry["type"] == "function"
        func = entry["function"]
        assert isinstance(func["name"], str) and len(func["name"]) > 0
        assert isinstance(func["description"], str) and len(func["description"]) > 10

        params = func["parameters"]
        assert params.get("type") == "object"
        assert "properties" in params and isinstance(params["properties"], dict)
        assert len(params["properties"]) > 0

        required = params.get("required", [])
        assert isinstance(required, list)
        assert set(required).issubset(set(params["properties"].keys()))


def test_internal_parameters_not_exposed_to_llm():
    """R3: Verify internal-only parameters are never exposed in LLM-facing schemas."""
    forbidden = {"session_id", "session_factory", "timeout_s", "auto_commit"}
    for item in get_tool_definitions():
        func = item["function"]
        props = set(func["parameters"]["properties"].keys())
        overlap = props.intersection(forbidden)
        assert not overlap, f"Tool '{func['name']}' exposes internal parameter(s) to LLM: {overlap}"


@pytest.mark.asyncio
async def test_registry_callables_route_to_singletons(harness):
    """R4: Verify dispatcher execution routes to rebound singletons and uses the test DB."""
    # check_doctor_availability via async_execute_tool
    res = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": "2026-10-26"},
    )
    assert isinstance(res, ToolResult)
    assert res.success is True
    assert res.data["has_shift"] is True
    assert res.data["remaining_capacity"] == 5


# ==============================================================================
# Group 2: End-to-End Patient Journeys (R5 - R8)
# ==============================================================================


@pytest.mark.asyncio
async def test_journey_happy_path_booking_and_lookup(harness):
    """R5: Full booking journey: check availability -> book -> lookup confirmed booking."""
    phone = "01012345678"
    patient_name = "أحمد مصطفى"

    # Step 1: Availability lookup for Monday 2026-10-26
    avail_res = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": "2026-10-26"},
    )
    assert avail_res.success is True
    assert avail_res.data["remaining_capacity"] == 5
    doctor_id = avail_res.data["doctor_id"]

    # Step 2: Book appointment
    book_res = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": patient_name,
            "patient_phone": phone,
            "doctor_id": doctor_id,
            "date": "2026-10-26",
            "visit_type": "examination",
        },
    )
    assert book_res.success is True
    assert "booking_code" in book_res.data
    booking_code = book_res.data["booking_code"]
    assert book_res.data["queue_number"] == 1
    assert book_res.data["fee"] == 350.0
    assert book_res.data["patient_name"] == patient_name
    assert "APT-20261026" in booking_code

    # Step 3: Lookup booking by code and phone
    lookup_res = await async_execute_tool(
        "manage_appointment",
        {
            "action": "lookup",
            "booking_code": booking_code,
            "phone": phone,
        },
    )
    assert lookup_res.success is True
    assert len(lookup_res.data["appointments"]) >= 1
    found_appt = lookup_res.data["appointments"][0]
    assert found_appt["booking_code"] == booking_code
    assert found_appt["status"] == "confirmed"
    assert found_appt["doctor_name_ar"] == "د. أحمد محمود الشريف"
    assert found_appt["appointment_date"] == "2026-10-26"


@pytest.mark.asyncio
async def test_journey_reschedule(harness):
    """R6: Reschedule journey: moves appointment to new date, cancels old, keeps doctor."""
    phone = "01099887766"
    patient_name = "خالد نور"

    # 1. Book appointment for Monday 2026-10-26
    book_res = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": patient_name,
            "patient_phone": phone,
            "doctor_name": "الشريف",
            "date": "2026-10-26",
            "visit_type": "examination",
        },
    )
    assert book_res.success is True
    old_code = book_res.data["booking_code"]

    # 2. Reschedule to next Monday 2026-11-02
    resched_res = await async_execute_tool(
        "manage_appointment",
        {
            "action": "reschedule",
            "booking_code": old_code,
            "phone": phone,
            "new_date": "2026-11-02",
        },
    )
    assert resched_res.success is True
    assert resched_res.data["status"] == "rescheduled"
    new_appt = resched_res.data["appointments"][0]
    new_code = new_appt["booking_code"]
    assert new_code != old_code
    assert new_appt["appointment_date"] == "2026-11-02"
    assert new_appt["status"] == "confirmed"

    # 3. Old booking is now cancelled
    old_lookup = await async_execute_tool(
        "manage_appointment",
        {"action": "lookup", "booking_code": old_code, "phone": phone},
    )
    assert old_lookup.success is True
    assert old_lookup.data["appointments"][0]["status"] == "cancelled"

    # 4. New booking is confirmed
    new_lookup = await async_execute_tool(
        "manage_appointment",
        {"action": "lookup", "booking_code": new_code, "phone": phone},
    )
    assert new_lookup.success is True
    assert new_lookup.data["appointments"][0]["status"] == "confirmed"


@pytest.mark.asyncio
async def test_journey_cancel(harness):
    """R7: Cancel journey: booking cancellation marks status and restores free slot."""
    phone = "01155443322"
    date_str = "2026-10-26"

    # Check baseline availability (5 slots)
    pre_avail = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": date_str},
    )
    assert pre_avail.data["remaining_capacity"] == 5

    # Book 1 slot
    book_res = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": "ياسر كمال",
            "patient_phone": phone,
            "doctor_name": "الشريف",
            "date": date_str,
        },
    )
    assert book_res.success is True
    code = book_res.data["booking_code"]

    # Slots drop to 4
    mid_avail = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": date_str},
    )
    assert mid_avail.data["remaining_capacity"] == 4

    # Cancel booking
    cancel_res = await async_execute_tool(
        "manage_appointment",
        {"action": "cancel", "booking_code": code, "phone": phone},
    )
    assert cancel_res.success is True

    # Slots restored to 5
    post_avail = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": date_str},
    )
    assert post_avail.data["remaining_capacity"] == 5


@pytest.mark.asyncio
async def test_journey_capacity_fill_rejection_and_recovery(harness):
    """R8: Fill shift capacity, reject extra booking with suggestion, recover after cancel."""
    # Saturday 2026-10-24 has capacity = 2 for Dr. Sherif
    target_date = "2026-10-24"

    # Patient 1 books
    res1 = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": "مريض أول",
            "patient_phone": "01011110001",
            "doctor_name": "الشريف",
            "date": target_date,
        },
    )
    assert res1.success is True
    assert res1.data["queue_number"] == 1
    code_1 = res1.data["booking_code"]

    # Patient 2 books (shift becomes full)
    res2 = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": "مريض ثان",
            "patient_phone": "01011110002",
            "doctor_name": "الشريف",
            "date": target_date,
        },
    )
    assert res2.success is True
    assert res2.data["queue_number"] == 2

    # Check availability: shift is full
    avail_full = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": target_date},
    )
    assert avail_full.data["is_available"] is False
    assert avail_full.data["remaining_capacity"] == 0

    # Patient 3 tries to book on full shift -> rejected with next available day suggestion
    res3_fail = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": "مريض ثالث",
            "patient_phone": "01011110003",
            "doctor_name": "الشريف",
            "date": target_date,
        },
    )
    assert res3_fail.success is False
    assert res3_fail.error == "shift_full"
    # Should suggest nearest available (e.g. Monday 2026-10-26)
    assert "أقرب يوم متاح" in res3_fail.message
    assert res3_fail.data.get("next_available") is not None

    # Patient 1 cancels
    cancel_res = await async_execute_tool(
        "manage_appointment",
        {"action": "cancel", "booking_code": code_1, "phone": "01011110001"},
    )
    assert cancel_res.success is True

    # Check availability: 1 slot freed
    avail_freed = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": target_date},
    )
    assert avail_freed.data["is_available"] is True
    assert avail_freed.data["remaining_capacity"] == 1

    # Patient 3 retries booking -> now succeeds
    res3_success = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": "مريض ثالث",
            "patient_phone": "01011110003",
            "doctor_name": "الشريف",
            "date": target_date,
        },
    )
    assert res3_success.success is True
    assert res3_success.data["queue_number"] == 3


# ==============================================================================
# Group 3: Cross-Tool State Consistency (R9, R10)
# ==============================================================================


@pytest.mark.asyncio
async def test_cross_tool_remaining_slots_math(harness):
    """R9: Remaining slots must strictly equal max_capacity - confirmed_count."""
    date_str = "2026-10-26"  # Dr. Sherif, max_capacity = 5

    # Book 3 slots
    for i in range(1, 4):
        res = await async_execute_tool(
            "book_appointment",
            {
                "patient_name": f"مريض {i}",
                "patient_phone": f"0120000000{i}",
                "doctor_name": "الشريف",
                "date": date_str,
            },
        )
        assert res.success is True

    # Verify availability matches 5 - 3 = 2
    avail = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": date_str},
    )
    assert avail.data["remaining_capacity"] == 2
    assert avail.data["is_available"] is True

    # Book remaining 2 slots to reach capacity (5)
    for i in range(4, 6):
        fill_res = await async_execute_tool(
            "book_appointment",
            {
                "patient_name": f"مريض {i}",
                "patient_phone": f"0120000000{i}",
                "doctor_name": "الشريف",
                "date": date_str,
            },
        )
        assert fill_res.success is True

    # Now capacity is exhausted: remaining is 0, is_available is False
    avail_full = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": date_str},
    )
    assert avail_full.data["remaining_capacity"] == 0
    assert avail_full.data["is_available"] is False


@pytest.mark.asyncio
async def test_cross_tool_booking_code_integrity_and_privacy(harness):
    """R10: Booking code works across tools; wrong phone rejected without data leak."""
    phone_owner = "01033334444"
    phone_attacker = "01099998888"

    book_res = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": "سامي سعيد",
            "patient_phone": phone_owner,
            "doctor_name": "طارق",
            "date": "2026-10-25",
        },
    )
    assert book_res.success is True
    code = book_res.data["booking_code"]

    # 1. Lookup with wrong phone
    lookup_fail = await async_execute_tool(
        "manage_appointment",
        {"action": "lookup", "booking_code": code, "phone": phone_attacker},
    )
    assert lookup_fail.success is False
    assert "phone_mismatch" in lookup_fail.error
    assert "سامي سعيد" not in lookup_fail.message

    # 2. Cancel with wrong phone
    cancel_fail = await async_execute_tool(
        "manage_appointment",
        {"action": "cancel", "booking_code": code, "phone": phone_attacker},
    )
    assert cancel_fail.success is False
    assert "phone_mismatch" in cancel_fail.error

    # 3. Reschedule with wrong phone
    resched_fail = await async_execute_tool(
        "manage_appointment",
        {
            "action": "reschedule",
            "booking_code": code,
            "phone": phone_attacker,
            "new_date": "2026-11-01",
        },
    )
    assert resched_fail.success is False
    assert "phone_mismatch" in resched_fail.error


# ==============================================================================
# Group 4: Concurrency (R11)
# ==============================================================================


@pytest.mark.asyncio
async def test_concurrency_race_condition_capacity_cap(harness):
    """R11: Concurrent booking calls for capacity-2 shift yield exactly 2 successes."""
    target_date = "2026-10-24"  # Saturday shift: cap = 2

    # Launch 6 concurrent bookings
    tasks = [
        async_execute_tool(
            "book_appointment",
            {
                "patient_name": f"متصل متزامن {i}",
                "patient_phone": f"0107777000{i}",
                "doctor_name": "الشريف",
                "date": target_date,
            },
        )
        for i in range(1, 7)
    ]
    results = await asyncio.gather(*tasks)

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]

    assert len(successes) == 2, f"Expected exactly 2 successes, got {len(successes)}"
    assert len(failures) == 4, f"Expected 4 failures due to capacity, got {len(failures)}"

    # Successful bookings must have unique queue numbers (1 and 2)
    queue_numbers = sorted([s.data["queue_number"] for s in successes])
    assert queue_numbers == [1, 2]

    # Verify directly from database
    async with harness() as session:
        stmt = (
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.appointment_date == dt.date(2026, 10, 24),
                Appointment.status == "confirmed",
            )
        )
        db_count = await session.scalar(stmt)
        assert db_count == 2


# ==============================================================================
# Group 5: Escalation & Safety (R12, R13)
# ==============================================================================


@pytest.mark.asyncio
async def test_emergency_escalation_dispatcher_persists_ticket(harness):
    """R12: Emergency phrase triggers upgrade, 123 prompt, and persisted ticket in DB."""
    emergency_text = "المريض بيشتكي من ألم شديد في الصدر وضيق تنفس حاد"
    res = await async_execute_tool(
        "transfer_to_receptionist",
        {
            "reason": emergency_text,
            "caller_name": "عادل إمام",
            "caller_phone": "01012345678",
            "urgency": "medium",  # LLM sent medium, but safety net must upgrade to emergency
        },
    )

    assert res.success is True
    assert res.data["urgency"] == "emergency"
    assert res.data["transfer_requested"] is True
    assert "123" in res.message
    ticket_id = res.data["ticket_id"]
    assert ticket_id.startswith("ESC-20261024")

    # Verify escalation ticket in DB via repository
    async with harness() as session:
        repo = ClinicRepository(session)
        open_tickets = await repo.list_open_escalations()
        assert any(t.ticket_id == ticket_id and t.urgency == "emergency" for t in open_tickets)


@pytest.mark.asyncio
async def test_booking_failure_suggests_reception_when_no_slots(harness):
    """R13: When no shifts exist in lookahead window, booking offers receptionist handoff."""
    # Create a temporary doctor with no schedules in DB
    async with harness() as session:
        inactive_doc = Doctor(
            specialty_id=1,
            name_ar="د. هشام زكي",
            name_en="Dr. Hesham Zaki",
            examination_fee=200.0,
            consultation_fee=100.0,
            is_active=True,
        )
        session.add(inactive_doc)
        await session.commit()

    res = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": "مريض تجريبي",
            "patient_phone": "01000009999",
            "doctor_name": "هشام زكي",
            "date": "2026-10-24",
        },
    )

    assert res.success is False
    assert res.error == "no_shift"
    assert "الاستقبال" in res.message or "أحولك" in res.message


# ==============================================================================
# Group 6: Knowledge Search (R14, R15)
# ==============================================================================


@pytest.mark.asyncio
async def test_knowledge_search_clinic_fees_grounded(harness, clinic_kb_retriever):
    """R14: Query about fees/prep retrieves grounded clinic knowledge."""
    if clinic_kb_retriever is None:
        pytest.skip("FastEmbed semantic embeddings not available on this machine")

    res = await async_execute_tool(
        "search_clinic_knowledge",
        {"query": "سعر كشف الباطنة والجهاز الهضمي كام؟"},
    )
    assert res.success is True
    assert res.data.get("found") is True
    assert len(res.data.get("chunks", [])) > 0
    assert len(res.message) > 0


@pytest.mark.asyncio
async def test_knowledge_search_medical_guardrail_refusal(harness, clinic_kb_retriever):
    """R15: Diagnostic/prescription query enforces medical guardrail."""
    if clinic_kb_retriever is None:
        pytest.skip("FastEmbed semantic embeddings not available on this machine")

    res = await async_execute_tool(
        "search_clinic_knowledge",
        {"query": "عندي وجع فظيع في بطني واسهال اكتبلي جرعة مضاد حيوي"},
    )
    assert res.success is True
    # Guardrail check: must not diagnose or recommend drug dosage
    assert (
        res.data.get("escalation_recommended") is True
        or "طوارئ" in res.message
        or "123" in res.message
        or "الاستقبال" in res.message
        or "طبيب" in res.message
        or "عيادة" in res.message
        or "حظر" in res.message
        or "سلامتكم" in res.message
    )


# ==============================================================================
# Group 7: Cross-Cutting Invariants (R16 - R19)
# ==============================================================================


@pytest.mark.parametrize("tool_name", CLINIC_TOOLS)
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"invalid_key": 99999, "nested": {"bad": True}},
        {"date": "not-a-valid-date-format", "party_size": 5},
    ],
)
def test_all_five_tools_never_raise_on_invalid_or_empty_sync(harness, tool_name, payload):
    """R16 (Sync): execute_tool never raises unhandled exception on malformed payload."""
    res = execute_tool(tool_name, payload)
    assert isinstance(res, ToolResult)
    assert len(res.message) > 0


@pytest.mark.parametrize("tool_name", CLINIC_TOOLS)
@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"invalid_key": 99999, "nested": {"bad": True}},
        {"date": "not-a-valid-date-format", "party_size": 5},
    ],
)
@pytest.mark.asyncio
async def test_all_five_tools_never_raise_on_invalid_or_empty_async(harness, tool_name, payload):
    """R16 (Async): async_execute_tool never raises unhandled exception on malformed payload."""
    res = await async_execute_tool(tool_name, payload)
    assert isinstance(res, ToolResult)
    assert len(res.message) > 0


@pytest.mark.asyncio
async def test_all_tools_messages_contain_arabic_and_errors_on_failure(harness):
    """R17: Spoken message contains Arabic text; failure carries non-empty error string."""
    # Failure case: lookup non-existent code
    fail_res = await async_execute_tool(
        "manage_appointment",
        {"action": "lookup", "booking_code": "APT-99999999-D1Q1"},
    )
    assert fail_res.success is False
    assert fail_res.error is not None and len(fail_res.error) > 0
    assert ARABIC_RE.search(fail_res.message) is not None, "Message must contain Arabic characters"

    # Success case: check doctor availability
    succ_res = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": "2026-10-26"},
    )
    assert succ_res.success is True
    assert succ_res.error is None
    assert ARABIC_RE.search(succ_res.message) is not None, "Message must contain Arabic characters"


def test_sync_and_async_dispatchers_equivalence(harness):
    """R18: Sync execute_tool and async async_execute_tool produce equivalent results."""
    args = {"doctor_name_or_id": "الشريف", "date": "2026-10-26"}
    sync_res = execute_tool("check_doctor_availability", args)
    async_res = asyncio.run(async_execute_tool("check_doctor_availability", args))

    assert sync_res.success == async_res.success
    assert sync_res.data["remaining_capacity"] == async_res.data["remaining_capacity"]
    assert sync_res.data["has_shift"] == async_res.data["has_shift"]


@pytest.mark.asyncio
async def test_no_raw_caller_phone_in_logs(harness, caplog: pytest.LogCaptureFixture):
    """R19: Captured logs during booking and management never expose raw patient phone."""
    secret_phone = "01099881122"
    with caplog.at_level(logging.DEBUG, logger="src"):
        await async_execute_tool(
            "book_appointment",
            {
                "patient_name": "حامد شاكر",
                "patient_phone": secret_phone,
                "doctor_name": "الشريف",
                "date": "2026-10-26",
            },
        )
        await async_execute_tool(
            "manage_appointment",
            {
                "action": "lookup",
                "phone": secret_phone,
            },
        )

    src_logs = "\n".join(rec.getMessage() for rec in caplog.records if rec.name.startswith("src"))
    assert secret_phone not in src_logs, "Raw patient phone number leaked into application logs!"


# ==============================================================================
# Group 8: Latency Smoke Check (NFR-4)
# ==============================================================================


@pytest.mark.asyncio
async def test_async_dispatcher_latency_smoke(harness):
    """NFR-4: Each DB-backed async tool call on a warm DB completes in < 1.5 seconds."""
    # Warm-up call
    await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": "2026-10-26"},
    )

    # 1. Availability check latency
    t0 = time.perf_counter()
    res1 = await async_execute_tool(
        "check_doctor_availability",
        {"doctor_name_or_id": "الشريف", "date": "2026-10-26"},
    )
    t1 = time.perf_counter()
    assert res1.success is True
    assert (t1 - t0) < 1.5, f"check_doctor_availability took {t1 - t0:.3f}s (> 1.5s)"

    # 2. Booking call latency
    t2 = time.perf_counter()
    res2 = await async_execute_tool(
        "book_appointment",
        {
            "patient_name": "مريض السرعة",
            "patient_phone": "01088887766",
            "doctor_name": "الشريف",
            "date": "2026-10-26",
        },
    )
    t3 = time.perf_counter()
    assert res2.success is True
    assert (t3 - t2) < 1.5, f"book_appointment took {t3 - t2:.3f}s (> 1.5s)"

    # 3. Lookup call latency
    code = res2.data["booking_code"]
    t4 = time.perf_counter()
    res3 = await async_execute_tool(
        "manage_appointment",
        {"action": "lookup", "booking_code": code, "phone": "01088887766"},
    )
    t5 = time.perf_counter()
    assert res3.success is True
    assert (t5 - t4) < 1.5, f"manage_appointment took {t5 - t4:.3f}s (> 1.5s)"
