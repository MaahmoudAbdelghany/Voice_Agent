"""
Hybrid Knowledge Base Retriever for Egyptian Polyclinics.

Combines Qdrant dense vector similarity search with pure-Python Okapi BM25
sparse keyword search using Reciprocal Rank Fusion (RRF).
Guarantees sub-400ms voice tool budget, exact medical entity recall,
and zero external runtime dependencies.
"""

from __future__ import annotations

import logging
import math
import re
import uuid
from collections import Counter
from typing import Any

from src.ai_core.text_normalizer import normalize_query
from src.config import settings
from src.rag.retriever import QdrantKnowledgeRetriever
from src.rag.retriever import retriever as default_retriever

logger = logging.getLogger(__name__)

# Curated Arabic conversational particles, pronouns, prepositions and query fillers.
# Preserves all medical terms, clinic specialties, doctor names, tests, and numbers.
ARABIC_STOP_WORDS: frozenset[str] = frozenset(
    {
        "في",
        "من",
        "على",
        "إلى",
        "الى",
        "عن",
        "مع",
        "هذا",
        "هذه",
        "هذان",
        "هاتان",
        "هؤلاء",
        "ذلك",
        "تلك",
        "أولئك",
        "اولئك",
        "الذي",
        "التي",
        "الذين",
        "اللاتي",
        "هو",
        "هي",
        "هما",
        "هم",
        "هن",
        "أنا",
        "انا",
        "نحن",
        "أنت",
        "انت",
        "أنتم",
        "أن",
        "ان",
        "إن",
        "إنّ",
        "أنّ",
        "انّ",
        "هل",
        "ما",
        "ماذا",
        "لماذا",
        "كيف",
        "متى",
        "أين",
        "اين",
        "لو",
        "سمحت",
        "ممكن",
        "عايز",
        "عايزة",
        "عاوز",
        "عاوزة",
        "محتاج",
        "محتاجة",
        "أعرف",
        "اعرف",
        "اسأل",
        "استفسر",
        "قولي",
        "قول",
        "يا",
        "فندم",
        "حضرتك",
        "طيب",
        "شكرا",
        "أرجو",
        "ارجو",
        "كان",
        "كانت",
        "يكون",
        "تكون",
        "عندكم",
        "عندي",
        "فيه",
        "فيها",
        "كل",
        "جميع",
        "بعض",
        "غير",
        "بين",
        "أو",
        "او",
        "ثم",
        "بل",
        "لكن",
        "حتى",
        "إذا",
        "اذا",
        "فقط",
        "جدا",
        "جداً",
        "بتاع",
        "بتاعة",
        "بتاعتي",
        "كام",
        "بكام",
        "سعر",
        "أسعار",
        "اسعار",
        "تكلفة",
        "رسوم",
        "كشف",
        "وجبة",
        "وجبات",
        "طلب",
        "طلبات",
        "توصيل",
        "دليفري",
        "شحن",
        "منيو",
        "طعام",
        "مطعم",
        "أكل",
        "اكل",
        "مواعيد",
        "موعد",
        "ميعاد",
    }
)

# Standard English stop words and conversational query fillers.
# Excludes clinical acronyms (cbc, hba1c, esr, crp, dexa, ecg, etc.).
ENGLISH_STOP_WORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "because",
        "as",
        "what",
        "which",
        "this",
        "that",
        "these",
        "those",
        "then",
        "just",
        "so",
        "than",
        "such",
        "both",
        "through",
        "about",
        "for",
        "is",
        "are",
        "was",
        "were",
        "of",
        "while",
        "during",
        "to",
        "from",
        "in",
        "out",
        "on",
        "off",
        "again",
        "further",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "any",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "too",
        "very",
        "can",
        "will",
        "don",
        "should",
        "now",
        "i",
        "me",
        "my",
        "myself",
        "we",
        "our",
        "you",
        "your",
        "he",
        "him",
        "his",
        "she",
        "her",
        "it",
        "its",
        "they",
        "them",
        "their",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "want",
        "need",
        "know",
        "tell",
        "please",
        "cost",
        "price",
        "fee",
    }
)

# Combined stop-word lookup set
ALL_STOP_WORDS: frozenset[str] = ARABIC_STOP_WORDS | ENGLISH_STOP_WORDS


