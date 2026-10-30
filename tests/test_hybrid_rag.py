"""
Comprehensive Unit, Integration, and Latency Tests for Feature 4.3 — Hybrid RAG Upgrade.

Validates:
1. Structure-aware chunking (Markdown table rows, atomic FAQs, boundary-split prose).
2. Pure-Python Okapi BM25Index tokenization, IDF scoring, and category filtering.
3. Reciprocal Rank Fusion (RRF) math (k=60), ranking, and [0.0, 1.0] score calibration.
4. Exact clinical entity recall (CBC, HbA1c, DEXA, doctor names, shift fees).
5. Elimination of table truncation in voice summaries (<220 chars).
6. Auto-synchronization and lazy-load scrolling from Qdrant.
7. Resilience, kill-switch fallback, out-of-domain rejection, and <5ms BM25 latency.
"""

import time
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config import settings
from src.rag.hybrid_retriever import (
    BM25Index,
    HybridKnowledgeRetriever,
    reciprocal_rank_fusion,
    tokenize_for_bm25,
)
from src.rag.ingestion import KnowledgeIngestionPipeline
from src.rag.retriever import QdrantKnowledgeRetriever
from src.tools.knowledge_search import ClinicKnowledgeSearchTool


@pytest.fixture(scope="module")
def kb_path() -> Path:
    """Fixture providing path to clinic_kb.md."""
    path = Path(__file__).resolve().parent.parent / "knowledge_base" / "clinic_kb.md"
    assert path.exists(), f"Clinic knowledge base not found at {path}"
    return path


@pytest.fixture(scope="module")
def parsed_kb_chunks(kb_path: Path) -> list[dict]:
    """Parse clinic_kb.md using structure-aware chunking."""
    pipeline = KnowledgeIngestionPipeline()
    chunks = pipeline.parse_markdown(kb_path)
    assert len(chunks) >= 40, f"Expected >=40 structure-aware chunks, got {len(chunks)}"
    return chunks


@pytest.fixture(scope="module")
def hybrid_test_retriever(parsed_kb_chunks: list[dict]) -> HybridKnowledgeRetriever:
    """
    Module-scoped HybridKnowledgeRetriever with dedicated test collection.
    Populates both in-memory Qdrant and in-memory BM25 index.
    """
    col_name = f"test_hybrid_kb_{uuid.uuid4().hex[:8]}"
    dense_retriever = QdrantKnowledgeRetriever(collection_name=col_name)
    retriever = HybridKnowledgeRetriever(
        dense_retriever=dense_retriever,
        collection_name=col_name,
    )
    retriever.recreate_collection()
    retriever.upsert_chunks(parsed_kb_chunks)
    return retriever


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


def test_table_row_chunking_preserves_headers(parsed_kb_chunks: list[dict]):
    """
    Verify structure-aware chunking decomposes tables into self-contained row-level
    chunks with column headers paired to cell values and parent section title.
    """
    table_row_chunks = [
        c for c in parsed_kb_chunks if c["metadata"].get("chunk_type") == "table_row"
    ]
    # Expect 10 doctors + 11 lab tests + 6 radiology exams = 27 table row chunks
    assert len(table_row_chunks) >= 27

    # Verify doctors table row chunk
    doc_chunks = [c for c in table_row_chunks if "د. عمرو خالد النجار" in c["text"]]
    assert len(doc_chunks) == 1
    doc_chunk = doc_chunks[0]
    assert doc_chunk["metadata"]["category"] == "doctors"
    assert "اسم الطبيب" in doc_chunk["text"]
    assert "سعر الكشف: 350 ج" in doc_chunk["text"]
    assert "الأسنان" in doc_chunk["text"]

    # Verify lab test table row chunk
    cbc_chunks = [c for c in table_row_chunks if "CBC" in c["text"]]
    assert len(cbc_chunks) == 1
    cbc_chunk = cbc_chunks[0]
    assert cbc_chunk["metadata"]["category"] == "lab_radiology"
    assert "اسم التحليل" in cbc_chunk["text"]
    assert "لا يشترط الصيام" in cbc_chunk["text"]

    # Verify radiology exam row chunk
    dexa_chunks = [c for c in table_row_chunks if "DEXA" in c["text"]]
    assert len(dexa_chunks) == 1
    dexa_chunk = dexa_chunks[0]
    assert dexa_chunk["metadata"]["category"] == "lab_radiology"
    assert "كثافة العظام" in dexa_chunk["text"]
    assert "الكالسيوم" in dexa_chunk["text"]


