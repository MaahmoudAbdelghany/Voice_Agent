"""
Unit, Integration, and Edge-Case Tests for 3-Tier Caching Ladder (Feature 4.2).

All tests run 100% offline using in-memory Qdrant and scripted fake components.
"""

from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any

import pytest
from pydantic import ValidationError
from qdrant_client import QdrantClient

from src.ai_core.cache import (
    BypassReason,
    CacheabilityPolicy,
    CacheEntry,
    CacheLadder,
    CacheScope,
    CacheTier,
    DefaultOutputValidator,
    InMemoryLRUBackend,
    SemanticCacheStore,
    cached_generate,
)
from src.ai_core.gateway import (
    DegradationTier,
    GatewayResult,
    ModelGateway,
    Stage,
)
from src.config import Settings

# ==============================================================================
# Test Fakes & Utilities
# ==============================================================================


class FakeClock:
    """Injectable monotonic clock for testing TTL and LRU expiry."""

    def __init__(self, start_time: float = 1_000_000.0) -> None:
        self.current_time = start_time

    def time(self) -> float:
        return self.current_time

    def advance(self, seconds: float) -> None:
        self.current_time += seconds


class ScriptedEmbeddingService:
    """Deterministic fake embedding service with controllable vectors and latency."""

    def __init__(
        self,
        dimension: int = 384,
        is_semantic: bool = True,
        delay_s: float = 0.0,
    ) -> None:
        self.dimension = dimension
        self.is_semantic = is_semantic
        self.delay_s = delay_s
        self.vectors: dict[str, list[float]] = {}
        # Default unit vector along axis 0
        self.default_vector = [1.0] + [0.0] * (dimension - 1)

    def set_vector(self, text: str, vector: list[float]) -> None:
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        self.vectors[text] = [x / norm for x in vector]

    def embed_query(self, query: str) -> list[float]:
        if self.delay_s > 0:
            time.sleep(self.delay_s)
        if query in self.vectors:
            return self.vectors[query]
        # Return deterministic hash-based unit vector
        val = sum(ord(c) for c in query) % 360
        angle = math.radians(val)
        vec = [math.cos(angle), math.sin(angle)] + [0.0] * (self.dimension - 2)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


