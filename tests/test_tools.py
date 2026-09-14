"""
Unit Tests for Centralized Tools Registry and Function Calling Dispatchers.
"""

from pathlib import Path
import pytest

from src.rag.ingestion import KnowledgeIngestionPipeline
from src.rag.retriever import QdrantKnowledgeRetriever
from src.tools import (
    TOOL_REGISTRY,
    KnowledgeSearchTool,
    ToolDefinition,
    ToolResult,
    async_execute_tool,
    execute_tool,
    get_registered_tools,
    get_tool_definitions,
    knowledge_search_tool,
    order_status_tool,
    reservation_tool,
    human_handoff_tool,
)


@pytest.fixture(scope="module", autouse=True)
def setup_knowledge_tool():
    """Ensure knowledge_search_tool has an in-memory collection for tool execution tests."""
    kb_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "restaurant_kb.md"
    pipeline = KnowledgeIngestionPipeline()
    chunks = pipeline.parse_markdown(kb_path)

    test_retriever = QdrantKnowledgeRetriever(collection_name="test_registry_knowledge_kb")
    test_retriever.upsert_chunks(chunks)

    # Attach to singleton instance for centralized dispatcher testing
    original_retriever = knowledge_search_tool.retriever
    knowledge_search_tool.retriever = test_retriever
    yield knowledge_search_tool
    knowledge_search_tool.retriever = original_retriever


def test_tool_registry_contains_all_tools():
    """Verify all 4 core domain tools are registered with complete bindings."""
    registry = get_registered_tools()
    expected_tools = {
        "search_restaurant_knowledge",
        "get_order_status",
        "book_reservation",
        "escalate_to_human",
    }
    assert expected_tools.issubset(set(registry.keys()))

    for tool_name, tool_def in registry.items():
        assert isinstance(tool_def, ToolDefinition)
        assert tool_def.name == tool_name
        assert len(tool_def.description) > 10
        assert tool_def.input_schema is not None
        assert tool_def.output_schema is not None
        assert callable(tool_def.sync_callable)
        assert callable(tool_def.async_callable)


def test_get_tool_definitions_openai_format():
    """Verify tool definitions match OpenAI / Groq function calling specification."""
    definitions = get_tool_definitions()
    assert len(definitions) >= 4

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


def test_execute_order_status_tool_success():
    """Verify synchronous execution of get_order_status via central dispatcher."""
    result = execute_tool(
        tool_name="get_order_status",
        arguments={"order_id": "ORD-1001"},
    )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "ORD-1001" in result.message
    assert result.data is not None
    assert result.data["order_id"] == "ORD-1001"
    assert result.data["customer_name"] == "أحمد السعيد"


def test_execute_reservation_tool_success():
    """Verify synchronous execution of book_reservation via central dispatcher."""
    result = execute_tool(
        tool_name="book_reservation",
        arguments={
            "customer_name": "حازم إمام",
            "phone_number": "01099887766",
            "party_size": 4,
            "date": "2026-09-25",
            "time": "20:30",
            "branch": "فرع مدينة نصر",
        },
    )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "حازم إمام" in result.message
    assert "RES-" in result.data["reservation_id"]
    assert result.data["party_size"] == 4


def test_execute_human_handoff_tool_success():
    """Verify synchronous execution of escalate_to_human via central dispatcher."""
    result = execute_tool(
        tool_name="escalate_to_human",
        arguments={
            "reason": "تأخر المندوب أكثر من ساعة والعميل يطلب إلغاء الطلب",
            "customer_name": "إيهاب جلال",
            "customer_phone": "01234567890",
        },
    )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert "ESC-" in result.data["handoff_id"]
    assert result.data["status"] in ["queued", "transferred"]
    assert "إيهاب جلال" in result.message


def test_execute_knowledge_search_tool_success():
    """Verify synchronous execution of search_restaurant_knowledge via central dispatcher."""
    result = execute_tool(
        tool_name="search_restaurant_knowledge",
        arguments={"query": "ما هي مكونات شاورما الدجاج؟"},
    )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.data["found"] is True
    assert len(result.data["chunks"]) > 0


def test_execute_unregistered_tool():
    """Verify executing an unknown tool fails safely with user-friendly message."""
    result = execute_tool(
        tool_name="non_existent_tool",
        arguments={"param": 123},
    )
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "غير متاحة حالياً" in result.message
    assert "non_existent_tool" in result.error


def test_execute_tool_invalid_arguments():
    """Verify validation errors return safe error ToolResult without unhandled exception."""
    result = execute_tool(
        tool_name="book_reservation",
        arguments={"party_size": 2},  # Missing required name, phone, date, time
    )
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "حدث خطأ أثناء تنفيذ هذا الإجراء" in result.message
    assert result.error is not None


@pytest.mark.asyncio
async def test_async_execute_tool_success():
    """Verify asynchronous execution dispatcher (non-blocking for LiveKit turns)."""
    result = await async_execute_tool(
        tool_name="get_order_status",
        arguments={"order_id": "ORD-1002"},
    )
    assert isinstance(result, ToolResult)
    assert result.success is True
    assert result.data["order_id"] == "ORD-1002"
    assert result.data["customer_name"] == "سارة القحطاني"


@pytest.mark.asyncio
async def test_async_execute_tool_unregistered():
    """Verify asynchronous dispatcher handles missing tools gracefully."""
    result = await async_execute_tool(
        tool_name="unknown_async_tool",
        arguments={},
    )
    assert isinstance(result, ToolResult)
    assert result.success is False
    assert "غير متاحة حالياً" in result.message


def test_singletons_exported():
    """Verify singleton tool instances are properly exported and accessible."""
    assert order_status_tool is not None
    assert reservation_tool is not None
    assert human_handoff_tool is not None
    assert knowledge_search_tool is not None