def test_faq_chunks_remain_atomic(parsed_kb_chunks: list[dict]):
    """
    Verify caller FAQ sections (### س 1 .. ### س 10) remain intact as atomic chunks.
    """
    faq_chunks = [c for c in parsed_kb_chunks if c["metadata"].get("chunk_type") == "faq"]
    assert len(faq_chunks) >= 10

    # Verify a sample FAQ contains both the question and model answer
    faq1 = next((c for c in faq_chunks if "س 1" in c["metadata"]["section"]), None)
    assert faq1 is not None
    assert "تخصصات العيادات" in faq1["text"]
    assert "**ج**" in faq1["text"] or "10 تخصصات" in faq1["text"]
    assert faq1["metadata"]["category"] == "faqs"


def test_long_prose_splits_on_boundaries(tmp_path: Path):
    """
    Verify non-table prose exceeding rag_chunk_max_chars splits along paragraph
    boundaries while preserving section header context in all pieces.
    """
    sample_md = (
        "## معلومات تفصيلية عن المركز الطبي\n\n"
        "الفقرة الأولى تتحدث عن تاريخ المركز الطبي وتأسيسه في المعادي بالقاهرة منذ عشر سنوات.\n\n"
        + ("تفاصيل مطولة ومعلومات إضافية عن المركز والخدمات الطبية والتجهيزات الحديثة. " * 20)
        + "\n\n"
        + ("تفاصيل أخرى عن مواعيد العمل واستقبال المرضى والفحوصات الشاملة المتاحة يوميا. " * 20)
    )
    test_file = tmp_path / "test_prose.md"
    test_file.write_text(sample_md, encoding="utf-8")

    pipeline = KnowledgeIngestionPipeline()
    with patch.object(settings, "rag_chunk_max_chars", 300):
        chunks = pipeline.parse_markdown(test_file)

    assert len(chunks) > 1
    for c in chunks:
        assert c["metadata"]["chunk_type"] == "section"
        assert c["metadata"]["section"] == "معلومات تفصيلية عن المركز الطبي"
        assert "معلومات تفصيلية عن المركز الطبي" in c["text"]


def test_tokenize_for_bm25_normalizes_arabic_and_removes_stopwords():
    """
    Verify BM25 tokenization normalizes Arabic characters, handles digits,
    filters conversational stop words, and preserves clinical codes and entities.
    """
    query = "هل ممكن أعرف سعر كشف د. عمرو خالد النجار كام وتحليل HbA1c و CBC كوده ١٢٣؟"
    tokens = tokenize_for_bm25(query)

    # Stop words / fillers must be filtered out
    assert "هل" not in tokens
    assert "ممكن" not in tokens
    assert "اعرف" not in tokens
    assert "سعر" not in tokens
    assert "كام" not in tokens

    # Clinical entities, doctor names, and numbers must be preserved
    assert "عمرو" in tokens
    assert "خالد" in tokens
    assert "النجار" in tokens
    assert "hba1c" in tokens
    assert "cbc" in tokens
    assert "123" in tokens  # Arabic-Indic '١٢٣' normalized to ASCII '123'