class ScriptedMockGateway(ModelGateway):
    """Simple mock gateway returning scripted GatewayResult."""

    def __init__(
        self,
        return_text: str = "سعر كشف الباطنة 300 جنيه",
        degradation_tier: DegradationTier = DegradationTier.TIER_1_PRIMARY,
        tool_calls: list[dict[str, Any]] | None = None,
        truncated: bool = False,
        success: bool = True,
    ) -> None:
        self.return_text = return_text
        self.degradation_tier = degradation_tier
        self.tool_calls = tool_calls or []
        self.truncated = truncated
        self.success = success
        self.call_count = 0

    async def agenerate(  # type: ignore[override]
        self,
        stage: Stage,
        messages: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> GatewayResult:
        self.call_count += 1
        return GatewayResult(
            success=self.success,
            text=self.return_text,
            tool_calls=self.tool_calls,
            stage=stage,
            provider="mock_groq",
            model="llama-3.3-70b",
            degradation_tier=self.degradation_tier,
            truncated=self.truncated,
        )


def create_test_ladder(
    clock: FakeClock | None = None,
    settings: Settings | None = None,
    tier1_backend: Any | None = None,
    embedder: ScriptedEmbeddingService | None = None,
    output_validator: Any | None = None,
    collection_name: str | None = None,
) -> CacheLadder:
    cl = clock or FakeClock()
    qdrant = QdrantClient(":memory:")
    col_name = collection_name or "test_isolated_cache"
    emb = embedder or ScriptedEmbeddingService()
    sem_store = SemanticCacheStore(client=qdrant, collection_name=col_name, clock=cl.time)
    return CacheLadder(
        settings=settings,
        tier1_backend=tier1_backend,
        semantic_store=sem_store,
        embeddings=emb,  # type: ignore[arg-type]
        output_validator=output_validator,
        clock=cl.time,
    )


# ==============================================================================
# Tier 1: Unit Verification
# ==============================================================================


def test_allowlist_categories():
    policy = CacheabilityPolicy(allowed_categories=["pricing", "insurance", "faqs"])

    # Allowed categories
    ok, reason = policy.allows_query("كم سعر الكشف؟", CacheScope(category="pricing"))
    assert ok is True
    assert reason is None

    # Unlisted category (e.g. doctors, booking_queue)
    ok, reason = policy.allows_query("مواعيد الدكاترة", CacheScope(category="doctors"))
    assert ok is False
    assert reason == BypassReason.CATEGORY_NOT_ALLOWED

    ok, reason = policy.allows_query("عايز أحجز دور", CacheScope(category="booking_queue"))
    assert ok is False
    assert reason == BypassReason.CATEGORY_NOT_ALLOWED


def test_deny_phone_id_digits():
    policy = CacheabilityPolicy()

    # Egyptian mobile
    ok, reason = policy.allows_query("رقمي هو 01012345678 وعايز أعرف مواعيدي")
    assert ok is False
    assert reason == BypassReason.PERSONAL_QUERY

    # 14-digit National ID
    ok, reason = policy.allows_query("الرقم القومي 29801011234567 للتحليل")
    assert ok is False
    assert reason == BypassReason.PERSONAL_QUERY

    # Generic long digit sequence (>= 6 digits)
    ok, reason = policy.allows_query("رقم الحجز 987654 استفسار")
    assert ok is False
    assert reason == BypassReason.PERSONAL_QUERY


def test_deny_personal_words_ar_en():
    policy = CacheabilityPolicy()

    # Arabic personal keywords
    for word in ["ميعادي", "حجزي", "نمرتي", "اسمي", "كشفي", "دوري"]:
        ok, reason = policy.allows_query(f"عايز أعرف {word} امتى")
        assert ok is False, f"Expected personal query bypass for '{word}'"
        assert reason == BypassReason.PERSONAL_QUERY

    # English personal phrases
    for phrase in ["my appointment", "my booking", "my number", "my name"]:
        ok, reason = policy.allows_query(f"Can you tell me {phrase} details?")
        assert ok is False, f"Expected personal query bypass for '{phrase}'"
        assert reason == BypassReason.PERSONAL_QUERY


def test_deny_emergency():
    policy = CacheabilityPolicy()
    ok, reason = policy.allows_query("والدي عنده ألم شديد في الصدر وصعوبة في التنفس")
    assert ok is False
    assert reason == BypassReason.EMERGENCY


def test_response_rules():
    policy = CacheabilityPolicy()

    # Normal public response -> OK
    ok, _ = policy.allows_response(
        response_text="سعر الكشف 300 جنيه شامل الاستشارة خلال 14 يوماً.",
        degradation_tier=DegradationTier.TIER_1_PRIMARY,
    )
    assert ok is True

    # Has tool calls -> Reject
    ok, reason = policy.allows_response(
        response_text="لحظة واحدة أتحقق من الجدول",
        degradation_tier=DegradationTier.TIER_1_PRIMARY,
        tool_calls=[{"name": "check_doctor_availability"}],
    )
    assert ok is False
    assert reason == "contains_tool_calls"

    # Degraded tier (Tier 3 Search-Only or Tier 4 Escalation) -> Reject
    ok, reason = policy.allows_response(
        response_text="مقتطف من دليل العيادة: ...",
        degradation_tier=DegradationTier.TIER_3_SEARCH_ONLY,
    )
    assert ok is False
    assert reason == "degraded_fallback_response"

    ok, reason = policy.allows_response(
        response_text="جاري تحويلك لموظف الاستقبال",
        degradation_tier=DegradationTier.TIER_4_HUMAN_ESCALATION,
    )
    assert ok is False
    assert reason == "degraded_fallback_response"

    # Truncated response -> Reject
    ok, reason = policy.allows_response(
        response_text="سعر الكشف ...",
        degradation_tier=DegradationTier.TIER_1_PRIMARY,
        truncated=True,
    )
    assert ok is False
    assert reason == "response_truncated"

    # Empty response -> Reject
    ok, reason = policy.allows_response(
        response_text="    ",
        degradation_tier=DegradationTier.TIER_1_PRIMARY,
    )
    assert ok is False
    assert reason == "empty_response"

    # Response leaking personal phone number -> Reject
    ok, reason = policy.allows_response(
        response_text="تم تسجيل رقمك 01012345678 بنجاح",
        degradation_tier=DegradationTier.TIER_1_PRIMARY,
    )
    assert ok is False
    assert reason == "contains_personal_identifiers"


def test_validator_rejects_medical_and_discount():
    validator = DefaultOutputValidator()

    # Drug / Prescription words
    assert validator.is_valid("خد بنادول مرتين في اليوم بعد الأكل") is False
    assert validator.is_valid("Take panadol 500mg twice daily") is False
    assert validator.is_valid("الجرعة كبسولة مضاد حيوي كل 8 ساعات") is False

    # Medical diagnosis
    assert validator.is_valid("الأعراض دي تشخيص حالتك أنها التهاب في المعدة") is False
    assert validator.is_valid("You have inflammation in the colon") is False
    assert validator.is_valid("غالباً أنت مصاب بنزلة معوية") is False

    # Unauthorized discounts
    assert validator.is_valid("هعملك خصم خاص لحضرتك 50 جنيه") is False
    assert validator.is_valid("I can give you a special discount for you") is False
    assert validator.is_valid("الكشف هيكون مجاناً عشانك") is False

    # Legitimate clinic fee / info answer -> Pass
    assert (
        validator.is_valid("سعر الكشف في عيادة الباطنة 300 جنيه يا فندم ومواعيدنا يومياً.") is True
    )
    assert validator.is_valid("مواعيد العيادة من السبت إلى الخميس من 9 صباحاً إلى 10 مساءً.") is True


@pytest.mark.asyncio
async def test_lru_ttl_expiry():
    clock = FakeClock(start_time=100.0)
    backend = InMemoryLRUBackend(max_entries=5, clock=clock.time)

    entry = CacheEntry(
        key="k1",
        query_norm="q1",
        text="val1",
        category="pricing",
        language="ar",
        kb_version="v1",
        created_at=100.0,
        expires_at=150.0,  # 50s TTL
    )
    await backend.set("k1", entry, ttl_s=50)

    # Within TTL -> Hit
    clock.advance(30.0)
    assert await backend.get("k1") is not None

    # Past TTL -> Expired
    clock.advance(25.0)
    assert await backend.get("k1") is None
    assert backend.size() == 0


@pytest.mark.asyncio
async def test_lru_evicts_least_recently_used():
    clock = FakeClock()
    backend = InMemoryLRUBackend(max_entries=3, clock=clock.time)

    for i in range(1, 4):
        entry = CacheEntry(
            key=f"k{i}",
            query_norm=f"q{i}",
            text=f"val{i}",
            category="pricing",
            language="ar",
            kb_version="v1",
            created_at=clock.time(),
            expires_at=clock.time() + 1000,
        )
        await backend.set(f"k{i}", entry, ttl_s=1000)

    assert backend.size() == 3

    # Add 4th item; k1 should be evicted as least recently used
    entry4 = CacheEntry(
        key="k4",
        query_norm="q4",
        text="val4",
        category="pricing",
        language="ar",
        kb_version="v1",
        created_at=clock.time(),
        expires_at=clock.time() + 1000,
    )
    await backend.set("k4", entry4, ttl_s=1000)

    assert backend.size() == 3
    assert await backend.get("k1") is None
    assert await backend.get("k2") is not None
    assert await backend.get("k3") is not None
    assert await backend.get("k4") is not None


@pytest.mark.asyncio
async def test_lru_get_refreshes_recency():
    clock = FakeClock()
    backend = InMemoryLRUBackend(max_entries=3, clock=clock.time)

    for i in [1, 2, 3]:
        entry = CacheEntry(
            key=f"k{i}",
            query_norm=f"q{i}",
            text=f"val{i}",
            category="pricing",
            language="ar",
            kb_version="v1",
            created_at=clock.time(),
            expires_at=clock.time() + 1000,
        )
        await backend.set(f"k{i}", entry, ttl_s=1000)

    # Access k1 to make it most recently used
    await backend.get("k1")

    # Add k4; k2 should now be the oldest and evicted!
    entry4 = CacheEntry(
        key="k4",
        query_norm="q4",
        text="val4",
        category="pricing",
        language="ar",
        kb_version="v1",
        created_at=clock.time(),
        expires_at=clock.time() + 1000,
    )
    await backend.set("k4", entry4, ttl_s=1000)

    assert await backend.get("k1") is not None
    assert await backend.get("k2") is None  # Evicted!
    assert await backend.get("k3") is not None
    assert await backend.get("k4") is not None


def test_threshold_validation():
    # Valid threshold
    s_valid = Settings(cache_semantic_threshold=0.97)
    assert s_valid.cache_semantic_threshold == 0.97

    # Too low threshold (< 0.90) fails validation
    with pytest.raises(ValidationError):
        Settings(cache_semantic_threshold=0.85)

    # Invalid category key in TTL dictionary
    with pytest.raises(ValidationError):
        Settings(cache_ttl_by_category={"invalid_category": 3600})

    # Invalid category in allowed list
    with pytest.raises(ValidationError):
        Settings(cache_allowed_categories=["unknown_cat"])


# ==============================================================================
# Tier 2: Integration Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_miss_then_store_then_exact_hit():
    clock = FakeClock()
    embedder = ScriptedEmbeddingService()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(
        client=qdrant, collection_name="test_cache", clock=clock.time
    )

    ladder = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )
    scope = CacheScope(category="pricing", language="ar")

    # 1. Initial Lookup: Miss
    res1 = await ladder.lookup("سعر كشف الباطنة كام؟", scope)
    assert res1.hit is False
    assert res1.tier == CacheTier.MISS

    # 2. Store response
    stored = await ladder.store(
        query="سعر كشف الباطنة كام؟",
        scope=scope,
        response_text="سعر الكشف 300 جنيه يا فندم.",
        degradation_tier=DegradationTier.TIER_1_PRIMARY,
    )
    assert stored is True

    # 3. Subsequent Lookup with spelling variation: Exact Hit
    # Notice Alef and Ta Marbuta variations:
    res2 = await ladder.lookup("سعر كشف الباطنه كام", scope)
    assert res2.hit is True
    assert res2.tier == CacheTier.EXACT
    assert res2.text == "سعر الكشف 300 جنيه يا فندم."
    assert res2.latency_ms < 50.0


