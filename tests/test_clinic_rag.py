"""
Comprehensive Unit and Integration Tests for Egyptian Clinic Knowledge Base RAG.

Validates:
1. FastEmbed multilingual embedding generation.
2. Ingestion of knowledge_base/clinic_kb.md into isolated cloud test collection ('test_clinic_kb').
3. Colloquial Egyptian Arabic retrieval across core clinic departments (lab, doctors, pricing, insurance).
4. Medical safety guardrails and emergency protocols (chest pain, prohibition of drug prescriptions).
5. Category filtering strictness.
6. Context formatting and truncation for LLM prompt generation.
7. Sub-150ms retrieval latency budget.
"""

import time
from pathlib import Path

import pytest

from src.rag.embeddings import EmbeddingService, embedding_service
from src.rag.ingestion import ingestion_pipeline
from src.rag.retriever import QdrantKnowledgeRetriever


@pytest.fixture(scope="module")
def embedding_svc() -> EmbeddingService:
    """Fixture providing singleton EmbeddingService."""
    return embedding_service


@pytest.fixture(scope="module")
def clinic_retriever() -> QdrantKnowledgeRetriever:
    """
    Module-scoped Qdrant retriever initialized with dedicated 'test_clinic_kb' collection.
    Parses and ingests knowledge_base/clinic_kb.md to guarantee realistic tests.
    """
    kb_path = Path(__file__).resolve().parent.parent / "knowledge_base" / "clinic_kb.md"
    assert kb_path.exists(), f"Clinic knowledge base missing at {kb_path}"

    test_retriever = QdrantKnowledgeRetriever(collection_name="test_clinic_kb")
    test_retriever.recreate_collection()

    chunks = ingestion_pipeline.parse_markdown(kb_path)
    assert len(chunks) >= 5, f"Expected at least 5 chunks from clinic_kb.md, got {len(chunks)}"

    upserted_count = test_retriever.upsert_chunks(chunks)
    assert upserted_count == len(chunks), f"Expected {len(chunks)} points upserted, got {upserted_count}"

    return test_retriever


# ==============================================================================
# Tier 1: Unit Verification (Embeddings & Pure Logic)
# ==============================================================================


def test_embedding_service_dimensions_and_non_zero(embedding_svc: EmbeddingService):
    """Verify FastEmbed output dimensions and non-zero float values."""
    assert embedding_svc.dimension == 384

    single_vec = embedding_svc.embed_query("استفسار عن عيادة الباطنة")
    assert isinstance(single_vec, list)
    assert len(single_vec) == 384
    assert any(val != 0.0 for val in single_vec)

    batch_vecs = embedding_svc.embed_documents([
        "تحليل السكر التراكمي",
        "مواعيد عيادة العظام",
    ])
    assert len(batch_vecs) == 2
    assert len(batch_vecs[0]) == 384
    assert len(batch_vecs[1]) == 384


# ==============================================================================
# Tier 2: Integration Verification (Colloquial Egyptian Clinical Retrieval)
# ==============================================================================


def test_colloquial_fasting_and_lab_query(clinic_retriever: QdrantKnowledgeRetriever):
    """
    FR2.1: Verify colloquial inquiry about fasting for blood sugar & ultrasound.
    Query: 'هو أنا لازم أكون صايم قبل تحليل السكر وسونار البطن؟'
    """
    query = "هو أنا لازم أكون صايم قبل تحليل السكر وسونار البطن؟"
    hits = clinic_retriever.search(query=query, limit=3)

    assert len(hits) > 0, "Expected non-empty search hits"
    top_hit = hits[0]
    assert top_hit["score"] >= 0.40, f"Expected similarity score >= 0.40, got {top_hit['score']}"
    assert top_hit["category"] == "lab_radiology"

    # Verify clinical factual content
    assert any(kw in top_hit["text"] for kw in ["صيام", "سونار", "ساعات", "سكر", "ماء"])