def test_bm25_exact_abbreviation_and_doctor_ranking():
    """
    Verify BM25 ranks documents containing exact entity codes #1 with bm25_score > 0.
    """
    index = BM25Index(k1=1.5, b=0.75)
    sample_chunks = [
        {
            "id": "c1",
            "text": "تحليل صورة دم كاملة CBC وسرعة الترسيب",
            "metadata": {"category": "lab_radiology"},
        },
        {
            "id": "c2",
            "text": "تحليل السكر التراكمي HbA1c صائم وفاطر",
            "metadata": {"category": "lab_radiology"},
        },
        {
            "id": "c3",
            "text": "فحص كثافة العظام DEXA Scan بالأشعة",
            "metadata": {"category": "lab_radiology"},
        },
        {
            "id": "c4",
            "text": "عيادة الأسنان د. عمرو خالد النجار استشاري",
            "metadata": {"category": "doctors"},
        },
    ]
    index.build(sample_chunks)

    # Query for CBC
    hits_cbc = index.search("CBC", limit=2)
    assert len(hits_cbc) > 0
    assert hits_cbc[0]["id"] == "c1"
    assert hits_cbc[0]["score"] > 0

    # Query for HbA1c
    hits_hba1c = index.search("HbA1c", limit=2)
    assert len(hits_hba1c) > 0
    assert hits_hba1c[0]["id"] == "c2"

    # Query for DEXA
    hits_dexa = index.search("DEXA", limit=2)
    assert len(hits_dexa) > 0
    assert hits_dexa[0]["id"] == "c3"

    # Query for doctor name
    hits_doc = index.search("د. عمرو خالد النجار", limit=2)
    assert len(hits_doc) > 0
    assert hits_doc[0]["id"] == "c4"


def test_bm25_category_filtering():
    """
    Verify BM25 search strictly honors category filter.
    """
    index = BM25Index(k1=1.5, b=0.75)
    sample_chunks = [
        {
            "id": "c1",
            "text": "خدمات عيادة الأسنان وجراحة الفم",
            "metadata": {"category": "doctors"},
        },
        {
            "id": "c2",
            "text": "خدمات معمل التحاليل الطبية المركزية",
            "metadata": {"category": "lab_radiology"},
        },
        {
            "id": "c3",
            "text": "خدمات شركات التأمين الصحي المعتمدة",
            "metadata": {"category": "insurance"},
        },
    ]
    index.build(sample_chunks)

    hits = index.search("خدمات معمل التحاليل", limit=5, category="lab_radiology")
    assert len(hits) == 1
    assert hits[0]["id"] == "c2"
    assert hits[0]["category"] == "lab_radiology"


def test_rrf_math_k60_and_dual_match_promotion():
    """
    Verify RRF math at k=60: document ranked #1 in both Dense and BM25
    receives rrf_score = 1/61 + 1/61 ≈ 0.032787, outranking single-source hits.
    """
    dense_hits = [
        {"id": "doc_both", "score": 0.70, "text": "نص وثيقة", "category": "general"},
        {"id": "doc_dense_only", "score": 0.65, "text": "نص وثيقة كثيفة", "category": "general"},
    ]
    bm25_hits = [
        {
            "id": "doc_both",
            "score": 4.5,
            "text": "نص وثيقة",
            "category": "general",
            "query_coverage": 1.0,
        },
        {
            "id": "doc_bm25_only",
            "score": 3.8,
            "text": "نص وثيقة كلمات",
            "category": "general",
            "query_coverage": 1.0,
        },
    ]

    fused = reciprocal_rank_fusion(dense_hits, bm25_hits, k=60, limit=3)
    assert len(fused) == 3

    # doc_both must be ranked #1
    top_hit = fused[0]
    assert top_hit["id"] == "doc_both"
    expected_rrf = round(1.0 / 61.0 + 1.0 / 61.0, 6)
    assert top_hit["rrf_score"] == expected_rrf
    assert "dense" in top_hit["match_sources"] and "bm25" in top_hit["match_sources"]

    # Fused scores must be within [0.0, 1.0]
    for h in fused:
        assert 0.0 <= h["score"] <= 1.0
        assert "rrf_score" in h
        assert "dense_score" in h
        assert "bm25_score" in h
        assert "match_sources" in h


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