@pytest.mark.asyncio
async def test_semantic_hit_above_threshold_and_promotion():
    clock = FakeClock()
    embedder = ScriptedEmbeddingService()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(
        client=qdrant, collection_name="test_semantic_hit", clock=clock.time
    )

    ladder = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )
    scope = CacheScope(category="pricing", language="ar")

    # Base query: vector [1.0, 0.0, ...]
    embedder.set_vector("سعر كشف الاطفال كام", [1.0, 0.0] + [0.0] * 382)
    await ladder.store(
        query="سعر كشف الاطفال كام",
        scope=scope,
        response_text="كشف الأطفال 250 جنيه.",
    )

    # Paraphrased query with cosine similarity ~0.99
    # cos(0.14 rad) ~ 0.99 > 0.97
    embedder.set_vector("بكام كشف دكتور الاطفال", [math.cos(0.14), math.sin(0.14)] + [0.0] * 382)

    res_semantic = await ladder.lookup("بكام كشف دكتور الاطفال", scope)
    assert res_semantic.hit is True
    assert res_semantic.tier == CacheTier.SEMANTIC
    assert res_semantic.similarity is not None and res_semantic.similarity >= 0.97
    assert res_semantic.text == "كشف الأطفال 250 جنيه."

    # Verify Promotion: Subsequent lookup of the paraphrase should now hit Tier 1 Exact!
    res_promoted = await ladder.lookup("بكام كشف دكتور الاطفال", scope)
    assert res_promoted.hit is True
    assert res_promoted.tier == CacheTier.EXACT
    assert res_promoted.text == "كشف الأطفال 250 جنيه."


