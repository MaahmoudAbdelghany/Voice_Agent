"""
AI Core Package for Egyptian Polyclinics Voice Agent.

Provides Enterprise Architecture & Resilience Layer:
- Central Model Gateway with LiteLLM provider
- Stage-Based Model Routing
- Circuit Breakers
- 4-Tier Graceful Degradation
- 3-Tier Caching Ladder (Exact Hash, Semantic, Prompt Prefix)
"""

from src.ai_core.cache import (
    BypassReason,
    CacheabilityPolicy,
    CacheBackend,
    CachedTurnResult,
    CacheEntry,
    CacheLadder,
    CacheResult,
    CacheScope,
    CacheTier,
    DefaultOutputValidator,
    InMemoryLRUBackend,
    OutputValidator,
    PromptPrefixBuilder,
    SemanticCacheStore,
    cached_generate,
    get_cache_ladder,
)
from src.ai_core.circuit_breaker import BreakerState, CircuitBreaker
from src.ai_core.gateway import (
    DegradationTier,
    GatewayResult,
    LiteLLMProvider,
    LLMProvider,
    ModelGateway,
    ProviderAttempt,
    Stage,
    classify_error,
    get_gateway,
)
from src.ai_core.text_normalizer import (
    build_exact_key,
    compute_kb_version,
    normalize_query,
)

__all__ = [
    "BreakerState",
    "BypassReason",
    "CacheBackend",
    "CacheEntry",
    "CacheLadder",
    "CacheResult",
    "CacheScope",
    "CacheTier",
    "CacheabilityPolicy",
    "CachedTurnResult",
    "CircuitBreaker",
    "DefaultOutputValidator",
    "DegradationTier",
    "GatewayResult",
    "InMemoryLRUBackend",
    "LLMProvider",
    "LiteLLMProvider",
    "ModelGateway",
    "OutputValidator",
    "PromptPrefixBuilder",
    "ProviderAttempt",
    "SemanticCacheStore",
    "Stage",
    "build_exact_key",
    "cached_generate",
    "classify_error",
    "compute_kb_version",
    "get_cache_ladder",
    "get_gateway",
    "normalize_query",
]