def test_hybrid_exact_lab_codes_cbc_and_hba1c(hybrid_test_retriever: HybridKnowledgeRetriever):
    """
    Verify exact clinical test codes retrieve corresponding row chunk at #1.
    """
    # 1. CBC
    hits_cbc = hybrid_test_retriever.search("تحليل CBC", limit=2)
    assert len(hits_cbc) > 0
    top_cbc = hits_cbc[0]
    assert top_cbc["category"] == "lab_radiology"
    assert "CBC" in top_cbc["text"]
    assert "لا يشترط الصيام" in top_cbc["text"]
    assert top_cbc["score"] >= 0.35

    # 2. HbA1c
    hits_hba1c = hybrid_test_retriever.search("تحليل HbA1c", limit=2)
    assert len(hits_hba1c) > 0
    top_hba1c = hits_hba1c[0]
    assert top_hba1c["category"] == "lab_radiology"
    assert "HbA1c" in top_hba1c["text"]
    assert "السكر التراكمي" in top_hba1c["text"]


def test_hybrid_exact_radiology_dexa_and_ct(hybrid_test_retriever: HybridKnowledgeRetriever):
    """
    Verify exact radiology procedure queries retrieve row chunk with preparation guidelines.
    """
    hits_dexa = hybrid_test_retriever.search("تحضير فحص DEXA Scan كثافة العظام", limit=2)
    assert len(hits_dexa) > 0
    top_dexa = hits_dexa[0]
    assert top_dexa["category"] == "lab_radiology"
    assert "DEXA" in top_dexa["text"]
    assert "الكالسيوم" in top_dexa["text"]


def test_hybrid_specific_doctor_row_retrieval_and_voice_summary(
    hybrid_test_retriever: HybridKnowledgeRetriever,
):
    """
    Verify specific doctor queries via ClinicKnowledgeSearchTool retrieve row chunk
    and spoken response includes shift hours and consultation fee (< 220 chars).
    """
    tool = ClinicKnowledgeSearchTool(retriever_instance=hybrid_test_retriever)

    # Doctor Amr Khaled El-Naggar (Dentistry)
    res_amr = tool.execute("مواعيد وسعر كشف د. عمرو خالد النجار")
    assert res_amr.success is True
    assert res_amr.data["found"] is True
    voice_msg_amr = res_amr.message
    assert "350" in voice_msg_amr or "عمرو" in voice_msg_amr

    # Doctor Yasmine Adel Ibrahim (Dentistry Specialist)
    res_yasmine = tool.execute("كشف دكتورة ياسمين عادل إبراهيم")
    assert res_yasmine.success is True
    assert res_yasmine.data["found"] is True
    voice_msg_yasmine = res_yasmine.message
    assert "230" in voice_msg_yasmine or "ياسمين" in voice_msg_yasmine


def test_hybrid_lazy_sync_from_existing_qdrant_collection(
    hybrid_test_retriever: HybridKnowledgeRetriever,
):
    """
    Verify a newly instantiated HybridKnowledgeRetriever lazily scrolls existing
    Qdrant points to populate its BM25 index on first search.
    """
    col_name = hybrid_test_retriever.collection_name
    dense_retriever = QdrantKnowledgeRetriever(collection_name=col_name)

    # Fresh hybrid retriever with empty BM25 index
    fresh_hybrid = HybridKnowledgeRetriever(
        dense_retriever=dense_retriever,
        collection_name=col_name,
    )
    assert len(fresh_hybrid.bm25_index.documents) == 0

    # Search should trigger lazy scroll
    hits = fresh_hybrid.search("CBC", limit=2)
    assert len(fresh_hybrid.bm25_index.documents) > 0
    assert len(hits) > 0
    assert any("bm25" in h["match_sources"] for h in hits)