@pytest.mark.asyncio
async def test_semantic_miss_below_threshold():
    clock = FakeClock()
    embedder = ScriptedEmbeddingService()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(
        client=qdrant, collection_name="test_semantic_miss", clock=clock.time
    )

    ladder = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )
    scope = CacheScope(category="pricing", language="ar")

    embedder.set_vector("سعر كشف الباطنه", [1.0, 0.0] + [0.0] * 382)
    await ladder.store(
        query="سعر كشف الباطنه",
        scope=scope,
        response_text="كشف الباطنة 300 جنيه.",
    )

    # Dissimilar query vector: cos(0.35 rad) ~ 0.939 < 0.97
    embedder.set_vector("سعر كشف الاسنان", [math.cos(0.35), math.sin(0.35)] + [0.0] * 382)

    res = await ladder.lookup("سعر كشف الاسنان", scope)
    assert res.hit is False
    assert res.tier == CacheTier.MISS


@pytest.mark.asyncio
async def test_semantic_category_isolation():
    clock = FakeClock()
    embedder = ScriptedEmbeddingService()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(
        client=qdrant, collection_name="test_cat_iso", clock=clock.time
    )

    ladder = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )

    # Identical vector stored under 'pricing'
    v = [1.0] + [0.0] * 383
    embedder.set_vector("سؤال عام", v)
    await ladder.store(
        query="سؤال عام",
        scope=CacheScope(category="pricing", language="ar"),
        response_text="إجابة الأسعار",
    )

    # Query with identical vector under 'insurance' -> Must MISS
    res = await ladder.lookup(
        query="سؤال عام",
        scope=CacheScope(category="insurance", language="ar"),
    )
    assert res.hit is False
    assert res.tier == CacheTier.MISS