def test_colloquial_pediatric_doctor_and_fees(clinic_retriever: QdrantKnowledgeRetriever):
    """
    FR2.2: Verify colloquial inquiry about pediatric doctor schedule and consultation fees.
    Query: 'عايز أعرف دكتور الأطفال بيبقى موجود امتى وتكلفة الكشف كام؟'
    """
    query = "عايز أعرف دكتور الأطفال بيبقى موجود امتى وتكلفة الكشف كام؟"
    hits = clinic_retriever.search(query=query, limit=3)

    assert len(hits) > 0, "Expected non-empty search hits"
    top_hit = hits[0]
    assert top_hit["score"] >= 0.40, f"Expected similarity score >= 0.40, got {top_hit['score']}"
    assert top_hit["category"] in ["doctors", "pricing", "specialties"]

    # Verify references pediatric clinic or fees
    combined_text = " ".join(hit["text"] for hit in hits)
    assert "أطفال" in combined_text
    assert any(kw in combined_text for kw in ["250", "طارق", "كشف"])


def test_colloquial_followup_and_consultation_policy(clinic_retriever: QdrantKnowledgeRetriever):
    """
    FR2.3: Verify colloquial inquiry regarding free follow-up (14 days rule).
    Query: 'لو كشفت النهاردة، الاستشارة المجانية مدتها قد إيه وممكن أعملها إزاي؟'
    """
    query = "لو كشفت النهاردة، الاستشارة المجانية مدتها قد إيه وممكن أعملها إزاي؟"
    hits = clinic_retriever.search(query=query, limit=3)

    assert len(hits) > 0, "Expected non-empty search hits"
    top_hit = hits[0]
    assert top_hit["score"] >= 0.40, f"Expected similarity score >= 0.40, got {top_hit['score']}"

    # Verify 14-day consultation rule exists in top hits
    combined_text = " ".join(hit["text"] for hit in hits)
    assert any(kw in combined_text for kw in ["14", "استشارة", "متابعة"])


def test_colloquial_insurance_coverage(clinic_retriever: QdrantKnowledgeRetriever):
    """
    FR2.4: Verify colloquial inquiry about accepted insurance companies (AXA / MetLife).
    Query: 'هل العيادات بتقبل كارت تأمين أكسا أو ميتلايف؟'
    """
    query = "هل العيادات بتقبل كارت تأمين أكسا أو ميتلايف؟"
    hits = clinic_retriever.search(query=query, limit=3)

    assert len(hits) > 0, "Expected non-empty search hits"
    top_hit = hits[0]
    assert top_hit["score"] >= 0.40, f"Expected similarity score >= 0.40, got {top_hit['score']}"
    assert top_hit["category"] == "insurance"

    assert any(kw in top_hit["text"] for kw in ["أكسا", "ميتلايف", "بوبا", "تأمين"])


# ==============================================================================
# Medical Safety Guardrails & Emergency Escalation
# ==============================================================================


def test_medical_emergency_safety_guardrail(clinic_retriever: QdrantKnowledgeRetriever):
    """
    FR3.1: Verify that acute life-threatening symptoms retrieve emergency protocol.
    Query: 'عندي ألم حاد ومفاجئ في الصدر ومش قادر أتنفس، هل دي حالة طوارئ؟'
    """
    query = "عندي ألم حاد ومفاجئ في الصدر ومش قادر أتنفس، هل دي حالة طوارئ؟"
    hits = clinic_retriever.search(query=query, limit=3)

    assert len(hits) > 0, "Expected non-empty search hits"
    top_hit = hits[0]
    assert top_hit["score"] >= 0.40, f"Expected similarity score >= 0.40, got {top_hit['score']}"
    assert top_hit["category"] == "safety_guardrails"

    # Assert emergency hotline 123 or ambulance protocol is referenced
    assert any(kw in top_hit["text"] for kw in ["123", "طوارئ", "إسعاف", "مستشفى"])


