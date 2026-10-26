"""
3-Tier Caching Ladder for Voice AI Agent (Enterprise Architecture).

Implements:
1. Tier 1: Exact Hash Cache (normalized SHA-256 with in-memory LRU + TTL).
2. Tier 2: Metadata-Scoped Semantic Cache (Qdrant collection filtered by category/language/kb_version).
3. Tier 3: Prompt Prefix Caching (static-first PromptPrefixBuilder).
4. CacheabilityPolicy & OutputValidator (fail-closed guardrail gates).
5. Fail-open execution, graceful fallbacks, and telemetry snapshot.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from enum import Enum
from typing import (
    Any,
    ClassVar,
    Literal,
    Protocol,
    runtime_checkable,
)

from pydantic import BaseModel
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from src.ai_core.gateway import DegradationTier, GatewayResult, ModelGateway, Stage
from src.ai_core.text_normalizer import (
    build_exact_key,
    compute_kb_version,
    normalize_query,
)
from src.config import Settings, get_settings
from src.rag.embeddings import EmbeddingService, embedding_service
from src.tools.human_handoff import detect_emergency

logger = logging.getLogger(__name__)


# ==============================================================================
# Domain Types and Enums
# ==============================================================================


class CacheTier(str, Enum):
    """Tier that resolved the cached request."""

    EXACT = "EXACT"  # Tier 1 Exact Hash Hit (< 5ms)
    SEMANTIC = "SEMANTIC"  # Tier 2 Semantic Cosine Hit (< 30ms)
    MISS = "MISS"  # Cache miss; proceed to LLM Gateway
    BYPASS = "BYPASS"  # Query or system bypassed caching


class BypassReason(str, Enum):
    """Explicit rationale when query or response bypasses caching."""

    DISABLED = "disabled"  # Cache or tier globally disabled via config
    CATEGORY_NOT_ALLOWED = "category_not_allowed"  # Category not in allowlist (e.g. doctors)
    PERSONAL_QUERY = "personal_query"  # Phone, national ID, or personal reference word detected
    EMERGENCY = "emergency"  # Urgent symptom / emergency detected
    EMBEDDING_FALLBACK = "embedding_fallback"  # Embedding service in pseudo-hash fallback mode
    TIMEOUT = "timeout"  # Semantic search timed out (> 50ms)
    BACKEND_ERROR = "backend_error"  # Storage or search exception caught
    EMPTY_QUERY = "empty_query"  # Query is empty or whitespace only


class CacheScope(BaseModel):
    """Metadata scope restricting cache lookup and storage."""

    category: str | None = None
    language: Literal["ar", "en"] = "ar"
    specialty: str | None = None


class CacheResult(BaseModel):
    """Detailed outcome of a CacheLadder lookup."""

    hit: bool
    tier: CacheTier
    text: str | None = None
    similarity: float | None = None
    latency_ms: float = 0.0
    bypass_reason: BypassReason | None = None
    kb_version: str | None = None


class CacheEntry(BaseModel):
    """In-memory entry stored in Tier 1 cache."""

    key: str
    query_norm: str
    text: str
    category: str | None
    language: str
    kb_version: str
    created_at: float
    expires_at: float


class CachedTurnResult(BaseModel):
    """Composite result returned by cached_generate helper."""

    text: str | None
    cache: CacheResult
    gateway: GatewayResult | None = None


# ==============================================================================
# Protocols (Interfaces)
# ==============================================================================


@runtime_checkable
class CacheBackend(Protocol):
    """Protocol for Tier 1 key-value storage (in-memory or Redis)."""

    async def get(self, key: str) -> CacheEntry | None: ...

    async def set(self, key: str, value: CacheEntry, ttl_s: int) -> None: ...

    async def delete(self, key: str) -> bool: ...

    async def clear(self, category: str | None = None) -> int: ...

    def size(self) -> int: ...


@runtime_checkable
class OutputValidator(Protocol):
    """Protocol validating LLM response safety before writing to cache."""

    def is_valid(self, response_text: str) -> bool: ...


# ==============================================================================
# Cacheability Policy & Default Output Validator
# ==============================================================================


class CacheabilityPolicy:
    """
    Enforces privacy, safety, and domain rules determining whether a query
    or LLM response is eligible for caching.
    """

    # Mobile numbers (e.g., 010, 011, 012, 015 + 8 digits)
    _PHONE_REGEX = re.compile(r"\b01[0125]\d{8}\b")
    # Egyptian 14-digit National ID
    _NATIONAL_ID_REGEX = re.compile(r"\b\d{14}\b")
    # General long digit sequence (>= 6 digits: accounts, booking refs, IDs)
    _LONG_DIGIT_REGEX = re.compile(r"\b\d{6,}\b")

    # Arabic personal reference keywords
    _PERSONAL_WORDS_AR: ClassVar[set[str]] = {
        "حجزي",
        "ميعادي",
        "معادي",
        "نمرتي",
        "اسمي",
        "رقمي",
        "كشفي",
        "دوري",
        "دورى",
        "تحاليلي",
        "روشتتي",
    }

    # English personal reference keywords / phrases
    _PERSONAL_PHRASES_EN: ClassVar[list[str]] = [
        "my appointment",
        "my booking",
        "my reservation",
        "my number",
        "my name",
        "my visit",
        "cancel my",
        "reschedule my",
    ]

    def __init__(self, allowed_categories: list[str] | set[str] | None = None) -> None:
        self.allowed_categories = set(
            allowed_categories
            or [
                "general",
                "specialties",
                "pricing",
                "lab_radiology",
                "insurance",
                "faqs",
            ]
        )

    def allows_query(
        self, query: str, scope: CacheScope | None = None
    ) -> tuple[bool, BypassReason | None]:
        """
        Evaluate if user query is safe and eligible for caching.

        Returns:
            (True, None) if allowed, or (False, BypassReason) if bypassed.
        """
        if not query or not query.strip():
            return False, BypassReason.EMPTY_QUERY

        # 1. Category check if explicitly specified
        if scope and scope.category:
            cat_norm = scope.category.strip().lower()
            if cat_norm not in self.allowed_categories:
                return False, BypassReason.CATEGORY_NOT_ALLOWED

        # 2. Emergency triage check
        if detect_emergency(query):
            return False, BypassReason.EMERGENCY

        # 3. PII / Numeric identifier checks
        if self._PHONE_REGEX.search(query):
            return False, BypassReason.PERSONAL_QUERY
        if self._NATIONAL_ID_REGEX.search(query):
            return False, BypassReason.PERSONAL_QUERY
        if self._LONG_DIGIT_REGEX.search(query):
            return False, BypassReason.PERSONAL_QUERY

        # 4. Personal keywords checks (Arabic)
        tokens = set(re.findall(r"\b\w+\b", query.lower()))
        if any(w in tokens for w in self._PERSONAL_WORDS_AR):
            return False, BypassReason.PERSONAL_QUERY

        # 5. Personal keywords checks (English)
        q_lower = query.lower()
        if any(phrase in q_lower for phrase in self._PERSONAL_PHRASES_EN):
            return False, BypassReason.PERSONAL_QUERY

        return True, None

    def allows_response(
        self,
        response_text: str | None,
        degradation_tier: DegradationTier | str,
        tool_calls: list[Any] | None = None,
        truncated: bool = False,
    ) -> tuple[bool, str | None]:
        """
        Evaluate if an LLM generated response is safe and eligible for caching.

        Returns:
            (True, None) if storeable, or (False, rejection_reason) if rejected.
        """
        if not response_text or not response_text.strip():
            return False, "empty_response"

        if truncated:
            return False, "response_truncated"

        if tool_calls and len(tool_calls) > 0:
            return False, "contains_tool_calls"

        tier_str = str(degradation_tier)
        if (
            DegradationTier.TIER_3_SEARCH_ONLY.value in tier_str
            or DegradationTier.TIER_4_HUMAN_ESCALATION.value in tier_str
        ):
            return False, "degraded_fallback_response"

        # Check for leaked personal identifiers in generated text
        if self._PHONE_REGEX.search(response_text) or self._NATIONAL_ID_REGEX.search(response_text):
            return False, "contains_personal_identifiers"

        return True, None


class DefaultOutputValidator:
    """
    Conservative fail-closed output validator that rejects medical prescriptions,
    drug dosages, direct medical diagnosis, and unauthorized commercial promises.
    """

    _MED_PRESCRIPTION_WORDS: ClassVar[set[str]] = {
        "بنادول",
        "بانادول",
        "مضاد حيوي",
        "جرعة",
        "أقراص",
        "اقراص",
        "كبسول",
        "كبسولات",
        "روشتة",
        "روشته",
        "ملجم",
        "panadol",
        "antibiotic",
        "dosage",
        "tablets",
        "capsules",
        "prescription",
    }

    _MED_PRESCRIPTION_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"\b\d+\s*(ملجم|mg)\b", re.IGNORECASE),
        re.compile(r"مرتين\s+في\s+اليوم", re.IGNORECASE),
        re.compile(r"(قبل|بعد)\s+الأكل", re.IGNORECASE),
        re.compile(r"خد\s+\w+", re.IGNORECASE),
    ]

    _DIAGNOSIS_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"عندك\s+التهاب", re.IGNORECASE),
        re.compile(r"تشخيص\s+حالتك", re.IGNORECASE),
        re.compile(r"بتعاني\s+من", re.IGNORECASE),
        re.compile(r"محتمل\s+يكون\s+عندك", re.IGNORECASE),
        re.compile(r"أنت\s+مصاب", re.IGNORECASE),
        re.compile(r"you\s+have\s+inflammation", re.IGNORECASE),
        re.compile(r"diagnosis\s+is", re.IGNORECASE),
    ]

    _DISCOUNT_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"هعملك\s+خصم", re.IGNORECASE),
        re.compile(r"خصم\s+خاص\s+لحضرتك", re.IGNORECASE),
        re.compile(r"مجاناً\s+عشانك", re.IGNORECASE),
        re.compile(r"أضمن\s+لك", re.IGNORECASE),
        re.compile(r"special\s+discount\s+for\s+you", re.IGNORECASE),
        re.compile(r"free\s+for\s+you", re.IGNORECASE),
    ]

    def is_valid(self, response_text: str) -> bool:
        """
        Verify that response text does not contain prohibited medical or promotional content.
        Fails closed on any exception.
        """
        if not response_text:
            return False

        try:
            resp_lower = response_text.lower()
            if any(w in resp_lower for w in self._MED_PRESCRIPTION_WORDS):
                return False

            tokens = set(re.findall(r"\b\w+\b", resp_lower))
            if any(w in tokens for w in self._MED_PRESCRIPTION_WORDS):
                return False

            for pat in self._MED_PRESCRIPTION_PATTERNS:
                if pat.search(response_text):
                    return False

            for pat in self._DIAGNOSIS_PATTERNS:
                if pat.search(response_text):
                    return False

            for pat in self._DISCOUNT_PATTERNS:
                if pat.search(response_text):
                    return False

            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"DefaultOutputValidator encountered error (fail-closed): {e}")
            return False


# ==============================================================================
# Tier 1: In-Memory LRU Backend
# ==============================================================================


class InMemoryLRUBackend:
    """
    In-memory thread-safe and async-safe LRU cache backend with TTL expiration.
    """

    def __init__(
        self,
        max_entries: int = 2000,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.max_entries = max_entries
        self._clock = clock
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> CacheEntry | None:
        async with self._lock:
            if key not in self._cache:
                return None

            entry = self._cache[key]
            now = self._clock()
            if entry.expires_at <= now:
                del self._cache[key]
                return None

            # Mark recently used by moving to end
            self._cache.move_to_end(key)
            return entry

    async def set(self, key: str, value: CacheEntry, ttl_s: int) -> None:
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = value

            # Evict least-recently-used (first item) if capacity exceeded
            if len(self._cache) > self.max_entries:
                self._cache.popitem(last=False)

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    async def clear(self, category: str | None = None) -> int:
        async with self._lock:
            if category is None:
                count = len(self._cache)
                self._cache.clear()
                return count

            keys_to_del = [
                k for k, v in self._cache.items() if (v.category or "").lower() == category.lower()
            ]
            for k in keys_to_del:
                del self._cache[k]
            return len(keys_to_del)

    def size(self) -> int:
        return len(self._cache)


# ==============================================================================
# Tier 2: Qdrant Semantic Cache Store
# ==============================================================================


class SemanticCacheStore:
    """
    Manages vector storage and similarity search in dedicated Qdrant collection.
    """

    def __init__(
        self,
        client: QdrantClient,
        collection_name: str,
        dimension: int = 384,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self.collection_name = collection_name
        self.dimension = dimension
        self._clock = clock
        self._initialized = False

    def _ensure_collection(self) -> None:
        if self._initialized:
            return

        try:
            collections = self.client.get_collections().collections
            exists = any(col.name == self.collection_name for col in collections)
            if not exists:
                logger.info(f"Creating semantic cache collection '{self.collection_name}'...")
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=self.dimension,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
                for field in ["category", "language", "kb_version"]:
                    try:
                        self.client.create_payload_index(
                            collection_name=self.collection_name,
                            field_name=field,
                            field_schema=qmodels.PayloadSchemaType.KEYWORD,
                        )
                    except Exception as idx_err:  # noqa: BLE001
                        logger.debug(f"Payload index creation note for '{field}': {idx_err}")
            self._initialized = True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error ensuring semantic cache collection: {e}")

    async def search(
        self,
        query_vector: list[float],
        category: str,
        language: str,
        kb_version: str,
        score_threshold: float = 0.97,
        limit: int = 1,
    ) -> list[dict[str, Any]]:
        """
        Execute cosine similarity search with exact pre-filters for category, language, and kb_version.
        """
        self._ensure_collection()
        now = self._clock()

        query_filter = qmodels.Filter(
            must=[
                qmodels.FieldCondition(
                    key="category", match=qmodels.MatchValue(value=category.lower())
                ),
                qmodels.FieldCondition(
                    key="language", match=qmodels.MatchValue(value=language.lower())
                ),
                qmodels.FieldCondition(
                    key="kb_version", match=qmodels.MatchValue(value=kb_version)
                ),
            ]
        )

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
        except Exception as e:  # noqa: BLE001
            logger.error(f"Qdrant semantic search error: {e}")
            return []

        results: list[dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            expires_at = float(payload.get("expires_at", 0.0))
            if expires_at <= now:
                continue

            results.append(
                {
                    "id": str(hit.id),
                    "score": round(float(hit.score), 4),
                    "text": payload.get("response_text", ""),
                    "category": payload.get("category", ""),
                    "language": payload.get("language", ""),
                    "query_norm": payload.get("query_norm", ""),
                    "kb_version": payload.get("kb_version", ""),
                }
            )

        return results

    async def upsert(
        self,
        point_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """Upsert a point into semantic cache collection."""
        self._ensure_collection()
        try:
            # Format point id into valid UUID string if not already
            try:
                uuid.UUID(str(point_id))
                pid = str(point_id)
            except ValueError:
                pid = str(uuid.uuid5(uuid.NAMESPACE_DNS, str(point_id)))

            point = qmodels.PointStruct(
                id=pid,
                vector=vector,
                payload=payload,
            )
            self.client.upsert(
                collection_name=self.collection_name,
                points=[point],
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to upsert point into semantic cache: {e}")

    async def invalidate(self, category: str | None = None) -> int:
        """Invalidate entries in semantic collection matching category filter."""
        self._ensure_collection()
        must_filters = []
        if category:
            must_filters.append(
                qmodels.FieldCondition(
                    key="category", match=qmodels.MatchValue(value=category.lower())
                )
            )

        filter_condition = qmodels.Filter(must=must_filters) if must_filters else qmodels.Filter()
        try:
            self.client.delete(
                collection_name=self.collection_name,
                points_selector=filter_condition,
            )
            return 1
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Error invalidating semantic cache: {e}")
            return 0


# ==============================================================================
# Tier 3: Prompt Prefix Cache Builder
# ==============================================================================


class PromptPrefixBuilder:
    """
    Structures system prompts and conversation messages static-first to optimize
    provider KV-cache prefix hits (Groq and Google Gemini).
    """

    def __init__(
        self,
        static_instructions: str,
        tool_schemas: list[dict[str, Any]] | None = None,
        few_shots: list[dict[str, Any]] | None = None,
    ) -> None:
        # Guarantee no dynamic datetime or session templates inside static prefix
        if "{current_datetime}" in static_instructions or "{now}" in static_instructions:
            raise ValueError("Static instructions must not contain dynamic date/time placeholders")

        self.static_instructions = static_instructions.strip()
        self.tool_schemas = tool_schemas or []
        self.few_shots = few_shots or []

        # Construct deterministic canonical static representation
        prefix_blocks = [self.static_instructions]
        if self.tool_schemas:
            prefix_blocks.append(
                "## AVAILABLE TOOLS:\n"
                + json.dumps(self.tool_schemas, sort_keys=True, ensure_ascii=False)
            )
        if self.few_shots:
            prefix_blocks.append(
                "## FEW SHOT EXAMPLES:\n"
                + json.dumps(self.few_shots, sort_keys=True, ensure_ascii=False)
            )

        self.canonical_static_text = "\n\n".join(prefix_blocks)
        self.prefix_hash = hashlib.sha256(self.canonical_static_text.encode("utf-8")).hexdigest()

    def build(
        self,
        dynamic_context: str | None = None,
        history: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Assemble messages list ordered:
        [1. System (Static)] -> [2. System (Dynamic Context)] -> [3. History]

        Returns:
            (messages, prefix_hash)
        """
        messages: list[dict[str, Any]] = [{"role": "system", "content": self.canonical_static_text}]

        if dynamic_context and dynamic_context.strip():
            messages.append(
                {
                    "role": "system",
                    "content": f"## DYNAMIC CALL CONTEXT:\n{dynamic_context.strip()}",
                }
            )

        if history:
            messages.extend(history)

        return messages, self.prefix_hash