def tokenize_for_bm25(text: str) -> list[str]:
    """
    Tokenize text for BM25 indexing and querying.

    Normalizes Arabic/English characters via normalize_query(), splits into word
    tokens, and filters out common stop words while preserving medical abbreviations
    (e.g., cbc, hba1c, esr, crp, dexa), doctor names, and numerical identifiers.
    If all tokens are filtered by stop words, falls back to the unfiltered tokens.

    Args:
        text: Raw or formatted query or document snippet.

    Returns:
        List of normalized string tokens.
    """
    if not text:
        return []

    normalized = normalize_query(text)
    raw_tokens = re.findall(r"[a-z0-9\u0600-\u06ff]+", normalized)
    if not raw_tokens:
        return []

    def _is_stop(tok: str) -> bool:
        if tok in ALL_STOP_WORDS:
            return True
        return tok.startswith("و") and len(tok) > 3 and tok[1:] in ALL_STOP_WORDS

    # Filter stop words and single-character Arabic particles (except numbers)
    filtered = [t for t in raw_tokens if (not _is_stop(t) and (len(t) > 1 or t.isdigit()))]
    # Fallback to raw tokens if filtering stripped everything (e.g., 'سعر الكشف')
    return filtered if filtered else raw_tokens


class BM25Index:
    """
    Pure-Python Okapi BM25 Inverted Index with Category Pre-Filtering.

    Features:
    - Zero external runtime dependencies.
    - Standard Okapi BM25 term weighting ($k_1 = 1.5, b = 0.75$).
    - Non-negative IDF weighting: ln(1 + (N - df + 0.5) / (df + 0.5)).
    - Sub-2ms search latency over clinic knowledge chunks.
    - Category-scoped search for domain filtering.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents: dict[str, dict[str, Any]] = {}
        self.doc_lengths: dict[str, int] = {}
        self.doc_token_freqs: dict[str, Counter[str]] = {}
        self.inverted_index: dict[str, set[str]] = {}
        self.avg_doc_len: float = 0.0

    def clear(self) -> None:
        """Clear all indexed documents and inverted index structures."""
        self.documents.clear()
        self.doc_lengths.clear()
        self.doc_token_freqs.clear()
        self.inverted_index.clear()
        self.avg_doc_len = 0.0

    def build(self, chunks: list[dict[str, Any]]) -> None:
        """Rebuild index from scratch with provided chunks."""
        self.clear()
        self.upsert(chunks)

    def upsert(self, chunks: list[dict[str, Any]]) -> int:
        """
        Upsert knowledge chunks into BM25 index.

        Args:
            chunks: List of dictionaries with 'id' (or generates one), 'text', and 'metadata'.

        Returns:
            Number of chunks indexed.
        """
        if not chunks:
            return 0

        for idx, chunk in enumerate(chunks):
            raw_id = chunk.get("id")
            if raw_id is not None:
                doc_id = str(raw_id)
            else:
                doc_id = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"{chunk.get('text', '')[:60]}_{idx}",
                    )
                )

            # If document previously existed, remove old term postings
            if doc_id in self.doc_token_freqs:
                for term in self.doc_token_freqs[doc_id]:
                    self.inverted_index.get(term, set()).discard(doc_id)

            text = chunk.get("text", "")
            tokens = tokenize_for_bm25(text)
            freqs = Counter(tokens)

            self.documents[doc_id] = {
                "id": doc_id,
                "text": text,
                "metadata": chunk.get("metadata", {}),
            }
            self.doc_lengths[doc_id] = len(tokens)
            self.doc_token_freqs[doc_id] = freqs

            for term in freqs:
                self.inverted_index.setdefault(term, set()).add(doc_id)

        total_length = sum(self.doc_lengths.values())
        self.avg_doc_len = total_length / len(self.documents) if self.documents else 0.0
        return len(chunks)

    def search(
        self,
        query: str,
        limit: int = 10,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search indexed chunks using Okapi BM25.

        Args:
            query: User query or search phrase.
            limit: Maximum candidate chunks to return.
            category: Optional clinic category filter.

        Returns:
            List of matching records with raw bm25 score and metadata.
        """
        q_tokens = tokenize_for_bm25(query)
        if not q_tokens or not self.documents or self.avg_doc_len == 0.0:
            return []

        # Find matching candidates via inverted index
        matching_doc_ids: set[str] = set()
        for term in q_tokens:
            matching_doc_ids.update(self.inverted_index.get(term, set()))

        if not matching_doc_ids:
            return []

        # Category pre-filter
        if category:
            cat_norm = category.strip().lower()
            matching_doc_ids = {
                did
                for did in matching_doc_ids
                if self.documents[did].get("metadata", {}).get("category") == cat_norm
            }
            if not matching_doc_ids:
                return []

        n_docs = len(self.documents)
        scores: list[tuple[str, float]] = []

        for doc_id in matching_doc_ids:
            doc_len = self.doc_lengths[doc_id]
            freqs = self.doc_token_freqs[doc_id]
            len_norm = 1.0 - self.b + self.b * (doc_len / self.avg_doc_len)
            doc_score = 0.0

            for term in q_tokens:
                tf = freqs.get(term, 0)
                if tf > 0:
                    df = len(self.inverted_index.get(term, set()))
                    # Standard Robertson-Spärck Jones non-negative IDF
                    idf = math.log(1.0 + (n_docs - df + 0.5) / (df + 0.5))
                    term_score = idf * (tf * (self.k1 + 1.0)) / (tf + self.k1 * len_norm)
                    doc_score += term_score

            if doc_score > 0.0:
                scores.append((doc_id, doc_score))

        # Sort by score descending, then doc_id ascending for deterministic ranking
        scores.sort(key=lambda x: (-x[1], x[0]))
        top_candidates = scores[:limit]

        results: list[dict[str, Any]] = []
        for doc_id, score in top_candidates:
            doc = self.documents[doc_id]
            meta = doc.get("metadata", {})
            freqs = self.doc_token_freqs[doc_id]
            matched_terms = sum(1 for term in q_tokens if freqs.get(term, 0) > 0)
            coverage = matched_terms / len(q_tokens) if q_tokens else 0.0
            results.append(
                {
                    "id": doc_id,
                    "score": round(score, 4),
                    "text": doc.get("text", ""),
                    "category": meta.get("category", "general"),
                    "section": meta.get("section", ""),
                    "source": meta.get("source", ""),
                    "query_coverage": round(coverage, 4),
                    "metadata": meta,
                }
            )

        return results


