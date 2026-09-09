"""
Test suite for RAG Knowledge Search Tool.
"""

from pathlib import Path
import pytest
from src.rag.ingestion import KnowledgeIngestionPipeline
from src.rag.retriever import QdrantKnowledgeRetriever
from src.tools.knowledge_search import KnowledgeSearchTool, search_knowledge, async_search_knowledge
from src.tools.schemas import KnowledgeSearchOutput


@pytest.fixture(scope="module")
def knowledge_tool():
    """Build in-memory retriever populated with restaurant knowledge base."""
    kb_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "restaurant_kb.md"
    pipeline = KnowledgeIngestionPipeline()
    chunks = pipeline.parse_markdown(kb_path)

    test_retriever = QdrantKnowledgeRetriever(collection_name="test_tool_knowledge_kb")
    test_retriever.upsert_chunks(chunks)

    tool = KnowledgeSearchTool(retriever_instance=test_retriever)
    return tool


def test_knowledge_search_menu(knowledge_tool):
    """Test searching for menu items in the knowledge base."""
    # Query: ما هي مكونات شاورما الدجاج؟
    query = "\u0645\u0627 \u0647\u064a \u0645\u0643\u0648\u0646\u0627\u062a \u0634\u0627\u0648\u0631\u0645\u0627 \u0627\u0644\u062f\u062c\u0627\u062c\u061f"
    result = knowledge_tool.execute(query, limit=2)
    assert isinstance(result, KnowledgeSearchOutput)
    assert result.found is True
    assert result.total_results > 0
    assert len(result.chunks) > 0
    # "شاورما"
    assert "\u0634\u0627\u0648\u0631\u0645\u0627" in result.context_text
    assert result.message != ""


def test_knowledge_search_allergens(knowledge_tool):
    """Test dietary and allergy queries."""
    # Query: هل صوص الثومية يحتوي على حليب أو بيض؟
    query = "\u0647\u0644 \u0635\u0648\u0635 \u0627\u0644\u062b\u0648\u0645\u064a\u0629 \u064a\u062d\u062a\u0648\u064a \u0639\u0644\u0649 \u062d\u0644\u064a\u0628 \u0623\u0648 \u0628\u064a\u0636\u061f"
    result = knowledge_tool.execute(query, limit=2)
    assert result.found is True
    # Check for "ثوم" or "بيض" or "حليب"
    has_allergen_kw = any(
        "\u062b\u0648\u0645" in c.content or "\u0628\u064a\u0636" in c.content or "\u062d\u0644\u064a\u0628" in c.content
        for c in result.chunks
    )
    assert has_allergen_kw


def test_knowledge_search_delivery_policy(knowledge_tool):
    """Test delivery policy search with category filter."""
    # Query: مصاريف ورسوم توصيل الدليفري
    query = "\u0645\u0635\u0627\u0631\u064a\u0641 \u0648\u0631\u0633\u0648\u0645 \u062a\u0648\u0635\u064a\u0644 \u0627\u0644\u062f\u0644\u064a\u0641\u0631\u064a"
    result = knowledge_tool.execute(query, limit=2, category="delivery")
    assert result.found is True
    assert any(c.metadata.get("category") == "delivery" for c in result.chunks)


def test_knowledge_search_empty_and_fallback(knowledge_tool):
    """Test empty query and out-of-domain query fallback behavior."""
    # Empty query
    res_empty = knowledge_tool.execute("   ")
    assert res_empty.found is False
    # "بوضوح"
    assert "\u0628\u0648\u0636\u0648\u062d" in res_empty.message

    # Completely unrelated query with high threshold: كيف أصلح محرك السيارة؟
    unrelated_query = "\u0643\u064a\u0641 \u0623\u0635\u0644\u062d \u0645\u062d\u0631\u0643 \u0627\u0644\u0633\u064a\u0627\u0631\u0629\u061f"
    res_unrelated = knowledge_tool.execute(unrelated_query, score_threshold=0.8)
    assert res_unrelated.found is False
    # "لم أجد معلومات مؤكدة"
    assert "\u0644\u0645 \u0623\u062c\u062f \u0645\u0639\u0644\u0648\u0645\u0627\u062a \u0645\u0624\u0643\u062f\u0629" in res_unrelated.message


@pytest.mark.asyncio
async def test_knowledge_search_async(knowledge_tool):
    """Test asynchronous execution for real-time voice agent."""
    # Query: ما هي وجبات الشاورما المتوفرة؟
    query = "\u0645\u0627 \u0647\u064a \u0648\u062c\u0628\u0627\u062a \u0627\u0644\u0634\u0627\u0648\u0631\u0645\u0627 \u0627\u0644\u0645\u062a\u0648\u0641\u0631\u0629\u061f"
    result = await knowledge_tool.aexecute(query, limit=2)
    assert result.found is True
    assert len(result.chunks) > 0
    assert result.message != ""
