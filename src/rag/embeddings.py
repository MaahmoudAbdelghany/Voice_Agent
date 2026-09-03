"""
Embeddings Service using FastEmbed.

Provides fast, lightweight dense vector generation using ONNX-optimized
models (default: BAAI/bge-small-en-v1.5) with local caching and zero API fees.
"""

from typing import List, Optional
import logging
from src.config import settings

logger = logging.getLogger(__name__)

# Default dimension for BAAI/bge-small-en-v1.5
DEFAULT_EMBEDDING_DIM = 384


class EmbeddingService:
    """
    Singleton-friendly wrapper around FastEmbed TextEmbedding.
    Handles batch document embedding, single query embedding, and graceful fallbacks.
    """

    def __init__(self, model_name: Optional[str] = None):
        self.model_name = model_name or settings.embedding_model
        self._model = None
        self._dim = DEFAULT_EMBEDDING_DIM

    def _get_model(self):
        """Lazy load the TextEmbedding model to prevent startup latency."""
        if self._model is None:
            try:
                from fastembed import TextEmbedding
                logger.info(f"Loading FastEmbed model: {self.model_name}")
                self._model = TextEmbedding(model_name=self.model_name)
            except Exception as e:
                logger.warning(f"Could not load FastEmbed model '{self.model_name}': {e}. Using deterministic fallback.")
                self._model = False
        return self._model

    @property
    def dimension(self) -> int:
        """Returns the embedding vector dimension."""
        return self._dim

    def embed_documents(self, documents: List[str]) -> List[List[float]]:
        """
        Embed a list of text documents into dense vector representations.
        
        Args:
            documents: List of text chunks to embed.
            
        Returns:
            List of vector embeddings (list of floats).
        """
        if not documents:
            return []

        model = self._get_model()
        if model:
            try:
                # fastembed returns an iterable of numpy arrays
                embeddings = list(model.embed(documents))
                return [emb.tolist() for emb in embeddings]
            except Exception as e:
                logger.error(f"Error generating fastembed embeddings: {e}")

        # Fallback pseudo-embeddings (deterministic hash-based) if model unavailable
        return [self._fallback_embed(doc) for doc in documents]

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a single search query string.
        
        Args:
            query: User search query.
            
        Returns:
            Dense vector embedding as a list of floats.
        """
        results = self.embed_documents([query])
        return results[0] if results else [0.0] * self._dim

    def _fallback_embed(self, text: str) -> List[float]:
        """Deterministic fallback embedding for testing or offline environments."""
        import hashlib
        import math
        
        hasher = hashlib.sha256(text.encode("utf-8"))
        seed = int(hasher.hexdigest()[:8], 16)
        
        # Generate pseudo-random normalized 384-dimensional vector
        raw_vec = [math.sin(seed + i) for i in range(self._dim)]
        norm = math.sqrt(sum(x * x for x in raw_vec)) or 1.0
        return [x / norm for x in raw_vec]


# Singleton instance
embedding_service = EmbeddingService()