@pytest.mark.asyncio
async def test_language_isolation():
    clock = FakeClock()
    embedder = ScriptedEmbeddingService()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(
        client=qdrant, collection_name="test_lang_iso", clock=clock.time
    )

    ladder = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )

    v = [1.0] + [0.0] * 383
    embedder.set_vector("clinic hours", v)
    embedder.set_vector("مواعيد العيادة", v)

    # Stored in Arabic
    await ladder.store(
        query="مواعيد العيادة",
        scope=CacheScope(category="general", language="ar"),
        response_text="العيادة مفتوحة من 9 صباحاً إلى 10 مساءً.",
    )

    # Query in English with identical vector -> Must MISS
    res = await ladder.lookup(
        query="clinic hours",
        scope=CacheScope(category="general", language="en"),
    )
    assert res.hit is False
    assert res.tier == CacheTier.MISS


@pytest.mark.asyncio
async def test_kb_version_invalidation():
    clock = FakeClock()
    embedder = ScriptedEmbeddingService()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(
        client=qdrant, collection_name="test_kb_inv", clock=clock.time
    )

    ladder1 = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )
    ladder1.kb_version = "version_1111"
    scope = CacheScope(category="pricing", language="ar")

    await ladder1.store(
        query="سعر التحليل",
        scope=scope,
        response_text="سعر التحليل 100 جنيه",
    )
    assert (await ladder1.lookup("سعر التحليل", scope)).hit is True

    # Simulate KB updated: ladder reloaded with new kb_version
    ladder2 = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )
    ladder2.kb_version = "version_2222"

    # Both Tier 1 and Tier 2 must MISS due to kb_version mismatch!
    res = await ladder2.lookup("سعر التحليل", scope)
    assert res.hit is False
    assert res.tier == CacheTier.MISS


