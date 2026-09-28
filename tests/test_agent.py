"""
Unit and Integration Tests for Real-Time LiveKit Voice Agent Core Pipeline.

Tests:
1. Plugin Component Factories (Deepgram STT, Groq LLM, ElevenLabs TTS, Silero VAD).
2. LiveKit Function Tools Creation, Execution, and CallSession Integration.
3. Voice Pipeline Assembly (Agent, AgentSession, Instructions, and Tool Bindings).
4. Error Fallback Handling in Live Tool Invocations.
5. Worker Configuration and Prewarm Logic.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from livekit.agents import WorkerType
from livekit.agents.voice import Agent, AgentSession
import livekit.plugins.deepgram as dg
import livekit.plugins.elevenlabs as el
import livekit.plugins.groq as gq
import livekit.plugins.silero as sil

from src.agent.prompts import build_error_fallback_message
from src.agent.session_manager import (
    CallSession,
    CallStatus,
    MessageRole,
)
from src.agent.voice_agent import (
    create_llm,
    create_stt,
    create_tts,
    create_vad,
    create_voice_pipeline,
    create_voice_tools,
    get_worker_options,
    prewarm,
)
from src.config import settings
from src.rag.ingestion import KnowledgeIngestionPipeline
from src.rag.retriever import QdrantKnowledgeRetriever
from src.tools.knowledge_search import knowledge_search_tool


# ==============================================================================
# Test Fixtures
# ==============================================================================

@pytest.fixture(scope="module", autouse=True)
def setup_in_memory_kb():
    """Ensure in-memory Qdrant instance is populated for knowledge retrieval tests."""
    kb_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "restaurant_kb.md"
    pipeline = KnowledgeIngestionPipeline()
    chunks = pipeline.parse_markdown(kb_path)

    test_retriever = QdrantKnowledgeRetriever(collection_name="test_voice_agent_kb")
    test_retriever.upsert_chunks(chunks)

    original_retriever = knowledge_search_tool.retriever
    knowledge_search_tool.retriever = test_retriever
    yield
    knowledge_search_tool.retriever = original_retriever


@pytest.fixture
def fresh_session() -> CallSession:
    """Create a fresh CallSession for testing."""
    session = CallSession(
        room_name="test-voice-room-01",
        participant_identity="caller_test_01",
    )
    session.context.customer_phone = "+201012345678"
    return session


# ==============================================================================
# 1. Plugin Component Factories Tests
# ==============================================================================

def test_create_stt_factory_defaults():
    """Verify Deepgram STT client initialization with defaults and fallback."""
    stt_client = create_stt()
    assert isinstance(stt_client, dg.STT)
    assert stt_client._opts.model == settings.deepgram_model
    assert stt_client._opts.language == settings.deepgram_language


def test_create_stt_factory_custom_params():
    """Verify Deepgram STT client initialization with custom language and key."""
    stt_client = create_stt(language="en-US", api_key="custom_dg_key")
    assert isinstance(stt_client, dg.STT)
    assert stt_client._opts.language == "en-US"
    assert stt_client._api_key == "custom_dg_key"


def test_create_llm_factory():
    """Verify Groq LLM client initialization."""
    llm_client = create_llm(api_key="custom_groq_key")
    assert isinstance(llm_client, gq.LLM)
    assert llm_client._opts.model == settings.groq_model
    assert llm_client._opts.temperature == settings.llm_temperature
    assert llm_client._client.api_key == "custom_groq_key"


def test_create_tts_factory():
    """Verify ElevenLabs TTS client initialization."""
    tts_client = create_tts(api_key="custom_eleven_key")
    assert isinstance(tts_client, el.TTS)
    assert tts_client._opts.model == settings.eleven_model
    assert tts_client._opts.voice_id == settings.eleven_voice_id


def test_create_vad_factory():
    """Verify Silero VAD initialization."""
    vad_client = create_vad()
    assert isinstance(vad_client, sil.VAD)


# ==============================================================================
# 2. LiveKit Function Tools Binding and Execution Tests
# ==============================================================================

def test_create_voice_tools_structure(fresh_session: CallSession):
    """Verify all 4 domain tools are created with descriptions and callable signatures."""
    tools = create_voice_tools(session=fresh_session)
    assert len(tools) == 4

    tool_names = [tool.info.name for tool in tools]
    expected_names = [
        "search_restaurant_knowledge",
        "get_order_status",
        "book_reservation",
        "escalate_to_human",
    ]
    for expected in expected_names:
        assert expected in tool_names

    # Check descriptions
    for tool in tools:
        assert len(tool.info.description) > 20


@pytest.mark.asyncio
async def test_tool_order_status_live_execution(fresh_session: CallSession):
    """Verify get_order_status execution within LiveKit tool binding."""
    tools = {tool.info.name: tool for tool in create_voice_tools(session=fresh_session)}
    order_tool = tools["get_order_status"]

    result_text = await order_tool._func(order_id="ORD-1001", phone="")
    assert "ORD-1001" in result_text
    assert "أحمد السعيد" in result_text or "خرج مع المندوب" in result_text

    # Verify session tracking
    assert fresh_session.context.order_id == "ORD-1001"
    assert fresh_session.metrics.total_tool_calls == 1
    assert len(fresh_session.messages) == 1
    assert fresh_session.messages[0].role == MessageRole.TOOL
    assert fresh_session.messages[0].tool_name == "get_order_status"


@pytest.mark.asyncio
async def test_tool_reservation_live_execution(fresh_session: CallSession):
    """Verify book_reservation execution and context extraction."""
    tools = {tool.info.name: tool for tool in create_voice_tools(session=fresh_session)}
    res_tool = tools["book_reservation"]

    result_text = await res_tool._func(
        customer_name="يوسف الشريف",
        phone_number="01099887766",
        party_size=4,
        date="2026-10-01",
        time="20:00",
        branch="الفرع الرئيسي",
        special_requests="ترابيزة بجوار النافذة",
    )

    assert "تم تأكيد حجزك" in result_text or "RES-" in result_text
    assert fresh_session.context.customer_name == "يوسف الشريف"
    assert fresh_session.context.customer_phone == "01099887766"
    assert fresh_session.context.reservation_draft.get("party_size") == 4
    assert fresh_session.metrics.total_tool_calls == 1


@pytest.mark.asyncio
async def test_tool_escalation_live_execution(fresh_session: CallSession):
    """Verify escalate_to_human execution updates session status to ESCALATED."""
    tools = {tool.info.name: tool for tool in create_voice_tools(session=fresh_session)}
    escalate_tool = tools["escalate_to_human"]

    result_text = await escalate_tool._func(
        reason="العميل غاضب جداً بسبب تأخير الأوردر",
        department="kitchen_manager",
        customer_name="سامر",
        customer_phone="01223344556",
        urgency="high",
    )

    assert "ESC-" in result_text or "تحويل" in result_text
    assert fresh_session.context.escalated is True
    assert fresh_session.context.escalation_department == "kitchen_manager"
    assert fresh_session.status == CallStatus.ESCALATED


@pytest.mark.asyncio
async def test_tool_knowledge_search_live_execution(fresh_session: CallSession):
    """Verify search_restaurant_knowledge queries vector DB and logs turn."""
    tools = {tool.info.name: tool for tool in create_voice_tools(session=fresh_session)}
    search_tool = tools["search_restaurant_knowledge"]

    result_text = await search_tool._func(query="ما هي مواعيد العمل في المطعم؟")
    assert len(result_text) > 10
    assert fresh_session.metrics.total_tool_calls == 1
    assert fresh_session.messages[0].tool_name == "search_restaurant_knowledge"


@pytest.mark.asyncio
async def test_tool_exception_returns_polite_fallback(fresh_session: CallSession):
    """Verify exceptions in tool execution return localized spoken fallback without crashing."""
    with patch(
        "src.agent.voice_agent.async_get_order_status",
        side_effect=RuntimeError("Database connection timed out"),
    ):
        tools = {tool.info.name: tool for tool in create_voice_tools(session=fresh_session)}
        order_tool = tools["get_order_status"]

        result_text = await order_tool._func(order_id="ORD-9999", phone="")
        expected_fallback = build_error_fallback_message(language="ar")
        assert result_text == expected_fallback


# ==============================================================================
# 3. Voice Pipeline Assembler Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_create_voice_pipeline_defaults(fresh_session: CallSession):
    """Verify complete pipeline assembly with default configuration."""
    agent_session, agent = create_voice_pipeline(session=fresh_session)

    assert isinstance(agent_session, AgentSession)
    assert isinstance(agent, Agent)

    # Verify agent instructions include persona
    assert settings.agent_name in agent.instructions
    assert settings.restaurant_name in agent.instructions

    # Verify tools bound to Agent
    assert len(agent.tools) == 4
    tool_names = [tool.info.name for tool in agent.tools]
    assert "search_restaurant_knowledge" in tool_names
    assert "get_order_status" in tool_names


@pytest.mark.asyncio
async def test_create_voice_pipeline_custom_instructions_and_english(fresh_session: CallSession):
    """Verify custom instructions and English language propagation."""
    custom_note = "Today we have a special 15% discount on grilled platters."
    agent_session, agent = create_voice_pipeline(
        session=fresh_session,
        custom_instructions=custom_note,
        language="en",
    )

    assert custom_note in agent.instructions
    assert "Speak in fluent, polite, and warm English." in agent.instructions


# ==============================================================================
# 4. Worker Configuration & Prewarm Tests
# ==============================================================================

def test_get_worker_options():
    """Verify LiveKit WorkerOptions configuration."""
    options = get_worker_options()
    assert options.worker_type == WorkerType.ROOM
    assert callable(options.entrypoint_fnc)
    assert callable(options.prewarm_fnc)


def test_prewarm_loads_vad():
    """Verify prewarm callback populates userdata with Silero VAD."""
    mock_proc = MagicMock()
    mock_proc.userdata = {}

    prewarm(mock_proc)
    assert "vad" in mock_proc.userdata
    assert isinstance(mock_proc.userdata["vad"], sil.VAD)
