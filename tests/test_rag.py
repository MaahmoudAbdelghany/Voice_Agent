"""
Unit and Integration Tests for Clinic RAG Knowledge Base & Vector Retriever.
"""

from pathlib import Path

import pytest

from src.config import VALID_CLINIC_CATEGORIES
from src.rag.embeddings import EmbeddingService
from src.rag.ingestion import KnowledgeIngestionPipeline
from src.rag.retriever import QdrantKnowledgeRetriever


@pytest.fixture
def embedding_service():
    return EmbeddingService()


@pytest.fixture
def local_retriever():
    # Force fresh in-memory collection for test isolation
    ret = QdrantKnowledgeRetriever(collection_name="test_rag_unit_kb")
    ret.recreate_collection()
    return ret


def test_embedding_generation(embedding_service):
    """Test generating embeddings for clinic query and batch documents."""
    assert embedding_service.dimension == 384

    query_vec = embedding_service.embed_query("مواعيد عيادة الباطنة وأسعار الكشف")
    assert isinstance(query_vec, list)
    assert len(query_vec) == 384
    assert any(x != 0.0 for x in query_vec)

    doc_vecs = embedding_service.embed_documents(["عيادة الأطفال", "معمل التحاليل والأشعة"])
    assert len(doc_vecs) == 2
    assert len(doc_vecs[0]) == 384
    assert len(doc_vecs[1]) == 384


def test_retriever_upsert_and_search(local_retriever):
    """Test indexing and semantic searching clinic chunks in in-memory Qdrant."""
    sample_chunks = [
        {
            "id": "clinic_pricing",
            "text": "سعر كشف الباطنة الاستشاري 350 جنيه والاستشارة مجانية خلال 14 يوماً.",
            "metadata": {"category": "pricing", "section": "أسعار الكشف"},
        },
        {
            "id": "clinic_lab",
            "text": "تحليل السكر الصائم والدهون الثلاثية يتطلب صيام من 8 إلى 12 ساعة.",
            "metadata": {"category": "lab_radiology", "section": "تعليمات الصيام"},
        },
        {
            "id": "clinic_insurance",
            "text": "يقبل المركز بطاقات التأمين الصحي لشركات أكسا وميتلايف وميدنت.",
            "metadata": {"category": "insurance", "section": "شركات التأمين"},
        },
    ]

    count = local_retriever.upsert_chunks(sample_chunks)
    assert count == 3

    results = local_retriever.search("شروط الصيام قبل تحليل السكر", limit=2)
    assert len(results) > 0
    top_hit = results[0]
    assert "صيام" in top_hit["text"] or "السكر" in top_hit["text"]
    assert top_hit["score"] is not None

    # Test category filter
    insurance_results = local_retriever.search("تأمين أكسا", category="insurance")
    assert len(insurance_results) >= 1
    assert insurance_results[0]["category"] == "insurance"

    # Test context string formatting
    context = local_retriever.get_context_for_query("سعر كشف الباطنة")
    assert isinstance(context, str)
    assert len(context) > 0


def test_knowledge_ingestion_pipeline():
    """T1.7, T2.1: Test parsing and Qdrant ingestion/retrieval of knowledge_base/clinic_kb.md."""
    kb_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "clinic_kb.md"
    assert kb_path.exists(), "clinic_kb.md must exist"

    pipeline = KnowledgeIngestionPipeline()
    chunks = pipeline.parse_markdown(kb_path)

    assert len(chunks) >= 20, f"Expected at least 20 clinic chunks, found {len(chunks)}"

    categories = {chunk["metadata"]["category"] for chunk in chunks}
    # Every chunk category must belong strictly to recognized clinic categories
    assert categories.issubset(VALID_CLINIC_CATEGORIES)
    assert "pricing" in categories
    assert "lab_radiology" in categories
    assert "insurance" in categories
    assert "safety_guardrails" in categories
    for legacy_cat in ("menu", "allergens", "delivery", "reservations", "catering"):
        assert legacy_cat not in categories

    # Verify end-to-end ingestion into in-memory retriever
    test_retriever = QdrantKnowledgeRetriever(collection_name="test_pipeline_clinic_kb")
    pipeline.retriever = test_retriever
    indexed_count = pipeline.ingest_file(kb_path)
    assert indexed_count == len(chunks)

    # Verify querying the ingested clinic knowledge
    search_hits = test_retriever.search("شركات التأمين الصحي المعتمدة أكسا", limit=3)
    assert len(search_hits) > 0
    assert any("تأمين" in hit["text"] or "أكسا" in hit["text"] for hit in search_hits)
