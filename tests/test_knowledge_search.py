"""
Comprehensive Test Suite for Egyptian Polyclinic Knowledge Search Tool.

Covers:
- Tier 1: Unit verification with stub retrievers (markdown cleaning, boundary trimming,
  safety flags, category validation, degraded-mode guard, async timeout).
- Tier 2: Integration tests with real FastEmbed and Qdrant collection.
- Tier 3: Edge cases (empty queries, out-of-domain queries, exceptions, aliases).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.rag.embeddings import embedding_service
from src.tools.knowledge_search import (
    ClinicKnowledgeSearchTool,
    KnowledgeSearchTool,
    async_search_clinic_knowledge,
    async_search_knowledge,
    async_search_restaurant_knowledge,
    clean_markdown_for_speech,
    clinic_knowledge_search_tool,
    is_emergency_content,
    knowledge_search_tool,
    search_clinic_knowledge,
    search_knowledge,
    search_restaurant_knowledge,
    trim_to_sentence_boundary,
)
from src.tools.schemas import ToolResult

# ==============================================================================
# Tier 1: Unit Verification (Stub Retrievers & Isolated Logic)
# ==============================================================================


class StubRetriever:
    """Configurable stub retriever for isolated unit tests."""

    def __init__(
        self,
        hits: list[dict[str, Any]] | None = None,
        raise_exc: Exception | None = None,
        delay: float = 0.0,
    ):
        self.hits = hits or []
        self.raise_exc = raise_exc
        self.delay = delay
        self.last_category: str | None = None
        self.last_query: str | None = None

    def search(
        self,
        query: str,
        limit: int = 3,
        score_threshold: float = 0.35,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        self.last_query = query
        self.last_category = category
        if self.delay > 0:
            import time

            time.sleep(self.delay)
        if self.raise_exc:
            raise self.raise_exc
        return self.hits[:limit]


class StubEmbeddings:
    """Configurable stub embeddings service."""

    def __init__(self, is_semantic: bool = True):
        self.is_semantic = is_semantic

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * 384


def test_clean_markdown_for_speech():
    """Verify markdown table pipes, headers, bold markers, and tags are stripped."""
    raw = (
        "### 4.1 أسعار الكشف\n"
        "| التخصص | السعر |\n"
        "|---|---|\n"
        "| باطنة | 250 ج |\n"
        "- كشف استشاري **ممتاز**<br>يشمل فحص السكر.\n"
        "---"
    )
    cleaned = clean_markdown_for_speech(raw)
    assert "###" not in cleaned
    assert "|" not in cleaned
    assert "---" not in cleaned
    assert "**" not in cleaned
    assert "<br>" not in cleaned
    assert "باطنة" in cleaned
    assert "250 ج" in cleaned


def test_trim_to_sentence_boundary():
    """Verify text trimming respects punctuation boundaries under max_chars."""
    short_text = "كشف الباطنة سعره 250 جنيه."
    assert trim_to_sentence_boundary(short_text, max_chars=100) == short_text

    long_text = (
        "مواعيد عيادة الأطفال تبدأ يومياً من الساعة السادسة مساءً وحتى التاسعة مساءً. "
        "يرجى الحضور قبل الموعد بنصف ساعة لاستلام رقم الكشف. يتوفر معمل تحاليل متكامل داخل المركز."
    )
    trimmed = trim_to_sentence_boundary(long_text, max_chars=100)
    assert len(trimmed) <= 100
    assert trimmed.endswith(".")


def test_is_emergency_content():
    """Verify emergency keyword recognition."""
    assert is_emergency_content("يرجى الاتصال بالإسعاف على 123 فوراً") is True
    assert is_emergency_content("ألم حاد في الصدر وضيق تنفس") is True
    assert is_emergency_content("مواعيد عيادة الأسنان") is False


def test_category_validation():
    """Verify valid categories pass through and unknown categories fallback to None."""
    stub = StubRetriever(hits=[{"text": "معلومات", "category": "pricing", "score": 0.8}])
    tool = ClinicKnowledgeSearchTool(retriever_instance=stub, embeddings=StubEmbeddings(True))

    # Valid category (case-insensitive)
    tool.execute(query="الأسعار", category="PRICING")
    assert stub.last_category == "pricing"

    # Invalid / unknown category -> searches all (None)
    tool.execute(query="الأسعار", category="unknown_dept")
    assert stub.last_category is None


def test_fallback_embeddings_guard():
    """Verify degraded-mode guard rejects search and returns safe transfer message."""
    stub = StubRetriever(hits=[{"text": "نتيجة وهمية"}])
    tool = ClinicKnowledgeSearchTool(
        retriever_instance=stub,
        embeddings=StubEmbeddings(is_semantic=False),
    )

    res = tool.execute(query="سعر الكشف كام؟")
    assert isinstance(res, ToolResult)
    assert res.success is False
    assert res.error == "embeddings_unavailable"
    assert "غير متاحة حالياً" in res.message
    assert res.data["found"] is False
    assert stub.last_query is None  # Retriever was not called!


def test_safety_flag_emergency():
    """Verify emergency hits set escalation_recommended and direct caller to 123."""
    stub = StubRetriever(
        hits=[
            {
                "id": "sec-8",
                "text": "حالات الطوارئ الحرجة وضيق التنفس الحاد تتطلب الاتصال بالإسعاف على 123 فوراً.",
                "category": "safety_guardrails",
                "section": "الطوارئ",
                "score": 0.92,
            }
        ]
    )
    tool = ClinicKnowledgeSearchTool(retriever_instance=stub, embeddings=StubEmbeddings(True))

    res = tool.execute("عندي ألم في الصدر ومش قادر أتنفس")
    assert res.success is True
    assert res.data["found"] is True
    assert res.data["escalation_recommended"] is True
    assert "123" in res.message
    assert "طوارئ" in res.message


def test_safety_flag_diagnosis():
    """Verify medical diagnosis ban sets escalation_recommended and politely declines."""
    stub = StubRetriever(
        hits=[
            {
                "id": "sec-8-1",
                "text": "يحظر حظراً تاماً تقديم استشارات طبية أو تشخيص أمراض أو وصف أدوية وجرعات علاجية هاتفياً.",
                "category": "safety_guardrails",
                "section": "حظر التشخيص",
                "score": 0.88,
            }
        ]
    )
    tool = ClinicKnowledgeSearchTool(retriever_instance=stub, embeddings=StubEmbeddings(True))

    res = tool.execute("اكتبلي مضاد حيوي لالتهاب الحلق")
    assert res.success is True
    assert res.data["escalation_recommended"] is True
    assert "ممنوع" in res.message or "حظر" in res.message or "سلامتكم" in res.message


def test_no_safety_flag_for_normal_hits():
    """Verify routine clinic inquiries do not set escalation_recommended flag."""
    stub = StubRetriever(
        hits=[
            {
                "id": "sec-4",
                "text": "سعر كشف الباطنة 250 جنيه والاستشارة مجاناً خلال 14 يوماً.",
                "category": "pricing",
                "section": "الأسعار",
                "score": 0.85,
            }
        ]
    )
    tool = ClinicKnowledgeSearchTool(retriever_instance=stub, embeddings=StubEmbeddings(True))

    res = tool.execute("سعر الكشف كام؟")
    assert res.success is True
    assert res.data["escalation_recommended"] is False
    assert "250" in res.message


def test_empty_query_direct_call():
    """Verify empty query returns empty_query error without searching."""
    stub = StubRetriever()
    tool = ClinicKnowledgeSearchTool(retriever_instance=stub, embeddings=StubEmbeddings(True))

    res = tool.execute("   ")
    assert res.success is False
    assert res.error == "empty_query"
    assert res.data["found"] is False
    assert "بوضوح" in res.message


def test_no_hits_message_is_clinic_specific():
    """Verify zero search hits returns polite clinic message without restaurant terms."""
    stub = StubRetriever(hits=[])
    tool = ClinicKnowledgeSearchTool(retriever_instance=stub, embeddings=StubEmbeddings(True))

    res = tool.execute("سؤال غير موجود في الدليل")
    assert res.success is True
    assert res.data["found"] is False
    assert "دليل العيادة" in res.message
    assert "مطعم" not in res.message
    assert "وجبات" not in res.message


def test_retriever_exception_graceful():
    """Verify unexpected Qdrant/retriever error fails safely."""
    stub = StubRetriever(raise_exc=RuntimeError("Qdrant connection timeout"))
    tool = ClinicKnowledgeSearchTool(retriever_instance=stub, embeddings=StubEmbeddings(True))

    res = tool.execute("سؤال عادي")
    assert res.success is False
    assert res.error == "search_failed"
    assert "خطأ غير متوقع" in res.message


@pytest.mark.asyncio
async def test_async_timeout():
    """Verify aexecute enforces timeout budget and yields friendly filler."""
    stub = StubRetriever(hits=[{"text": "مرحبا"}], delay=0.15)
    tool = ClinicKnowledgeSearchTool(
        retriever_instance=stub,
        embeddings=StubEmbeddings(True),
        timeout_s=0.05,
    )

    res = await tool.aexecute("سؤال")
    assert res.success is False
    assert res.error == "timeout"
    assert "ثواني" in res.message


def test_warm_up():
    """Verify warm_up executes successfully."""
    tool = ClinicKnowledgeSearchTool(embeddings=StubEmbeddings(True))
    assert tool.warm_up() is True


def test_deprecated_aliases_importable():
    """Verify legacy restaurant aliases point to clinic implementation."""
    assert KnowledgeSearchTool is ClinicKnowledgeSearchTool
    assert knowledge_search_tool is clinic_knowledge_search_tool
    assert search_knowledge is search_clinic_knowledge
    assert async_search_knowledge is async_search_clinic_knowledge
    assert search_restaurant_knowledge is search_clinic_knowledge
    assert async_search_restaurant_knowledge is async_search_clinic_knowledge


# ==============================================================================
# Tier 2: Integration Verification (Real FastEmbed & Cloud Qdrant Collection)
# ==============================================================================


@pytest.fixture(scope="module")
def real_clinic_tool():
    """Singleton clinic search tool with real embeddings and cloud Qdrant."""
    if not embedding_service.is_semantic:
        pytest.skip("FastEmbed model not loaded (missing VC++ redistributable)")
    clinic_knowledge_search_tool.warm_up()
    return clinic_knowledge_search_tool


def test_fees_question(real_clinic_tool):
    """Verify inquiry about pediatric doctor schedule and consultation fees."""
    res = real_clinic_tool.execute("الكشف عند دكتور الأطفال بكام؟")
    assert isinstance(res, ToolResult)
    assert res.success is True
    assert res.data["found"] is True
    combined = " ".join(c["content"] for c in res.data["chunks"])
    assert "أطفال" in combined or "كشف" in combined


def test_fasting_question(real_clinic_tool):
    """Verify inquiry about fasting requirements before blood tests."""
    res = real_clinic_tool.execute("لازم أكون صايم قبل تحليل السكر؟")
    assert res.success is True
    assert res.data["found"] is True
    top_chunk = res.data["chunks"][0]
    assert top_chunk["metadata"]["category"] in ["lab_radiology", "faqs", "pricing"]


def test_insurance_question(real_clinic_tool):
    """Verify inquiry about accepted health insurance companies (AXA / MetLife)."""
    res = real_clinic_tool.execute("هل بتقبلوا كارت تأمين أكسا؟")
    assert res.success is True
    assert res.data["found"] is True
    combined = " ".join(c["content"] for c in res.data["chunks"])
    assert any(kw in combined for kw in ["أكسا", "تأمين", "شركات"])


def test_emergency_question_sets_flag(real_clinic_tool):
    """Verify emergency symptom inquiry triggers escalation_recommended and directs to 123."""
    res = real_clinic_tool.execute("عندي ألم شديد ومفاجئ في صدري ومش قادر أتنفس")
    assert res.success is True
    assert res.data["found"] is True
    assert res.data["escalation_recommended"] is True
    assert any(kw in res.message for kw in ["123", "طوارئ", "إسعاف"])


def test_out_of_domain_not_found(real_clinic_tool):
    """Verify unrelated questions (e.g. food/cars) yield found=False at default threshold."""
    res = real_clinic_tool.execute("سعر وجبة بيتزا مارجريتا حجم عائلي وخصم التوصيل")
    assert res.success is True
    assert res.data["found"] is False


def test_category_filter_strict(real_clinic_tool):
    """Verify category filtering isolates results to requested category."""
    res = real_clinic_tool.execute("مواعيد العمل", category="insurance", limit=3)
    if res.data["found"]:
        for chunk in res.data["chunks"]:
            assert chunk["metadata"]["category"] == "insurance"


@pytest.mark.asyncio
async def test_sync_and_async_execution(real_clinic_tool):
    """Verify both sync and async entrypoints return matching results."""
    query = "عنوان المركز فين؟"
    res_sync = search_clinic_knowledge(query)
    res_async = await async_search_clinic_knowledge(query)

    assert res_sync.success is True
    assert res_async.success is True
    assert res_sync.data["found"] == res_async.data["found"]