# ==============================================================================
# Central Orchestrator: CacheLadder
# ==============================================================================


class CacheLadder:
    """
    Coordinates 3-tier caching ladder: Exact Hash (Tier 1), Metadata Semantic (Tier 2),
    and Prompt Prefix verification (Tier 3).
    """

    def __init__(
        self,
        settings: Settings | None = None,
        tier1_backend: CacheBackend | None = None,
        semantic_store: SemanticCacheStore | None = None,
        embeddings: EmbeddingService | None = None,
        policy: CacheabilityPolicy | None = None,
        output_validator: OutputValidator | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.settings = settings or get_settings()
        self._clock = clock
        self.policy = policy or CacheabilityPolicy(self.settings.cache_allowed_categories)
        self.output_validator = output_validator or DefaultOutputValidator()
        self.embeddings = embeddings or embedding_service

        # Tier 1 Backend
        self.tier1_backend = tier1_backend or InMemoryLRUBackend(
            max_entries=self.settings.cache_max_entries,
            clock=self._clock,
        )

        # Tier 2 Store
        if semantic_store is not None:
            self.semantic_store = semantic_store
        else:
            qdrant_client = (
                QdrantClient(url=self.settings.qdrant_url, api_key=self.settings.qdrant_api_key)
                if self.settings.is_qdrant_cloud()
                else QdrantClient(":memory:")
            )
            self.semantic_store = SemanticCacheStore(
                client=qdrant_client,
                collection_name=self.settings.cache_semantic_collection,
                dimension=self.embeddings.dimension,
                clock=self._clock,
            )

        # Knowledge Base Version Digest
        self.kb_version = compute_kb_version(self.settings.cache_kb_path)
        self._warned_embedding_fallback = False

        # In-process telemetry counters
        self._counters = {
            "tier1_hits": 0,
            "tier2_hits": 0,
            "misses": 0,
            "bypasses": {reason.value: 0 for reason in BypassReason},
            "stores": 0,
            "store_rejected": 0,
            "errors": 0,
        }

    def _get_ttl_for_category(self, category: str | None) -> int:
        if not category:
            return self.settings.cache_default_ttl_s
        cat_key = category.strip().lower()
        return self.settings.cache_ttl_by_category.get(cat_key, self.settings.cache_default_ttl_s)

    async def lookup(self, query: str, scope: CacheScope | None = None) -> CacheResult:
        """
        Evaluate Tier 1 then Tier 2 cache. Guaranteed fail-open (never raises).
        """
        start_t = time.perf_counter()
        effective_scope = scope or CacheScope()

        # Check global kill switch
        if not self.settings.cache_enabled:
            self._counters["bypasses"][BypassReason.DISABLED.value] += 1
            return CacheResult(
                hit=False,
                tier=CacheTier.BYPASS,
                bypass_reason=BypassReason.DISABLED,
                latency_ms=(time.perf_counter() - start_t) * 1000,
                kb_version=self.kb_version,
            )

        # Evaluate Cacheability Policy
        allowed, bypass_reason = self.policy.allows_query(query, effective_scope)
        if not allowed:
            reason = bypass_reason or BypassReason.CATEGORY_NOT_ALLOWED
            self._counters["bypasses"][reason.value] += 1
            return CacheResult(
                hit=False,
                tier=CacheTier.BYPASS,
                bypass_reason=reason,
                latency_ms=(time.perf_counter() - start_t) * 1000,
                kb_version=self.kb_version,
            )

        norm_query = normalize_query(query)
        exact_key = build_exact_key(
            normalized_query=norm_query,
            category=effective_scope.category,
            language=effective_scope.language,
            kb_version=self.kb_version,
        )

        # ----------------------------------------------------------------------
        # Tier 1: Exact Hash Cache Lookup
        # ----------------------------------------------------------------------
        if self.settings.cache_exact_enabled:
            try:
                entry = await self.tier1_backend.get(exact_key)
                if entry is not None:
                    lat = (time.perf_counter() - start_t) * 1000
                    self._counters["tier1_hits"] += 1
                    return CacheResult(
                        hit=True,
                        tier=CacheTier.EXACT,
                        text=entry.text,
                        latency_ms=lat,
                        kb_version=self.kb_version,
                    )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Tier 1 cache lookup exception (fail-open): {e}")
                self._counters["errors"] += 1

        # ----------------------------------------------------------------------
        # Tier 2: Metadata-Scoped Semantic Cache Lookup
        # ----------------------------------------------------------------------
        if (
            self.settings.cache_semantic_enabled
            and effective_scope.category
            and effective_scope.category.strip().lower() in self.policy.allowed_categories
        ):
            # Guard against pseudo-hash fallback embeddings
            if not self.embeddings.is_semantic:
                if not self._warned_embedding_fallback:
                    logger.warning(
                        "EmbeddingService in fallback mode. Disabling Tier 2 Semantic Cache."
                    )
                    self._warned_embedding_fallback = True
                self._counters["bypasses"][BypassReason.EMBEDDING_FALLBACK.value] += 1
                return CacheResult(
                    hit=False,
                    tier=CacheTier.MISS,
                    bypass_reason=BypassReason.EMBEDDING_FALLBACK,
                    latency_ms=(time.perf_counter() - start_t) * 1000,
                    kb_version=self.kb_version,
                )

            # Bound vector search with timeout
            timeout_s = self.settings.cache_semantic_timeout_ms / 1000.0
            try:
                # Embed query in background thread to avoid blocking event loop
                vector = await asyncio.wait_for(
                    asyncio.to_thread(self.embeddings.embed_query, norm_query),
                    timeout=timeout_s,
                )

                hits = await asyncio.wait_for(
                    self.semantic_store.search(
                        query_vector=vector,
                        category=effective_scope.category,
                        language=effective_scope.language,
                        kb_version=self.kb_version,
                        score_threshold=self.settings.cache_semantic_threshold,
                        limit=1,
                    ),
                    timeout=timeout_s,
                )

                if hits:
                    best_hit = hits[0]
                    lat = (time.perf_counter() - start_t) * 1000
                    self._counters["tier2_hits"] += 1

                    # Promote semantic hit into Tier 1 for rapid subsequent exact lookups
                    ttl = self._get_ttl_for_category(effective_scope.category)
                    now = self._clock()
                    promoted_entry = CacheEntry(
                        key=exact_key,
                        query_norm=norm_query,
                        text=best_hit["text"],
                        category=effective_scope.category,
                        language=effective_scope.language,
                        kb_version=self.kb_version,
                        created_at=now,
                        expires_at=now + ttl,
                    )
                    await self.tier1_backend.set(exact_key, promoted_entry, ttl)

                    return CacheResult(
                        hit=True,
                        tier=CacheTier.SEMANTIC,
                        text=best_hit["text"],
                        similarity=best_hit["score"],
                        latency_ms=lat,
                        kb_version=self.kb_version,
                    )

            except asyncio.TimeoutError:
                logger.debug(
                    f"Tier 2 semantic cache search timed out (> {self.settings.cache_semantic_timeout_ms}ms)"
                )
                self._counters["bypasses"][BypassReason.TIMEOUT.value] += 1
                return CacheResult(
                    hit=False,
                    tier=CacheTier.MISS,
                    bypass_reason=BypassReason.TIMEOUT,
                    latency_ms=(time.perf_counter() - start_t) * 1000,
                    kb_version=self.kb_version,
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Tier 2 semantic cache lookup error (fail-open): {e}")
                self._counters["errors"] += 1
                return CacheResult(
                    hit=False,
                    tier=CacheTier.MISS,
                    bypass_reason=BypassReason.BACKEND_ERROR,
                    latency_ms=(time.perf_counter() - start_t) * 1000,
                    kb_version=self.kb_version,
                )

        # Cache Miss
        self._counters["misses"] += 1
        return CacheResult(
            hit=False,
            tier=CacheTier.MISS,
            latency_ms=(time.perf_counter() - start_t) * 1000,
            kb_version=self.kb_version,
        )

    async def store(
        self,
        query: str,
        scope: CacheScope,
        response_text: str | None,
        *,
        degradation_tier: DegradationTier | str = DegradationTier.TIER_1_PRIMARY,
        tool_calls: list[Any] | None = None,
        truncated: bool = False,
    ) -> bool:
        """
        Store public answer in Tier 1 and Tier 2 caches after passing safety gates.
        Fail-closed: Returns False and writes nothing if validation fails.
        """
        if not self.settings.cache_enabled:
            return False

        # 1. Query-side cacheability check
        allowed_q, _ = self.policy.allows_query(query, scope)
        if not allowed_q:
            self._counters["store_rejected"] += 1
            return False

        # 2. Response-side cacheability check
        allowed_resp, reason = self.policy.allows_response(
            response_text=response_text,
            degradation_tier=degradation_tier,
            tool_calls=tool_calls,
            truncated=truncated,
        )
        if not allowed_resp:
            logger.debug(f"Cache store rejected response: {reason}")
            self._counters["store_rejected"] += 1
            return False

        # 3. Output Guardrail safety check (Fail-closed)
        assert response_text is not None
        try:
            if not self.output_validator.is_valid(response_text):
                logger.debug("Cache store rejected response via OutputValidator")
                self._counters["store_rejected"] += 1
                return False
        except Exception as val_err:  # noqa: BLE001
            logger.warning(
                f"OutputValidator raised exception during store (fail-closed): {val_err}"
            )
            self._counters["store_rejected"] += 1
            return False

        norm_query = normalize_query(query)
        exact_key = build_exact_key(
            normalized_query=norm_query,
            category=scope.category,
            language=scope.language,
            kb_version=self.kb_version,
        )
        ttl = self._get_ttl_for_category(scope.category)
        now = self._clock()

        entry = CacheEntry(
            key=exact_key,
            query_norm=norm_query,
            text=response_text.strip(),
            category=scope.category,
            language=scope.language,
            kb_version=self.kb_version,
            created_at=now,
            expires_at=now + ttl,
        )

        try:
            # Write to Tier 1
            if self.settings.cache_exact_enabled:
                await self.tier1_backend.set(exact_key, entry, ttl)

            # Write to Tier 2
            if (
                self.settings.cache_semantic_enabled
                and scope.category
                and scope.category.strip().lower() in self.policy.allowed_categories
                and self.embeddings.is_semantic
            ):
                vector = await asyncio.to_thread(self.embeddings.embed_query, norm_query)
                payload = {
                    "query_norm": norm_query,
                    "response_text": response_text.strip(),
                    "category": scope.category.strip().lower(),
                    "language": scope.language.strip().lower(),
                    "kb_version": self.kb_version,
                    "created_at": now,
                    "expires_at": now + ttl,
                }
                await self.semantic_store.upsert(
                    point_id=exact_key,
                    vector=vector,
                    payload=payload,
                )

            self._counters["stores"] += 1
            return True

        except Exception as e:  # noqa: BLE001
            logger.error(f"Error storing response into cache ladder: {e}")
            self._counters["errors"] += 1
            return False

    def schedule_store(
        self,
        query: str,
        scope: CacheScope,
        response_text: str | None,
        *,
        degradation_tier: DegradationTier | str = DegradationTier.TIER_1_PRIMARY,
        tool_calls: list[Any] | None = None,
        truncated: bool = False,
    ) -> asyncio.Task[bool]:
        """Fire-and-forget background task storing response outside hot path."""
        return asyncio.create_task(
            self.store(
                query=query,
                scope=scope,
                response_text=response_text,
                degradation_tier=degradation_tier,
                tool_calls=tool_calls,
                truncated=truncated,
            )
        )

    async def invalidate(self, category: str | None = None) -> int:
        """
        Invalidate cache entries in both Tier 1 and Tier 2.
        Returns total entries cleared.
        """
        t1_count = await self.tier1_backend.clear(category)
        t2_count = await self.semantic_store.invalidate(category)
        logger.info(
            f"Invalidated cache for category='{category}': Tier 1={t1_count}, Tier 2={t2_count}"
        )
        return t1_count + t2_count

    def snapshot(self) -> dict[str, Any]:
        """Return real-time operational telemetry snapshot."""
        return {
            "tier1_size": self.tier1_backend.size(),
            "kb_version": self.kb_version,
            "counters": dict(self._counters),
        }


# ==============================================================================
# Cached Generate Helper
# ==============================================================================


async def cached_generate(
    gateway: ModelGateway,
    cache: CacheLadder,
    messages: list[dict[str, Any]],
    scope: CacheScope,
    temperature: float | None = None,
    max_tokens: int | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> CachedTurnResult:
    """
    Wrap ModelGateway.agenerate(Stage.DIALOGUE) with CacheLadder check.
    If cache hit, bypasses LLM entirely (< 30ms).
    If cache miss, invokes gateway and schedules background store.
    """
    # Extract latest user message as the query
    query = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            query = str(msg.get("content") or "").strip()
            break

    # 1. Cache lookup
    cache_res = await cache.lookup(query, scope)
    if cache_res.hit and cache_res.text:
        return CachedTurnResult(
            text=cache_res.text,
            cache=cache_res,
            gateway=None,
        )

    # 2. Gateway invocation
    gw_res = await gateway.agenerate(
        stage=Stage.DIALOGUE,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        tools=tools,
    )

    # 3. Schedule background store on successful primary/backup response
    if gw_res.success and gw_res.text:
        cache.schedule_store(
            query=query,
            scope=scope,
            response_text=gw_res.text,
            degradation_tier=gw_res.degradation_tier,
            tool_calls=gw_res.tool_calls,
            truncated=gw_res.truncated,
        )

    return CachedTurnResult(
        text=gw_res.text,
        cache=cache_res,
        gateway=gw_res,
    )


# ==============================================================================
# Singleton Factory
# ==============================================================================

_cache_ladder_instance: CacheLadder | None = None


def get_cache_ladder() -> CacheLadder:
    """Return singleton instance of CacheLadder."""
    global _cache_ladder_instance
    if _cache_ladder_instance is None:
        _cache_ladder_instance = CacheLadder()
    return _cache_ladder_instance