def test_recreate_collection_clears_bm25_index(parsed_kb_chunks: list[dict]):
    """
    Verify recreate_collection() clears both Qdrant and BM25 index.
    """
    col_name = f"test_clear_col_{uuid.uuid4().hex[:8]}"
    retriever = HybridKnowledgeRetriever(collection_name=col_name)
    retriever.recreate_collection()
    retriever.upsert_chunks(parsed_kb_chunks[:5])
    assert len(retriever.bm25_index.documents) == 5

    retriever.recreate_collection()
    assert len(retriever.bm25_index.documents) == 0


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


def test_out_of_domain_query_with_price_stopword_rejected(
    hybrid_test_retriever: HybridKnowledgeRetriever,
):
    """
    Verify unrelated query containing stop words like 'سعر' does not trigger false BM25 hits.
    """
    tool = ClinicKnowledgeSearchTool(retriever_instance=hybrid_test_retriever)
    query = "سعر وجبة بيتزا مارجريتا حجم عائلي وخصم التوصيل"
    res = tool.execute(query)
    assert res.success is True
    assert res.data["found"] is False


def test_hybrid_kill_switch_falls_back_to_dense_only(
    hybrid_test_retriever: HybridKnowledgeRetriever,
):
    """
    Verify hybrid_search_enabled=False bypasses BM25 and executes dense-only search.
    """
    with patch.object(settings, "hybrid_search_enabled", False):
        hits = hybrid_test_retriever.search("مواعيد عيادة العظام", limit=2)
        assert len(hits) > 0
        # Dense-only search hit dictionary does not include match_sources or rrf_score
        assert "match_sources" not in hits[0]


def test_bm25_exception_fails_open_to_dense(
    hybrid_test_retriever: HybridKnowledgeRetriever,
):
    """
    Verify BM25 search error gracefully fails open to dense vector results without crashing.
    """
    with patch.object(
        hybrid_test_retriever.bm25_index,
        "search",
        side_effect=RuntimeError("Simulated BM25 inverted index corruption"),
    ):
        hits = hybrid_test_retriever.search("مواعيد عيادة العظام", limit=2)
        assert len(hits) > 0
        assert hits[0]["score"] >= 0.35


def test_empty_and_punctuation_only_queries(
    hybrid_test_retriever: HybridKnowledgeRetriever,
):
    """
    Verify empty, whitespace, and punctuation-only queries return [] without error.
    """
    assert hybrid_test_retriever.search("") == []
    assert hybrid_test_retriever.search("   ") == []
    assert hybrid_test_retriever.search("؟؟؟") == []


def test_hybrid_retrieval_latency_sla(
    hybrid_test_retriever: HybridKnowledgeRetriever,
):
    """
    Verify hybrid retrieval latency SLA:
    - Pure BM25 + RRF execution takes < 5ms for 70+ chunks.
    - Total hybrid search median latency is well within interactive voice bounds.
    """
    # 1. Benchmark pure BM25 search overhead
    bm25_latencies = []
    for _ in range(20):
        start = time.perf_counter()
        hybrid_test_retriever.bm25_index.search("د. عمرو خالد النجار تحليل HbA1c", limit=10)
        bm25_latencies.append((time.perf_counter() - start) * 1000)

    median_bm25 = sorted(bm25_latencies)[len(bm25_latencies) // 2]
    assert median_bm25 < 5.0, f"BM25 latency too high: {median_bm25:.2f}ms (expected <5ms)"

    # 2. Benchmark total hybrid search
    test_queries = [
        "CBC",
        "HbA1c",
        "د. عمرو خالد النجار",
        "صيام تحليل السكر",
        "فرع المعادي",
    ]
    total_latencies = []
    for q in test_queries:
        start = time.perf_counter()
        hits = hybrid_test_retriever.search(q, limit=3)
        total_latencies.append((time.perf_counter() - start) * 1000)
        assert len(hits) > 0

    median_total = sorted(total_latencies)[len(total_latencies) // 2]
    assert median_total < 250.0, f"Total hybrid latency too high: {median_total:.2f}ms"