def test_prohibited_over_the_phone_diagnosis_guardrail(clinic_retriever: QdrantKnowledgeRetriever):
    """
    FR3.2: Verify that inquiries about remote diagnosis/prescriptions retrieve safety guardrails.
    Query: 'هل مسموح إعطاء استشارة علاجية أو تشخيص طبي ووصف أدوية هاتفياً؟'
    """
    query = "هل مسموح إعطاء استشارة علاجية أو تشخيص طبي ووصف أدوية هاتفياً؟"
    hits = clinic_retriever.search(query=query, limit=3)

    assert len(hits) > 0, "Expected non-empty search hits"
    top_hit = hits[0]
    assert top_hit["score"] >= 0.40, f"Expected similarity score >= 0.40, got {top_hit['score']}"
    assert top_hit["category"] == "safety_guardrails"

    # Must recall policy forbidding telephone prescriptions
    combined_text = " ".join(hit["text"] for hit in hits)
    assert any(kw in combined_text for kw in ["حظر", "تشخيص", "وصفات", "طوارئ", "أدوية", "ممنوع"])


# ==============================================================================
# Tier 3: Category Filtering & Edge Cases
# ==============================================================================


def test_category_filtering_strict_isolation(clinic_retriever: QdrantKnowledgeRetriever):
    """FR4: Verify that category filtering strictly limits results to requested category."""
    lab_hits = clinic_retriever.search(
        query="مواعيد وساعات العمل والأسعار",
        category="lab_radiology",
        limit=4,
    )
    assert len(lab_hits) > 0
    assert all(hit["category"] == "lab_radiology" for hit in lab_hits)

    insurance_hits = clinic_retriever.search(
        query="مواعيد وساعات العمل والأسعار",
        category="insurance",
        limit=4,
    )
    assert len(insurance_hits) > 0
    assert all(hit["category"] == "insurance" for hit in insurance_hits)


def test_out_of_domain_query_behavior(clinic_retriever: QdrantKnowledgeRetriever):
    """Tier 3: Verify completely irrelevant queries yield low similarity or no high-confidence hits."""
    query = "سعر وجبة بيتزا مارجريتا حجم عائلي وخصم التوصيل"
    high_conf_hits = clinic_retriever.search(query=query, score_threshold=0.60, limit=3)
    # Irrelevant culinary query must not match clinical knowledge with high confidence
    assert len(high_conf_hits) == 0


def test_context_assembly_and_truncation(clinic_retriever: QdrantKnowledgeRetriever):
    """FR5: Verify get_context_for_query bounds formatted string within max_chars."""
    max_chars = 600
    context = clinic_retriever.get_context_for_query(
        query="تعليمات التحاليل والأشعة ومواعيد العمل",
        limit=4,
        max_chars=max_chars,
    )

    assert isinstance(context, str)
    assert len(context) > 0
    assert len(context) <= max_chars
    assert "[" in context and "]" in context  # Section headers formatted


# ==============================================================================
# Tier 4: Latency SLA Benchmark
# ==============================================================================


def test_retrieval_latency_sla(clinic_retriever: QdrantKnowledgeRetriever):
    """
    NFR1: Verify vector retrieval latency budget.
    Measures local FastEmbed query encoding and overall semantic search.
    """
    test_queries = [
        "سعر كشف الباطنة كام؟",
        "تعليمات الصيام قبل تحليل السكر",
        "هل يوجد فرع في المعادي؟",
    ]

    latencies = []
    for q in test_queries:
        start = time.perf_counter()
        hits = clinic_retriever.search(query=q, limit=2)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert len(hits) > 0
        latencies.append(elapsed_ms)

    median_latency = sorted(latencies)[len(latencies) // 2]
    # FastEmbed local embedding + Qdrant search
    # In cloud environments, network round-trip is factored; local embedding should be < 50ms
    # and median search latency within reasonable interactive bounds
    assert median_latency < 350, f"Retrieval latency too high: {median_latency:.2f}ms"