@pytest.mark.asyncio
async def test_invalidate_category_and_all():
    clock = FakeClock()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(
        client=qdrant, collection_name="test_inv_cat", clock=clock.time
    )
    ladder = CacheLadder(semantic_store=semantic_store, clock=clock.time)

    await ladder.store(
        query="سعر الكشف",
        scope=CacheScope(category="pricing", language="ar"),
        response_text="300 جنيه",
    )
    await ladder.store(
        query="شركات التامين",
        scope=CacheScope(category="insurance", language="ar"),
        response_text="بوبا وميتلايف",
    )

    assert (await ladder.lookup("سعر الكشف", CacheScope(category="pricing"))).hit is True
    assert (await ladder.lookup("شركات التامين", CacheScope(category="insurance"))).hit is True

    # Invalidate pricing category only
    await ladder.invalidate(category="pricing")

    # Pricing misses; insurance still hits
    assert (await ladder.lookup("سعر الكشف", CacheScope(category="pricing"))).hit is False
    assert (await ladder.lookup("شركات التامين", CacheScope(category="insurance"))).hit is True

    # Invalidate all
    await ladder.invalidate()
    assert (await ladder.lookup("شركات التامين", CacheScope(category="insurance"))).hit is False


@pytest.mark.asyncio
async def test_no_category_skips_tier2():
    clock = FakeClock()
    embedder = ScriptedEmbeddingService()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(
        client=qdrant, collection_name="test_no_cat", clock=clock.time
    )
    ladder = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )

    # Lookup without category
    scope = CacheScope(category=None, language="ar")
    res = await ladder.lookup("مواعيد العمل", scope)
    assert res.hit is False
    assert res.tier == CacheTier.MISS


@pytest.mark.asyncio
async def test_cached_generate_hit_skips_gateway():
    clock = FakeClock()
    ladder = create_test_ladder(clock=clock)
    scope = CacheScope(category="pricing", language="ar")

    # Pre-populate cache
    await ladder.store(
        query="سعر كشف الباطنة",
        scope=scope,
        response_text="سعر الكشف 300 جنيه يا فندم.",
    )

    gw = ScriptedMockGateway()
    messages = [{"role": "user", "content": "سعر كشف الباطنة"}]

    turn_res = await cached_generate(
        gateway=gw,
        cache=ladder,
        messages=messages,
        scope=scope,
    )

    # Gateway should NEVER be called on cache hit!
    assert turn_res.cache.hit is True
    assert turn_res.cache.tier == CacheTier.EXACT
    assert turn_res.text == "سعر الكشف 300 جنيه يا فندم."
    assert gw.call_count == 0
    assert turn_res.gateway is None


@pytest.mark.asyncio
async def test_cached_generate_miss_calls_gateway_and_stores():
    clock = FakeClock()
    ladder = create_test_ladder(clock=clock)
    scope = CacheScope(category="pricing", language="ar")

    gw = ScriptedMockGateway(return_text="سعر كشف الرمد 250 جنيه")
    messages = [{"role": "user", "content": "كم سعر كشف الرمد؟"}]

    turn_res = await cached_generate(
        gateway=gw,
        cache=ladder,
        messages=messages,
        scope=scope,
    )

    assert turn_res.cache.hit is False
    assert gw.call_count == 1
    assert turn_res.text == "سعر كشف الرمد 250 جنيه"
    assert turn_res.gateway is not None

    # Wait briefly for background task to complete storage
    await asyncio.sleep(0.05)

    # Next lookup should be a cache hit!
    lookup_res = await ladder.lookup("كم سعر كشف الرمد؟", scope)
    assert lookup_res.hit is True
    assert lookup_res.tier == CacheTier.EXACT
    assert lookup_res.text == "سعر كشف الرمد 250 جنيه"


