"""
Qdrant Vector Database Retriever for Knowledge Base RAG.

Supports both Qdrant Cloud and local in-memory/disk vector storage.
Provides hybrid semantic retrieval, category filtering, and formatted context generation for voice LLM turns.
"""

from typing import List, Dict, Any, Optional
import logging
import uuid
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels
from src.config import settings
from src.rag.embeddings import embedding_service

logger = logging.getLogger(__name__)


class QdrantKnowledgeRetriever:
    """
    Manages vector indexing and retrieval from Qdrant vector database.
    Seamlessly operates with Qdrant Cloud or local in-memory client.
    """

    def __init__(self, collection_name: Optional[str] = None):
        self.collection_name = collection_name or settings.qdrant_collection
        self.client = self._init_client()
        self.embeddings = embedding_service
        self._ensure_collection()

    def _init_client(self) -> QdrantClient:
        """Initializes Qdrant client based on configuration."""
        if settings.is_qdrant_cloud():
            logger.info(f"Connecting to Qdrant Cloud at {settings.qdrant_url}")
            return QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
            )
        else:
            logger.info("Using local in-memory Qdrant instance for vector search")
            return QdrantClient(":memory:")

    def _ensure_collection(self) -> None:
        """Ensure collection exists in Qdrant with appropriate vector configuration."""
        try:
            collections = self.client.get_collections().collections
            exists = any(col.name == self.collection_name for col in collections)
            if not exists:
                logger.info(f"Creating collection '{self.collection_name}' in Qdrant...")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self.embeddings.dimension,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
        except Exception as e:
            logger.error(f"Error checking/creating collection '{self.collection_name}': {e}")

    def upsert_chunks(self, chunks: List[Dict[str, Any]]) -> int:
        """
        Embed and upsert knowledge chunks into Qdrant collection.
        
        Args:
            chunks: List of dicts, each containing:
                - text: The chunk content
                - metadata: Dict of metadata (title, category, source, etc.)
                - id (optional): Unique string identifier
                
        Returns:
            Number of points successfully upserted.
        """
        if not chunks:
            return 0

        texts = [chunk["text"] for chunk in chunks]
        vectors = self.embeddings.embed_documents(texts)

        points = []
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
            raw_id = chunk.get("id")
            if raw_id is not None:
                if isinstance(raw_id, int):
                    point_id = raw_id
                else:
                    try:
                        uuid.UUID(str(raw_id))
                        point_id = str(raw_id)
                    except ValueError:
                        point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(raw_id)))
            else:
                point_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{chunk['text'][:40]}_{idx}"))

            payload = {
                "text": chunk["text"],
                **chunk.get("metadata", {}),
            }
            points.append(
                qmodels.PointStruct(
                    id=point_id,
                    vector=vector,
                    payload=payload,
                )
            )

        self.client.upsert(
            collection_name=self.collection_name,
            points=points,
        )
        logger.info(f"Successfully upserted {len(points)} knowledge points into '{self.collection_name}'.")
        return len(points)

    def search(
        self,
        query: str,
        limit: int = 4,
        score_threshold: Optional[float] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute semantic vector similarity search against the restaurant knowledge base.
        
        Args:
            query: User utterance or question.
            limit: Maximum top-k chunks to return.
            score_threshold: Minimum cosine similarity score.
            category: Optional payload filter by section/category.
            
        Returns:
            List of matching records with text, score, and metadata.
        """
        query_vector = self.embeddings.embed_query(query)
        
        # Build query filter if category provided
        query_filter = None
        if category:
            query_filter = qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="category",
                        match=qmodels.MatchValue(value=category),
                    )
                ]
            )

        # Support both new query_points (qdrant-client >=1.10) and search API
        try:
            if hasattr(self.client, "query_points"):
                response = self.client.query_points(
                    collection_name=self.collection_name,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                )
                hits = response.points
            else:
                hits = self.client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=limit,
                    score_threshold=score_threshold,
                )
        except Exception as e:
            logger.error(f"Error performing Qdrant search: {e}")
            return []

        results = []
        for hit in hits:
            payload = hit.payload or {}
            results.append({
                "id": str(hit.id),
                "score": round(float(hit.score), 4),
                "text": payload.get("text", ""),
                "category": payload.get("category", "general"),
                "section": payload.get("section", ""),
                "source": payload.get("source", ""),
            })

        return results

    def get_context_for_query(self, query: str, limit: int = 3, max_chars: int = 1200) -> str:
        """
        Retrieve and format top matching knowledge snippets into a clean context block for LLM prompts.
        
        Args:
            query: User query.
            limit: Maximum snippets to assemble.
            max_chars: Character limit to avoid prompt bloat during voice turns.
            
        Returns:
            Formatted multi-line context string.
        """
        hits = self.search(query=query, limit=limit)
        if not hits:
            return ""

        context_blocks = []
        current_len = 0
        for i, hit in enumerate(hits, start=1):
            snippet = f"[{hit.get('section', 'General')}]\n{hit['text'].strip()}"
            if current_len + len(snippet) > max_chars:
                break
            context_blocks.append(snippet)
            current_len += len(snippet)

        return "\n\n".join(context_blocks)


# Singleton instance
retriever = QdrantKnowledgeRetriever()
