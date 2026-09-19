"""
Unit tests for Call Session State, Memory, and Context Tracking (SessionManager).
"""

import tempfile
from pathlib import Path
from src.agent.session_manager import (
    CallMetrics,
    CallSession,
    CallStatus,
    ExtractedContext,
    MessageRole,
    SessionManager,
    TurnMessage,
)


def test_session_lifecycle_and_messages():
    """Verify session creation, adding turns, and status transitions."""
    session = CallSession(room_name="test-room", participant_identity="caller-01")
    assert session.status == CallStatus.INITIATED
    assert len(session.messages) == 0

    # User speaks
    user_turn = session.add_user_message("عايز أعرف مواعيد العمل", stt_latency_ms=120.0)
    assert user_turn.role == MessageRole.USER
    assert user_turn.content == "عايز أعرف مواعيد العمل"
    assert session.status == CallStatus.ACTIVE
    assert session.metrics.total_user_turns == 1

    # Assistant speaks
    assistant_turn = session.add_assistant_message(
        "أهلاً بحضرتك، المطعم مفتوح يومياً من 11 صباحاً حتى 10 مساءً.",
        latency_ms=250.0,
        llm_latency_ms=150.0,
        tts_latency_ms=100.0,
    )
    assert assistant_turn.role == MessageRole.ASSISTANT
    assert session.metrics.total_assistant_turns == 1
    assert session.metrics.average_latency_ms > 0
    assert session.metrics.max_latency_ms == 250.0

    # End call
    session.end_call()
    assert session.status == CallStatus.ENDED
    assert session.end_time is not None
    assert session.metrics.duration_seconds >= 0.0


def test_interruption_recording():
    """Verify barge-in / interruption detection and metrics."""
    session = CallSession()
    session.add_assistant_message("لدينا اليوم عرض خاص على وجبات...")
    assert session.metrics.total_interruptions == 0
    assert session.messages[-1].interrupted is False

    session.record_interruption()
    assert session.metrics.total_interruptions == 1
    assert session.messages[-1].interrupted is True


def test_tool_call_context_extraction():
    """Verify context and slot extraction upon tool execution."""
    session = CallSession()

    # 1. Order status tool extracts order_id
    session.record_tool_call(
        tool_name="get_order_status",
        arguments={"order_id": "ORD-1002"},
        result={"status": "out_for_delivery", "eta_minutes": 15},
    )
    assert session.context.order_id == "ORD-1002"
    assert session.metrics.total_tool_calls == 1

    # 2. Reservation tool extracts draft, name, phone
    session.record_tool_call(
        tool_name="book_reservation",
        arguments={
            "customer_name": "أحمد محمود",
            "phone": "+201012345678",
            "party_size": 4,
            "date": "2026-09-25",
            "time_slot": "19:00",
        },
        result={"success": True, "reservation_id": "RES-5541"},
    )
    assert session.context.customer_name == "أحمد محمود"
    assert session.context.customer_phone == "+201012345678"
    assert session.context.reservation_draft["reservation_id"] == "RES-5541"

    # 3. Escalation tool updates state and marks escalated
    session.record_tool_call(
        tool_name="escalate_to_human",
        arguments={"reason": "Customer angry about delay", "department": "Customer Support"},
        result={"success": True, "handoff_id": "ESC-999"},
    )
    assert session.context.escalated is True
    assert session.context.escalation_department == "Customer Support"
    assert session.status == CallStatus.ESCALATED


def test_sliding_window_conversation_history():
    """Verify history formatting with sliding window for LLM context."""
    session = CallSession()
    session.add_turn(role=MessageRole.SYSTEM, content="You are a helpful assistant.")
    session.add_turn(role=MessageRole.USER, content="Hello")
    session.add_turn(role=MessageRole.ASSISTANT, content="Hi there!")
    session.add_turn(role=MessageRole.USER, content="What is on the menu?")
    session.add_turn(role=MessageRole.ASSISTANT, content="We have shawarma and grills.")

    # All turns including system
    all_history = session.get_conversation_history(include_system=True)
    assert len(all_history) == 5
    assert all_history[0]["role"] == "system"

    # Sliding window of last 2 turns, keeping system message intact
    windowed = session.get_conversation_history(max_turns=2, include_system=True)
    assert len(windowed) == 3  # System + last 2 turns
    assert windowed[0]["role"] == "system"
    assert windowed[1]["content"] == "What is on the menu?"
    assert windowed[2]["content"] == "We have shawarma and grills."


def test_session_manager_persistence_and_metrics():
    """Verify saving to disk, loading, and aggregate metrics."""
    with tempfile.TemporaryDirectory() as tmpdir:
        manager = SessionManager(storage_dir=tmpdir)

        # Create session 1
        s1 = manager.create_session(
            room_name="room-1",
            participant_identity="user-1",
            language="ar",
            customer_phone="+201112223333",
        )
        s1.add_user_message("مرحبا")
        s1.add_assistant_message("أهلاً وسهلاً", latency_ms=100.0)
        s1.end_call()
        manager.save_session(s1.session_id)

        # Create session 2 (escalated)
        s2 = manager.create_session(room_name="room-2")
        s2.record_tool_call(
            tool_name="escalate_to_human",
            arguments={"reason": "complaint", "department": "Management"},
            result={"success": True},
        )
        s2.end_call()
        manager.save_session(s2.session_id)

        # Verify disk loading in a fresh manager instance
        fresh_manager = SessionManager(storage_dir=tmpdir)
        loaded_sessions = fresh_manager.load_all_persisted_sessions()
        assert len(loaded_sessions) == 2

        loaded_s1 = fresh_manager.get_session(s1.session_id)
        assert loaded_s1 is not None
        assert loaded_s1.context.customer_phone == "+201112223333"
        assert len(loaded_s1.messages) == 2

        # Verify aggregate metrics
        metrics = fresh_manager.get_aggregated_metrics()
        assert metrics["total_calls"] == 2
        assert metrics["escalated_calls"] == 1
        assert metrics["total_tool_calls"] == 1
        assert metrics["average_latency_ms"] == 100.0