@pytest.mark.asyncio
async def test_cached_generate_does_not_store_tier3_or_tool_calls():
    clock = FakeClock()
    ladder = create_test_ladder(clock=clock)
    scope = CacheScope(category="pricing", language="ar")

    # Gateway returned fallback Tier 3
    gw = ScriptedMockGateway(
        return_text="مقتطف من الأرشيف...",
        degradation_tier=DegradationTier.TIER_3_SEARCH_ONLY,
    )
    messages = [{"role": "user", "content": "سؤال صعب"}]

    await cached_generate(
        gateway=gw,
        cache=ladder,
        messages=messages,
        scope=scope,
    )
    await asyncio.sleep(0.05)

    assert (await ladder.lookup("سؤال صعب", scope)).hit is False


@pytest.mark.asyncio
async def test_snapshot_counters():
    clock = FakeClock()
    ladder = create_test_ladder(clock=clock)
    scope = CacheScope(category="pricing", language="ar")

    await ladder.lookup("سؤال 1", scope)  # Miss
    await ladder.store("سؤال 1", scope, "جواب 1")  # Store
    await ladder.lookup("سؤال 1", scope)  # Exact hit
    await ladder.lookup("حجزي ميعاده امتى", scope)  # Bypass (personal)

    snap = ladder.snapshot()
    assert snap["tier1_size"] == 1
    assert snap["counters"]["misses"] == 1
    assert snap["counters"]["tier1_hits"] == 1
    assert snap["counters"]["stores"] == 1
    assert snap["counters"]["bypasses"][BypassReason.PERSONAL_QUERY.value] == 1


@pytest.mark.asyncio
async def test_concurrent_lookups_and_stores():
    clock = FakeClock()
    ladder = create_test_ladder(clock=clock)
    scope = CacheScope(category="pricing", language="ar")

    async def op(idx: int):
        q = f"سؤال تجريبي رقم {idx % 5}"
        res = await ladder.lookup(q, scope)
        if not res.hit:
            await ladder.store(q, scope, f"جواب لسؤال {idx % 5}")

    # Run 50 concurrent async lookups and stores
    await asyncio.gather(*(op(i) for i in range(50)))
    snap = ladder.snapshot()
    assert snap["tier1_size"] <= 5
    assert snap["counters"]["errors"] == 0


# ==============================================================================
# Tier 3: Error & Edge-Case Verification
# ==============================================================================


@pytest.mark.asyncio
async def test_embedding_fallback_disables_tier2():
    clock = FakeClock()
    embedder = ScriptedEmbeddingService(is_semantic=False)
    ladder = CacheLadder(embeddings=embedder, clock=clock.time)  # type: ignore[arg-type]
    scope = CacheScope(category="pricing", language="ar")

    res = await ladder.lookup("سعر الكشف", scope)
    assert res.hit is False
    assert res.tier == CacheTier.MISS
    assert res.bypass_reason == BypassReason.EMBEDDING_FALLBACK


@pytest.mark.asyncio
async def test_semantic_timeout_returns_miss():
    clock = FakeClock()
    # Embedder with delay greater than semantic timeout (50ms)
    embedder = ScriptedEmbeddingService(delay_s=0.2)
    s = Settings(cache_semantic_timeout_ms=50)
    ladder = CacheLadder(settings=s, embeddings=embedder, clock=clock.time)  # type: ignore[arg-type]
    scope = CacheScope(category="pricing", language="ar")

    t0 = time.perf_counter()
    res = await ladder.lookup("سعر الكشف", scope)
    elapsed = time.perf_counter() - t0

    assert res.hit is False
    assert res.tier == CacheTier.MISS
    assert res.bypass_reason == BypassReason.TIMEOUT
    assert elapsed < 0.25  # Bounded by timeout


