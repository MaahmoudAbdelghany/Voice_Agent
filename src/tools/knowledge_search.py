"""
Clinic Knowledge Base Search Tool for Egyptian Polyclinics.

Provides strongly-typed, low-latency semantic retrieval over clinic specialties,
doctor schedules, diagnostic lab/radiology preparation, examination fees,
health insurance networks, and medical safety guardrails via Qdrant vector database.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from src.config import settings
from src.rag.embeddings import embedding_service as default_embedding_service
from src.rag.retriever import retriever as default_retriever
from src.tools.schemas import (
    ClinicKnowledgeSearchOutput,
    KnowledgeChunk,
    ToolResult,
)

logger = logging.getLogger(__name__)

# Validated categories in clinic_kb.md
ALLOWED_CATEGORIES: set[str] = {
    "general",
    "specialties",
    "doctors",
    "pricing",
    "lab_radiology",
    "insurance",
    "booking_queue",
    "safety_guardrails",
    "faqs",
}

_HTML_TAGS = re.compile(r"<[^>]+>")
_MD_HEADER = re.compile(r"^#+\s*", re.MULTILINE)
_MARKDOWN_STYLING = re.compile(r"[*_~`]")


def clean_markdown_for_speech(text: str) -> str:
    """
    Remove Markdown tables, headers, HTML tags, and styling characters,
    producing fluent plain text appropriate for voice synthesis.
    """
    lines: list[str] = []
    for line in text.splitlines():
        trimmed = line.strip()
        # Skip table divider rows like |---|---|
        if re.match(r"^\|?[-:\s|]+\|?$", trimmed):
            continue
        if trimmed.startswith("|") and trimmed.endswith("|"):
            line = trimmed.strip("|").replace("|", " - ")
        lines.append(line)

    text = "\n".join(lines)
    text = _HTML_TAGS.sub(" ", text)
    text = _MD_HEADER.sub("", text)
    text = re.sub(r"^\s*[-*•]\s+", "", text, flags=re.MULTILINE)
    text = _MARKDOWN_STYLING.sub("", text)
    text = re.sub(r"-{2,}", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def trim_to_sentence_boundary(text: str, max_chars: int = 250) -> str:
    """
    Trim text to at most max_chars, preferably cutting at a sentence or clause boundary.
    """
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]
    boundary_idx = -1
    for punct in [".", "!", "؟", "،", ",", "؛", ";", "\n"]:
        idx = truncated.rfind(punct)
        if idx > boundary_idx and idx >= max_chars // 2:
            boundary_idx = idx

    if boundary_idx != -1:
        return truncated[: boundary_idx + 1].strip()

    space_idx = truncated.rfind(" ")
    if space_idx > max_chars // 2:
        return truncated[:space_idx].strip() + "..."
    return truncated.strip() + "..."


def is_emergency_content(text: str) -> bool:
    """Check if snippet relates to emergency protocols, ambulance, or acute symptoms."""
    lower = text.lower()
    return any(
        kw in lower for kw in ["123", "١٢٣", "طوارئ", "طوارىء", "إسعاف", "اسعاف", "صدر", "تنفس"]
    )


class ClinicKnowledgeSearchTool:
    """
    RAG-powered Knowledge Search tool for Egyptian Polyclinics.
    Performs semantic vector retrieval against Qdrant with medical guardrails.
    """

    def __init__(
        self,
        retriever_instance: Any | None = None,
        embeddings: Any | None = None,
        timeout_s: float = 0.4,
    ):
        self._retriever = retriever_instance
        self.embeddings = embeddings or default_embedding_service
        self.timeout_s = timeout_s

    @property
    def retriever(self) -> Any:
        """Resolve retriever instance lazily on access."""
        if self._retriever is None:
            if settings.hybrid_search_enabled:
                from src.rag.hybrid_retriever import hybrid_retriever
                self._retriever = hybrid_retriever
            else:
                self._retriever = default_retriever
        return self._retriever

    @retriever.setter
    def retriever(self, val: Any) -> None:
        self._retriever = val

    def warm_up(self) -> bool:
        """Pre-load the embedding model and warm up retriever."""
        try:
            self.embeddings.embed_query("warm up")
            if hasattr(self.retriever, "warm_up"):
                self.retriever.warm_up()
            # If in-memory retriever has no indexed documents, auto-index from clinic_kb.md
            if (
                hasattr(self.retriever, "bm25_index")
                and not getattr(self.retriever.bm25_index, "documents", None)
            ):
                kb_path = Path("knowledge_base/clinic_kb.md")
                if kb_path.exists():
                    from src.rag.ingestion import ingestion_pipeline
                    ingestion_pipeline.ingest_file(kb_path)
            return getattr(self.embeddings, "is_semantic", True)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Knowledge search warm_up warning: {e}")
            return False

    def execute(
        self,
        query: str,
        limit: int = 3,
        score_threshold: float = 0.35,
        category: str | None = None,
    ) -> ToolResult:
        """
        Synchronously search the clinic knowledge base.

        Args:
            query: Caller question or search phrase.
            limit: Maximum snippets to return (1-10, default 3).
            score_threshold: Minimum vector similarity score (default 0.35).
            category: Optional category filter.

        Returns:
            ToolResult containing ClinicKnowledgeSearchOutput and spoken response.
        """
        clean_query = query.strip() if isinstance(query, str) else ""

        # FR-1.2: Empty query validation
        if not clean_query:
            msg = "عذراً، لم أتمكن من سماع سؤالك بوضوح. ممكن تعيد استفسارك عن تخصصات العيادة أو الأسعار أو مواعيد العمل؟"
            return ToolResult(
                success=False,
                message=msg,
                error="empty_query",
                data=ClinicKnowledgeSearchOutput(
                    query=query or "",
                    found=False,
                    total_results=0,
                    chunks=[],
                    context_text="",
                    message=msg,
                ).model_dump()
                | {"escalation_recommended": False},
            )

        # FR-2.2: Degraded-mode guard
        is_semantic = getattr(self.embeddings, "is_semantic", True)
        if not is_semantic:
            logger.warning("Rejecting knowledge search because embeddings are in fallback mode")
            msg = "عذراً، خدمة الاستعلام عن معلومات العيادة غير متاحة حالياً، تحب أحولك لموظف الاستقبال؟"
            return ToolResult(
                success=False,
                message=msg,
                error="embeddings_unavailable",
                data=ClinicKnowledgeSearchOutput(
                    query=clean_query,
                    found=False,
                    total_results=0,
                    chunks=[],
                    context_text="",
                    message=msg,
                ).model_dump()
                | {"escalation_recommended": False},
            )

        # FR-1.3: Category filter validation
        effective_category: str | None = None
        if category:
            cat_norm = str(category).strip().lower()
            if cat_norm in ALLOWED_CATEGORIES:
                effective_category = cat_norm
            else:
                logger.warning(
                    f"Unknown category filter '{category}' requested. Searching across all categories."
                )

        logger.debug(
            f"Executing clinic knowledge search: query='{clean_query}', category={effective_category}"
        )

        try:
            hits = self.retriever.search(
                query=clean_query,
                limit=limit,
                score_threshold=score_threshold,
                category=effective_category,
            )

            # FR-3.2: No hits
            if not hits:
                logger.info(
                    f"No knowledge hits found for query: length={len(clean_query)}, category={effective_category}"
                )
                msg = "عذراً، لم أجد معلومة مؤكدة حول ذلك في دليل العيادة الحالي. تحب أساعدك في حجز موعد مع الدكتور أو أحولك لموظف الاستقبال؟"
                return ToolResult(
                    success=True,
                    message=msg,
                    data=ClinicKnowledgeSearchOutput(
                        query=clean_query,
                        found=False,
                        total_results=0,
                        chunks=[],
                        context_text="",
                        message=msg,
                    ).model_dump()
                    | {"escalation_recommended": False},
                )

            chunks: list[KnowledgeChunk] = []
            context_blocks: list[str] = []
            current_ctx_len = 0
            has_safety_hit = False

            for hit in hits:
                cat = hit.get("category", "general")
                if cat == "safety_guardrails":
                    has_safety_hit = True

                chunk = KnowledgeChunk(
                    id=str(hit.get("id", "")),
                    content=hit.get("text", ""),
                    score=float(hit.get("score", 0.0)),
                    section=hit.get("section") or cat,
                    metadata={
                        "category": cat,
                        "source": hit.get("source", ""),
                    },
                )
                chunks.append(chunk)

                # FR-3.4: context_text bounding (<= 1200 chars)
                sec_header = hit.get("section") or cat or "معلومات عامة"
                raw_text = hit.get("text", "").strip()
                block = f"[{sec_header}]\n{raw_text}"
                if current_ctx_len + len(block) <= 1200:
                    context_blocks.append(block)
                    current_ctx_len += len(block) + 2
                elif not context_blocks:
                    context_blocks.append(block[:1200])
                    current_ctx_len = 1200

            context_text = "\n\n".join(context_blocks)
            top_hit = hits[0]
            top_cat = top_hit.get("category", "general")
            top_text = top_hit.get("text", "")

            # FR-4: Safety escalation flag & messaging
            escalation_recommended = has_safety_hit

            if top_cat == "safety_guardrails" or is_emergency_content(top_text):
                if is_emergency_content(top_text):
                    voice_message = (
                        "لو حاسس بأي أعراض طوارئ زي ألم حاد في الصدر أو صعوبة في التنفس، "
                        "يرجى التوجه فوراً لأقرب قسم طوارئ أو الاتصال بالإسعاف على 123. تحب أحولك للاستقبال حالاً؟"
                    )
                else:
                    voice_message = (
                        "ممنوع تقديم استشارات طبية أو تشخيص ووصف أدوية هاتفياً حرصاً على سلامتكم. "
                        "نقدر نحجز لحضرتك موعد كشف مع الدكتور المختص، أو أحولك لموظف الاستقبال."
                    )
            else:
                cleaned_text = clean_markdown_for_speech(top_text)
                trimmed_summary = trim_to_sentence_boundary(cleaned_text, max_chars=220)
                voice_message = f"بناءً على معلومات العيادة: {trimmed_summary}"

            out = ClinicKnowledgeSearchOutput(
                query=clean_query,
                found=True,
                total_results=len(chunks),
                chunks=chunks,
                context_text=context_text,
                message=voice_message,
            )

            return ToolResult(
                success=True,
                message=voice_message,
                data=out.model_dump() | {"escalation_recommended": escalation_recommended},
            )

        except Exception:
            logger.exception("Error executing clinic knowledge search")
            msg = "حدث خطأ غير متوقع أثناء البحث في دليل العيادة، يرجى المحاولة مرة أخرى أو التحويل للاستقبال."
            return ToolResult(
                success=False,
                message=msg,
                error="search_failed",
                data=ClinicKnowledgeSearchOutput(
                    query=clean_query,
                    found=False,
                    total_results=0,
                    chunks=[],
                    context_text="",
                    message=msg,
                ).model_dump()
                | {"escalation_recommended": False},
            )

    async def aexecute(
        self,
        query: str,
        limit: int = 3,
        score_threshold: float = 0.35,
        category: str | None = None,
    ) -> ToolResult:
        """
        Asynchronously search the clinic knowledge base with latency timeout guard (400ms).
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(
                    self.execute,
                    query=query,
                    limit=limit,
                    score_threshold=score_threshold,
                    category=category,
                ),
                timeout=self.timeout_s,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Clinic knowledge search timed out after {self.timeout_s}s")
            filler_msg = "ثواني بس، بدوّر لحضرتك على المعلومة في النظام..."
            return ToolResult(
                success=False,
                message=filler_msg,
                error="timeout",
                data=None,
            )


