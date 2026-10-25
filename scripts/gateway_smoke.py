"""
CLI Smoke Test Runner for AI Core Model Gateway (Feature 4.1).

Validates:
1. Live primary generation with Groq Llama 3.3 70B & 3.1 8B.
2. Stage-based deterministic routing.
3. Failover to Google Gemini fallback.
4. Circuit breaker trip detection (5 consecutive failures -> OPEN).
5. 4-tier degradation (Search-only & Receptionist escalation).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from src.ai_core.gateway import (
    LLMProvider,
    ModelGateway,
    Stage,
)
from src.config import get_settings


class FailingMockProvider:
    """Mock provider simulating failures for testing circuit breakers and fallback."""

    def __init__(self, name: str, exc_to_raise: Exception) -> None:
        self.name = name
        self.exc = exc_to_raise

    def is_configured(self) -> bool:
        return True

    async def astream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        tools: list[dict[str, Any]] | None = None,
        ttft_timeout_s: float = 3.5,
        total_timeout_s: float = 10.0,
    ) -> AsyncGenerator[tuple[str | None, list[dict[str, Any]] | None, dict[str, Any]], None]:
        raise self.exc
        yield None, None, {}


async def run_smoke(
    stage_str: str,
    prompt: str,
    simulate_primary_outage: bool = False,
    simulate_total_outage: bool = False,
    repeat: int = 1,
) -> None:
    settings = get_settings()
    stage = Stage(stage_str.lower())

    # Build gateway
    primary_provider: LLMProvider | None = None
    fallback_provider: LLMProvider | None = None

    if simulate_primary_outage or simulate_total_outage:
        import litellm.exceptions

        primary_provider = FailingMockProvider(
            name="groq",
            exc_to_raise=litellm.exceptions.RateLimitError(
                message="Simulated Groq 429 Rate Limit",
                model="llama-3.3-70b-versatile",
                llm_provider="groq",
            ),
        )

    if simulate_total_outage:
        import litellm.exceptions

        fallback_provider = FailingMockProvider(
            name="gemini",
            exc_to_raise=litellm.exceptions.ServiceUnavailableError(
                message="Simulated Gemini 503 Outage",
                model="gemini-2.0-flash",
                llm_provider="gemini",
            ),
        )

    gateway = ModelGateway(
        settings=settings,
        primary_provider=primary_provider,
        fallback_provider=fallback_provider,
    )

    messages = [{"role": "user", "content": prompt}]

    print(f"\n{'=' * 70}")
    print("🚀 Running Model Gateway Smoke Check")
    print(f"   Stage: {stage.value}")
    print(f"   Prompt: '{prompt}'")
    print(f"   Simulate Primary Outage: {simulate_primary_outage}")
    print(f"   Simulate Total Outage: {simulate_total_outage}")
    print(f"   Repetitions: {repeat}")
    print(f"{'=' * 70}\n")

    for i in range(1, repeat + 1):
        print(f"--- [Run {i}/{repeat}] ---")
        primary_state_before = gateway.primary_breaker.state.value

        start_time = asyncio.get_event_loop().time()
        result = await gateway.agenerate(
            stage=stage,
            messages=messages,
        )
        elapsed_s = asyncio.get_event_loop().time() - start_time

        primary_state_after = gateway.primary_breaker.state.value
        fallback_state_after = gateway.fallback_breaker.state.value

        print(f"Outcome: success={result.success}")
        print(f"Tier: {result.degradation_tier.value}")
        print(f"Provider: {result.provider} | Model: {result.model}")
        print(f"Escalate: {result.escalate} | Truncated: {result.truncated}")
        print(f"Tokens: prompt={result.prompt_tokens}, completion={result.completion_tokens}")
        if result.ttft_ms:
            print(f"TTFT: {result.ttft_ms:.1f}ms")
        print(f"Total Latency: {result.latency_ms:.1f}ms (Wall: {elapsed_s * 1000:.1f}ms)")
        print(
            f"Primary Breaker: {primary_state_before} -> {primary_state_after} (consecutive: {gateway.primary_breaker.consecutive_failures})"
        )
        print(f"Fallback Breaker: {fallback_state_after}")

        if result.attempts:
            print("Attempts Log:")
            for att in result.attempts:
                print(
                    f"  * {att.provider} ({att.model}): outcome={att.outcome}, error={att.error_class}"
                )

        print("Generated/Spoken Text:")
        print(f'  "{result.text}"\n')


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Core Model Gateway Smoke Test")
    parser.add_argument(
        "--stage",
        type=str,
        default="dialogue",
        choices=["dialogue", "classification", "extraction"],
        help="Workflow stage",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="مواعيد العيادة إيه؟",
        help="Caller question or utterance",
    )
    parser.add_argument(
        "--simulate-primary-outage",
        action="store_true",
        help="Simulate primary provider failure to verify failover and breaker trip",
    )
    parser.add_argument(
        "--simulate-total-outage",
        action="store_true",
        help="Simulate outage across all LLMs to verify Tier 3/4 degradation",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of times to run request",
    )

    args = parser.parse_args()
    asyncio.run(
        run_smoke(
            stage_str=args.stage,
            prompt=args.prompt,
            simulate_primary_outage=args.simulate_primary_outage,
            simulate_total_outage=args.simulate_total_outage,
            repeat=args.repeat,
        )
    )


if __name__ == "__main__":
    main()
