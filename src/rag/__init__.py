"""RAG and Vector Search Package for Voice Agent."""

from typing import Any

from src.rag.embeddings import EmbeddingService, embedding_service
from src.rag.hybrid_retriever import (
    BM25Index,
    HybridKnowledgeRetriever,
    get_hybrid_retriever,
    reciprocal_rank_fusion,
    tokenize_for_bm25,
)
from src.rag.retriever import QdrantKnowledgeRetriever, get_retriever
from src.rag.sanitizer import (
    DocumentSanitizer,
    SanitizationFinding,
    SanitizationReport,
    document_sanitizer,
)

__all__ = [
    "BM25Index",
    "DocumentSanitizer",
    "EmbeddingService",
    "HybridKnowledgeRetriever",
    "QdrantKnowledgeRetriever",
    "SanitizationFinding",
    "SanitizationReport",
    "document_sanitizer",
    "embedding_service",
    "hybrid_retriever",
    "reciprocal_rank_fusion",
    "retriever",
    "tokenize_for_bm25",
]


def __getattr__(name: str) -> Any:
    if name == "retriever":
        return get_retriever()
    if name == "hybrid_retriever":
        return get_hybrid_retriever()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals().keys()) | set(__all__))