# Global singleton instance
clinic_knowledge_search_tool = ClinicKnowledgeSearchTool()


def search_clinic_knowledge(
    query: str,
    limit: int = 3,
    score_threshold: float = 0.35,
    category: str | None = None,
) -> ToolResult:
    """
    Search Egyptian polyclinic knowledge base for specialties, fees, tests, and policies.
    """
    return clinic_knowledge_search_tool.execute(
        query=query,
        limit=limit,
        score_threshold=score_threshold,
        category=category,
    )


async def async_search_clinic_knowledge(
    query: str,
    limit: int = 3,
    score_threshold: float = 0.35,
    category: str | None = None,
) -> ToolResult:
    """
    Asynchronously search Egyptian polyclinic knowledge base.
    """
    return await clinic_knowledge_search_tool.aexecute(
        query=query,
        limit=limit,
        score_threshold=score_threshold,
        category=category,
    )


# ==============================================================================
# Backward-compatibility aliases (deprecated; replaced in Phase 5)
# ==============================================================================
KnowledgeSearchTool = ClinicKnowledgeSearchTool
knowledge_search_tool = clinic_knowledge_search_tool
search_knowledge = search_clinic_knowledge
async_search_knowledge = async_search_clinic_knowledge
search_restaurant_knowledge = search_clinic_knowledge
async_search_restaurant_knowledge = async_search_clinic_knowledge

__all__ = [
    "ALLOWED_CATEGORIES",
    "ClinicKnowledgeSearchTool",
    "KnowledgeSearchTool",
    "async_search_clinic_knowledge",
    "async_search_knowledge",
    "async_search_restaurant_knowledge",
    "clean_markdown_for_speech",
    "clinic_knowledge_search_tool",
    "is_emergency_content",
    "knowledge_search_tool",
    "search_clinic_knowledge",
    "search_knowledge",
    "search_restaurant_knowledge",
    "trim_to_sentence_boundary",
]