@pytest.mark.asyncio
async def test_qdrant_error_fail_open():
    clock = FakeClock()
    qdrant = QdrantClient(":memory:")
    semantic_store = SemanticCacheStore(client=qdrant, collection_name="test_err", clock=clock.time)

    # Force search to raise
    async def broken_search(*args, **kwargs):
        raise ConnectionResetError("Qdrant connection dropped")

    semantic_store.search = broken_search  # type: ignore[method-assign]

    embedder = ScriptedEmbeddingService()
    ladder = CacheLadder(
        semantic_store=semantic_store,
        embeddings=embedder,  # type: ignore[arg-type]
        clock=clock.time,
    )
    scope = CacheScope(category="pricing", language="ar")

    # Must return MISS without raising
    res = await ladder.lookup("سعر الكشف", scope)
    assert res.hit is False
    assert res.tier == CacheTier.MISS
    assert res.bypass_reason == BypassReason.BACKEND_ERROR


@pytest.mark.asyncio
async def test_backend_error_fail_open():
    clock = FakeClock()
    backend = InMemoryLRUBackend(clock=clock.time)

    async def broken_get(*args, **kwargs):
        raise RuntimeError("Memory corruption")

    backend.get = broken_get  # type: ignore[method-assign]

    ladder = create_test_ladder(clock=clock, tier1_backend=backend)
    res = await ladder.lookup("سعر الكشف", CacheScope(category="pricing"))
    assert res.hit is False
    assert res.tier == CacheTier.MISS


@pytest.mark.asyncio
async def test_validator_exception_fail_closed():
    class BrokenValidator:
        def is_valid(self, text: str) -> bool:
            raise ValueError("Validator crashed")

    ladder = create_test_ladder(output_validator=BrokenValidator())
    stored = await ladder.store(
        query="سعر الكشف",
        scope=CacheScope(category="pricing"),
        response_text="300 جنيه",
    )
    assert stored is False

    default_v = DefaultOutputValidator()
    assert default_v.is_valid(None) is False  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_empty_and_whitespace_query():
    ladder = create_test_ladder()
    for empty_q in ["", "   ", "   \n\t   "]:
        res = await ladder.lookup(empty_q)
        assert res.hit is False
        assert res.tier == CacheTier.BYPASS
        assert res.bypass_reason == BypassReason.EMPTY_QUERY


@pytest.mark.asyncio
async def test_disabled_switches():
    s = Settings(cache_enabled=False)
    ladder = create_test_ladder(settings=s)

    res = await ladder.lookup("سعر الكشف", CacheScope(category="pricing"))
    assert res.hit is False
    assert res.tier == CacheTier.BYPASS
    assert res.bypass_reason == BypassReason.DISABLED


def test_no_text_in_logs(caplog: pytest.LogCaptureFixture):
    ladder = create_test_ladder()
    with caplog.at_level(logging.DEBUG):
        # Query containing sensitive phone and name
        asyncio.run(
            ladder.lookup(
                "رقمي 01012345678 واسمي محمود",
                CacheScope(category="pricing"),
            )
        )

    # Confirm phone number or query text is NEVER logged
    for record in caplog.records:
        assert "01012345678" not in record.message
        assert "محمود" not in record.message


@pytest.mark.asyncio
async def test_tier1_hit_latency():
    clock = FakeClock()
    ladder = create_test_ladder(clock=clock)
    scope = CacheScope(category="pricing", language="ar")

    await ladder.store("سعر الكشف", scope, "300 جنيه")

    # Execute 100 consecutive hits and measure execution duration
    t0 = time.perf_counter()
    for _ in range(100):
        res = await ladder.lookup("سعر الكشف", scope)
        assert res.hit is True
    avg_lat = ((time.perf_counter() - t0) / 100) * 1000

    # Must be under 5ms
    assert avg_lat < 5.0
