"""
AI Core Package for Egyptian Polyclinics Voice Agent.

Provides Enterprise Architecture & Resilience Layer:
- Central Model Gateway with LiteLLM provider
- Stage-Based Model Routing
- Circuit Breakers
- 4-Tier Graceful Degradation
"""

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

__all__ = [
    "BreakerState",
    "CircuitBreaker",
    "DegradationTier",
    "GatewayResult",
    "LLMProvider",
    "LiteLLMProvider",
    "ModelGateway",
    "ProviderAttempt",
    "Stage",
    "classify_error",
    "get_gateway",
]