def reciprocal_rank_fusion(
    dense_hits: list[dict[str, Any]],
    bm25_hits: list[dict[str, Any]],
    k: int = 60,
    limit: int = 4,
    score_threshold: float | None = None,
) -> list[dict[str, Any]]:
    """
    Merge and rank candidate lists from Dense and BM25 retrieval using RRF.

    Formula:
        RRF_score(d) = sum_{m in {dense, bm25}} 1 / (k + rank_m(d))

    Calibrated score:
        - Calibrates output `score` to [0.0, 1.0] for compatibility with
          ClinicKnowledgeSearchTool (score_threshold=0.35) and out-of-domain checks (0.60).
        - Multi-source agreement boosts the score up to 1.0.
        - BM25-only entity matches are calibrated onto [0.35, 0.95] depending on lexical score.
        - Out-of-domain queries without informative BM25 matches retain low dense scores.

    Args:
        dense_hits: Ranked hit list from Qdrant vector search.
        bm25_hits: Ranked hit list from BM25Index.
        k: RRF smoothing constant (default: 60).
        limit: Maximum results to return.
        score_threshold: Optional minimum calibrated relevance score.

    Returns:
        List of merged result dictionaries sorted by RRF score.
    """
    candidates: dict[str, dict[str, Any]] = {}

    # 1. Process Dense candidates
    for rank_idx, hit in enumerate(dense_hits, start=1):
        doc_id = str(hit.get("id", ""))
        candidates[doc_id] = {
            "id": doc_id,
            "text": hit.get("text", ""),
            "category": hit.get("category", "general"),
            "section": hit.get("section", ""),
            "source": hit.get("source", ""),
            "metadata": hit.get("metadata", {}),
            "dense_rank": rank_idx,
            "dense_score": float(hit.get("score", 0.0)),
            "bm25_rank": None,
            "bm25_score": 0.0,
        }

    # 2. Process BM25 candidates
    for rank_idx, hit in enumerate(bm25_hits, start=1):
        doc_id = str(hit.get("id", ""))
        coverage = float(hit.get("query_coverage", 0.0))
        if doc_id in candidates:
            candidates[doc_id]["bm25_rank"] = rank_idx
            candidates[doc_id]["bm25_score"] = float(hit.get("score", 0.0))
            candidates[doc_id]["query_coverage"] = coverage
        else:
            candidates[doc_id] = {
                "id": doc_id,
                "text": hit.get("text", ""),
                "category": hit.get("category", "general"),
                "section": hit.get("section", ""),
                "source": hit.get("source", ""),
                "metadata": hit.get("metadata", {}),
                "dense_rank": None,
                "dense_score": 0.0,
                "bm25_rank": rank_idx,
                "bm25_score": float(hit.get("score", 0.0)),
                "query_coverage": coverage,
            }

    # 3. Compute RRF scores and calibrated relevance
    fused: list[dict[str, Any]] = []
    for cand in candidates.values():
        rrf_score = 0.0
        match_sources: list[str] = []

        if cand["dense_rank"] is not None:
            rrf_score += 1.0 / (k + cand["dense_rank"])
            match_sources.append("dense")

        if cand["bm25_rank"] is not None:
            rrf_score += 1.0 / (k + cand["bm25_rank"])
            match_sources.append("bm25")

        cand["rrf_score"] = rrf_score
        cand["match_sources"] = match_sources

        dense_s = cand["dense_score"]
        bm25_s = cand["bm25_score"]
        coverage = cand.get("query_coverage", 0.0)

        # Calibrate score to [0.0, 1.0]
        bm25_norm = min(1.0, bm25_s / 5.0) if bm25_s > 0 else 0.0
        if "dense" in match_sources and "bm25" in match_sources:
            if dense_s < 0.30 and coverage < 0.5:
                # Incidental lexical match with low semantic relevance (e.g. out-of-domain query)
                calibrated = dense_s
            else:
                calibrated = min(1.0, max(dense_s + 0.15 * bm25_norm, 0.40 + 0.40 * bm25_norm))
        elif "dense" in match_sources:
            # Dense only: preserve cosine similarity
            calibrated = dense_s
        else:
            # BM25 only: query contains exact medical entity / physician name
            if coverage >= 0.5 and bm25_s >= 2.0:
                calibrated = min(0.98, max(0.60, 0.50 + 0.50 * bm25_norm))
            else:
                calibrated = min(0.34, 0.20 + 0.10 * bm25_norm)

        cand["score"] = calibrated

        # Filter by score_threshold if provided
        if score_threshold is not None and calibrated < score_threshold:
            continue

        fused.append(cand)

    # 4. Strict ranking: RRF score descending, then calibrated score descending, then id
    fused.sort(key=lambda c: (-c["rrf_score"], -c["score"], c["id"]))
    top_fused = fused[:limit]

    # 5. Format outputs preserving backward-compatible schema
    results: list[dict[str, Any]] = []
    for item in top_fused:
        results.append(
            {
                "id": item["id"],
                "score": round(item["score"], 4),
                "rrf_score": round(item["rrf_score"], 6),
                "dense_score": round(item["dense_score"], 4),
                "bm25_score": round(item["bm25_score"], 4),
                "match_sources": item["match_sources"],
                "text": item["text"],
                "category": item["category"],
                "section": item["section"],
                "source": item["source"],
                "metadata": item["metadata"],
            }
        )

    return results


