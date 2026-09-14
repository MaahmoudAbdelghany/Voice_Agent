"""
Knowledge Base Search Tool for Voice Agent.

Provides semantic retrieval over restaurant menu, ingredients, allergens,
operating hours, delivery zones, and customer service policies using Qdrant vector database.
Designed for low-latency execution during real-time voice turns.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from src.config import settings
from src.rag.retriever import QdrantKnowledgeRetriever, retriever as default_retriever
from src.tools.schemas import (
    KnowledgeChunk,
    KnowledgeSearchInput,
    KnowledgeSearchOutput,
    ToolResult,
)

logger = logging.getLogger(__name__)


class KnowledgeSearchTool:
    """
    RAG-powered Knowledge Search tool for restaurant voice inquiries.
    Searches indexed menu items, policies, allergens, and FAQs.
    """

    def __init__(self, retriever_instance: Optional[QdrantKnowledgeRetriever] = None):
        """Initialize the tool with a Qdrant retriever instance."""
        self.retriever = retriever_instance or default_retriever

    def execute(
        self,
        query: str,
        limit: int = 3,
        score_threshold: float = 0.25,
        category: Optional[str] = None,
    ) -> KnowledgeSearchOutput:
        """
        Synchronously search the knowledge base.

        Args:
            query: Natural language question or search phrase.
            limit: Maximum number of knowledge snippets to return.
            score_threshold: Minimum vector similarity score (0.0 - 1.0).
            category: Optional filter (e.g., 'menu', 'allergens', 'delivery', 'policies').

        Returns:
            KnowledgeSearchOutput containing matching chunks and voice summary.
        """
        clean_query = query.strip()
        logger.info(f"Executing knowledge search for query: '{clean_query}' (limit={limit})")

        if not clean_query:
            return KnowledgeSearchOutput(
                query=query,
                found=False,
                total_results=0,
                chunks=[],
                context_text="",
                message="\u0639\u0630\u0631\u0627\u064b\u060c \u0644\u0645 \u0623\u062a\u0645\u0643\u0646 \u0645\u0646 \u0633\u0645\u0627\u0639 \u0633\u0624\u0627\u0644\u0643 \u0628\u0648\u0636\u0648\u062d. \u0647\u0644 \u064a\u0645\u0643\u0646\u0643 \u0625\u0639\u0627\u062f\u0629 \u0627\u0644\u0633\u0624\u0627\u0644 \u0639\u0646 \u0627\u0644\u0642\u0627\u0626\u0645\u0629 \u0623\u0648 \u0627\u0644\u062e\u062f\u0645\u0627\u062a\u061f",
            )

        # Relax threshold when filtering by a specific category since category match ensures topical domain
        effective_threshold = min(score_threshold, 0.15) if category else score_threshold

        try:
            hits = self.retriever.search(
                query=clean_query,
                limit=limit,
                score_threshold=effective_threshold,
                category=category,
            )

            if not hits:
                logger.info(f"No knowledge hits found for query: '{clean_query}'")
                return KnowledgeSearchOutput(
                    query=clean_query,
                    found=False,
                    total_results=0,
                    chunks=[],
                    context_text="",
                    message=(
                        "\u0639\u0630\u0631\u0627\u064b\u060c \u0644\u0645 \u0623\u062c\u062f \u0645\u0639\u0644\u0648\u0645\u0627\u062a \u0645\u0624\u0643\u062f\u0629 \u062d\u0648\u0644 \u0630\u0644\u0643 \u0641\u064a \u0642\u0627\u0626\u0645\u0629 \u0627\u0644\u0637\u0639\u0627\u0645 \u0623\u0648 \u0627\u0644\u0633\u064a\u0627\u0633\u0627\u062a \u0627\u0644\u062d\u0627\u0644\u064a\u0629. "
                        "\u064a\u0645\u0643\u0646\u0646\u064a \u0645\u0633\u0627\u0639\u062f\u062a\u0643 \u0641\u064a \u0627\u0633\u062a\u0639\u0631\u0627\u0636 \u0627\u0644\u0623\u0637\u0628\u0627\u0642 \u0627\u0644\u0623\u0643\u062b\u0631 \u0637\u0644\u0628\u0627\u064b \u0623\u0648 \u0633\u0627\u0639\u0627\u062a \u0627\u0644\u0639\u0645\u0644 \u0648\u0627\u0644\u062a\u0648\u0635\u064a\u0644."
                    ),
                )

            chunks: List[KnowledgeChunk] = []
            context_blocks: List[str] = []

            for hit in hits:
                chunk = KnowledgeChunk(
                    id=str(hit.get("id", "")),
                    content=hit.get("text", ""),
                    score=float(hit.get("score", 0.0)),
                    section=hit.get("section") or hit.get("category"),
                    metadata={
                        "category": hit.get("category", "general"),
                        "source": hit.get("source", ""),
                    },
                )
                chunks.append(chunk)

                section_header = hit.get("section") or hit.get("category") or "\u0645\u0639\u0644\u0648\u0645\u0627\u062a \u0639\u0627\u0645\u0629"
                context_blocks.append(f"[{section_header}]\n{hit.get('text', '')}")

            context_text = "\n\n".join(context_blocks)

            # Generate natural voice-ready summary
            top_hit = hits[0]
            top_text = top_hit.get("text", "").strip()

            voice_message = (
                f"\u0628\u0646\u0627\u0621\u064b \u0639\u0644\u0649 \u0645\u0639\u0644\u0648\u0645\u0627\u062a \u0627\u0644\u0645\u0637\u0639\u0645: {top_text}"
                if len(top_text) <= 250
                else f"\u0628\u0646\u0627\u0621\u064b \u0639\u0644\u0649 \u0645\u0639\u0644\u0648\u0645\u0627\u062a \u0627\u0644\u0645\u0637\u0639\u0645: {top_text[:240]}..."
            )

            return KnowledgeSearchOutput(
                query=clean_query,
                found=True,
                total_results=len(chunks),
                chunks=chunks,
                context_text=context_text,
                message=voice_message,
            )

        except Exception as e:
            logger.error(f"Error executing knowledge search for '{clean_query}': {e}", exc_info=True)
            return KnowledgeSearchOutput(
                query=clean_query,
                found=False,
                total_results=0,
                chunks=[],
                context_text="",
                message="\u062d\u062f\u062b \u062e\u0637\u0623 \u0645\u0624\u0642\u062a \u0623\u062b\u0646\u0627\u0621 \u0627\u0644\u0628\u062d\u062b \u0641\u064a \u0642\u0627\u0639\u062f\u0629 \u0627\u0644\u0645\u0639\u0644\u0648\u0645\u0627\u062a\u060c \u064a\u0631\u062c\u0649 \u0627\u0644\u0645\u062d\u0627\u0648\u0644\u0629 \u0645\u0631\u0629 \u0623\u062e\u0631\u0649.",
            )

    async def aexecute(
        self,
        query: str,
        limit: int = 3,
        score_threshold: float = 0.25,
        category: Optional[str] = None,
    ) -> KnowledgeSearchOutput:
        """
        Asynchronously search the knowledge base (non-blocking for LiveKit voice turns).
        """
        return await asyncio.to_thread(
            self.execute,
            query=query,
            limit=limit,
            score_threshold=score_threshold,
            category=category,
        )


# Singleton tool instance
knowledge_search_tool = KnowledgeSearchTool()


def search_knowledge(
    query: str,
    limit: int = 3,
    score_threshold: float = 0.25,
    category: Optional[str] = None,
) -> KnowledgeSearchOutput:
    """
    Convenience function to query the restaurant knowledge base.

    Args:
        query: User question about menu, allergens, hours, prices, or delivery.
        limit: Max knowledge chunks to return (default: 3).
        score_threshold: Minimum cosine similarity score.
        category: Optional category filter.

    Returns:
        KnowledgeSearchOutput with matching chunks and spoken message.
    """
    return knowledge_search_tool.execute(
        query=query,
        limit=limit,
        score_threshold=score_threshold,
        category=category,
    )


async def async_search_knowledge(
    query: str,
    limit: int = 3,
    score_threshold: float = 0.25,
    category: Optional[str] = None,
) -> KnowledgeSearchOutput:
    """
    Asynchronous convenience function to query the restaurant knowledge base.
    """
    return await knowledge_search_tool.aexecute(
        query=query,
        limit=limit,
        score_threshold=score_threshold,
        category=category,
    )


# Descriptive aliases for function calling registry
search_restaurant_knowledge = search_knowledge
async_search_restaurant_knowledge = async_search_knowledge