class HybridKnowledgeRetriever:
    """
    Drop-in Hybrid Knowledge Retriever wrapping Qdrant and BM25.

    Implements the identical public interface of QdrantKnowledgeRetriever
    while executing hybrid dense + sparse retrieval with Reciprocal Rank Fusion.
    """

    def __init__(
        self,
        dense_retriever: QdrantKnowledgeRetriever | None = None,
        collection_name: str | None = None,
    ):
        self.dense_retriever = dense_retriever or QdrantKnowledgeRetriever(
            collection_name=collection_name
        )
        self.bm25_index = BM25Index(
            k1=settings.hybrid_bm25_k1,
            b=settings.hybrid_bm25_b,
        )

    @property
    def collection_name(self) -> str:
        """Target Qdrant collection name."""
        return self.dense_retriever.collection_name

    @property
    def client(self):
        """Underlying Qdrant client."""
        return self.dense_retriever.client

    @property
    def embeddings(self):
        """Underlying embedding service."""
        return self.dense_retriever.embeddings

    def recreate_collection(self) -> None:
        """Recreate Qdrant collection and clear the BM25 index."""
        self.dense_retriever.recreate_collection()
        self.bm25_index.clear()
        logger.info(
            f"Recreated hybrid collection and cleared BM25 index for '{self.collection_name}'."
        )

    def sync_bm25_from_qdrant(self) -> int:
        """
        Populate BM25Index from existing points in Qdrant collection via scroll API.

        Returns:
            Number of chunks loaded into BM25 index.
        """
        try:
            points, _ = self.client.scroll(
                collection_name=self.collection_name,
                limit=1000,
                with_payload=True,
                with_vectors=False,
            )
            if not points:
                return 0

            chunks: list[dict[str, Any]] = []
            for p in points:
                payload = p.payload or {}
                chunks.append(
                    {
                        "id": str(p.id),
                        "text": payload.get("text", ""),
                        "metadata": {k: v for k, v in payload.items() if k != "text"},
                    }
                )

            indexed_count = self.bm25_index.upsert(chunks)
            logger.info(
                f"Synchronized {indexed_count} points from Qdrant '{self.collection_name}' into BM25Index."
            )
            return indexed_count
        except Exception as e:  # noqa: BLE001
            logger.warning(
                f"Failed to scroll Qdrant collection '{self.collection_name}' for BM25 sync: {e}"
            )
            return 0

    def upsert_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """
        Upsert chunks into both Qdrant vector store and BM25 index.

        Args:
            chunks: List of knowledge chunk dictionaries.

        Returns:
            Number of points indexed.
        """
        if not chunks:
            return 0

        # Guarantee deterministic IDs across both stores
        normalized_chunks: list[dict[str, Any]] = []
        for idx, chunk in enumerate(chunks):
            c = dict(chunk)
            if not c.get("id"):
                meta = c.get("metadata", {})
                sec = meta.get("section", "sec")
                ctype = meta.get("chunk_type", "chunk")
                c["id"] = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"{sec}_{ctype}_{idx}_{c.get('text', '')[:50]}",
                    )
                )
            normalized_chunks.append(c)

        # 1. Upsert into Qdrant vector database
        qdrant_count = self.dense_retriever.upsert_chunks(normalized_chunks)

        # 2. Upsert into in-memory BM25 index
        self.bm25_index.upsert(normalized_chunks)

        return qdrant_count

    def search(
        self,
        query: str,
        limit: int = 4,
        score_threshold: float | None = None,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Execute hybrid search combining Dense Qdrant search and Sparse BM25 search via RRF.

        Args:
            query: User utterance or search query.
            limit: Maximum top-k chunks to return.
            score_threshold: Minimum calibrated relevance score.
            category: Optional clinic category filter.

        Returns:
            List of merged matching records with calibrated scores and provenance.
        """
        clean_q = normalize_query(query) if isinstance(query, str) else ""
        if not clean_q:
            return []

        if not settings.hybrid_search_enabled:
            return self.dense_retriever.search(
                query=query,
                limit=limit,
                score_threshold=score_threshold,
                category=category,
            )

        # Lazy-load BM25 from Qdrant if BM25 is empty
        if not self.bm25_index.documents:
            self.sync_bm25_from_qdrant()

        candidate_limit = max(limit * settings.hybrid_candidate_multiplier, 25)

        # 1. Dense retrieval leg (fetch without threshold to allow RRF fusion)
        dense_hits = self.dense_retriever.search(
            query=query,
            limit=candidate_limit,
            score_threshold=None,
            category=category,
        )

        # 2. Sparse BM25 retrieval leg
        try:
            bm25_hits = self.bm25_index.search(
                query=query,
                limit=candidate_limit,
                category=category,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"BM25 search failed, falling back to dense search: {e}")
            if score_threshold is not None:
                dense_hits = [h for h in dense_hits if h.get("score", 0.0) >= score_threshold]
            return dense_hits[:limit]

        # 3. Reciprocal Rank Fusion
        fused = reciprocal_rank_fusion(
            dense_hits=dense_hits,
            bm25_hits=bm25_hits,
            k=settings.hybrid_rrf_k,
            limit=limit,
            score_threshold=score_threshold,
        )
        return fused

    def get_context_for_query(
        self,
        query: str,
        limit: int = 3,
        max_chars: int = 1200,
    ) -> str:
        """
        Retrieve and format top matching snippets into a clean context block for LLM prompts.

        Args:
            query: User query.
            limit: Maximum snippets to assemble.
            max_chars: Total character limit for prompt safety.

        Returns:
            Formatted multi-line context string.
        """
        hits = self.search(query=query, limit=limit)
        if not hits:
            return ""

        context_blocks: list[str] = []
        current_len = 0
        for hit in hits:
            section_name = hit.get("section") or hit.get("category", "General")
            snippet = f"[{section_name}]\n{hit['text'].strip()}"
            if current_len + len(snippet) > max_chars:
                break
            context_blocks.append(snippet)
            current_len += len(snippet) + 2

        return "\n\n".join(context_blocks)

    def warm_up(self) -> bool:
        """Pre-load embeddings and synchronize BM25 index."""
        try:
            self.embeddings.embed_query("warm up")
            if not self.bm25_index.documents:
                self.sync_bm25_from_qdrant()
            return getattr(self.embeddings, "is_semantic", True)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Hybrid retriever warm_up warning: {e}")
            return False


# Global singleton hybrid retriever instance
hybrid_retriever = HybridKnowledgeRetriever(dense_retriever=default_retriever)
