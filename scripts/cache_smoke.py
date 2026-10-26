"""
Smoke Test CLI Script for 3-Tier Caching Ladder (Feature 4.2).

Demonstrates:
1. Cold query miss -> Store into Cache.
2. Normalized repeat query -> Instant Tier 1 Exact Hit (< 5ms).
3. Paraphrased query -> Tier 2 Semantic Hit (>= 0.97) + Promotion.
4. Policy bypasses: Personal data, Emergency symptoms, Disallowed categories.
5. Telemetry counters snapshot.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time

from src.ai_core.cache import (
    CacheScope,
    CacheTier,
    cached_generate,
    get_cache_ladder,
)
from src.ai_core.gateway import DegradationTier, get_gateway
from src.config import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cache_smoke")


async def run_offline_smoke() -> None:
    print("=" * 70)
    print(" 🏥 Egyptian Polyclinic 3-Tier Caching Ladder — Smoke Verification")
    print("=" * 70)

    ladder = get_cache_ladder()
    scope = CacheScope(category="pricing", language="ar")

    # Step 1: Initial Cold Query (Expected: MISS)
    query1 = "سعر كشف الأطفال كام؟"
    print(f"\n[1] Cold Lookup: '{query1}' (category='{scope.category}')")
    t0 = time.perf_counter()
    res1 = await ladder.lookup(query1, scope)
    lat1 = (time.perf_counter() - t0) * 1000
    print(f"    -> Hit: {res1.hit} | Tier: {res1.tier.value} | Latency: {lat1:.2f}ms")
    assert not res1.hit, "Cold query should miss"

    # Step 2: Store public answer
    response1 = "سعر الكشف في عيادة الأطفال 250 جنيه شامل الاستشارة خلال أسبوعين."
    print(f"\n[2] Storing Answer: '{response1}'")
    stored = await ladder.store(
        query=query1,
        scope=scope,
        response_text=response1,
        degradation_tier=DegradationTier.TIER_1_PRIMARY,
    )
    print(f"    -> Store Success: {stored}")
    assert stored, "Store should succeed"

    # Step 3: Exact Normalized Lookup with punctuation and Alef differences (Expected: Tier 1 Hit)
    query2 = "سعر كشف الاطفال كام"  # Without hamza, question mark
    print(f"\n[3] Normalized Lookup: '{query2}'")
    t0 = time.perf_counter()
    res2 = await ladder.lookup(query2, scope)
    lat2 = (time.perf_counter() - t0) * 1000
    print(
        f"    -> Hit: {res2.hit} | Tier: {res2.tier.value} | Latency: {lat2:.2f}ms | Text: '{res2.text}'"
    )
    assert res2.hit and res2.tier == CacheTier.EXACT, "Expected Tier 1 Exact Hit"

    # Step 4: Paraphrased Query (Expected: Tier 2 Semantic Hit if >= 0.97 threshold)
    query3 = "بكام كشف دكتور الأطفال؟"
    print(f"\n[4] Paraphrase Lookup: '{query3}'")
    t0 = time.perf_counter()
    res3 = await ladder.lookup(query3, scope)
    lat3 = (time.perf_counter() - t0) * 1000
    print(
        f"    -> Hit: {res3.hit} | Tier: {res3.tier.value} | Similarity: {res3.similarity} | Latency: {lat3:.2f}ms"
    )

    # Step 5: Policy Bypasses
    print("\n[5] Verifying Cacheability Policy Bypasses:")

    # 5a. Personal query bypass
    p_q = "عايز أعرف ميعادي امتى ورقمي 01012345678"
    p_res = await ladder.lookup(p_q, scope)
    print(f"    -> Personal Query: '{p_q}' -> Bypass: {p_res.bypass_reason.value}")
    assert p_res.tier == CacheTier.BYPASS

    # 5b. Emergency bypass
    e_q = "عندي ألم شديد في صدري وصعوبة تنفس"
    e_res = await ladder.lookup(e_q, scope)
    print(f"    -> Emergency Query: '{e_q}' -> Bypass: {e_res.bypass_reason.value}")
    assert e_res.tier == CacheTier.BYPASS

    # 5c. Disallowed category (doctors)
    d_q = "مين دكتور الباطنة النهاردة؟"
    d_scope = CacheScope(category="doctors", language="ar")
    d_res = await ladder.lookup(d_q, d_scope)
    print(f"    -> Disallowed Category: category='doctors' -> Bypass: {d_res.bypass_reason.value}")
    assert d_res.tier == CacheTier.BYPASS

    # Step 6: Telemetry Snapshot
    print("\n[6] Real-time Telemetry Snapshot:")
    snap = ladder.snapshot()
    print(f"    Tier 1 LRU Entries: {snap['tier1_size']}")
    print(f"    KB Version: {snap['kb_version']}")
    print(f"    Counters: {snap['counters']}")

    print("\n" + "=" * 70)
    print(" ✅ Cache Smoke Verification Completed Successfully!")
    print("=" * 70)


async def run_live_smoke(prompt: str, category: str) -> None:
    print("=" * 70)
    print(f" 🚀 Live Gateway + Cache Integration Test: '{prompt}' (category='{category}')")
    print("=" * 70)

    if not settings.is_llm_configured():
        print("❌ Groq API key is not configured. Live test requires GROQ_API_KEY in .env.")
        sys.exit(1)

    gw = get_gateway()
    ladder = get_cache_ladder()
    scope = CacheScope(category=category, language="ar")
    messages = [{"role": "user", "content": prompt}]

    # Turn 1: Cold call (Cache MISS -> LLM Gateway -> TTS -> Background Store)
    print("\n[Turn 1] Cold Invocation (expecting Cache MISS -> Gateway invocation)...")
    t0 = time.perf_counter()
    turn1 = await cached_generate(gw, ladder, messages, scope)
    lat1 = (time.perf_counter() - t0) * 1000
    print(f"    Cache Hit: {turn1.cache.hit} | Tier: {turn1.cache.tier.value}")
    print(f"    Gateway Provider: {turn1.gateway.provider if turn1.gateway else 'N/A'}")
    print(f"    Total Latency: {lat1:.2f}ms")
    print(f"    Spoken Response: '{turn1.text}'")

    # Wait for background storage task
    await asyncio.sleep(0.5)

    # Turn 2: Warm call (Cache EXACT HIT -> Instant return < 5ms)
    print("\n[Turn 2] Warm Repeat (expecting Cache HIT -> Zero LLM tokens)...")
    t0 = time.perf_counter()
    turn2 = await cached_generate(gw, ladder, messages, scope)
    lat2 = (time.perf_counter() - t0) * 1000
    print(f"    Cache Hit: {turn2.cache.hit} | Tier: {turn2.cache.tier.value}")
    print(f"    Gateway Called: {'NO (Bypassed!)' if turn2.gateway is None else 'YES'}")
    print(f"    Total Latency: {lat2:.2f}ms")
    print(f"    Spoken Response: '{turn2.text}'")

    print("\n" + "=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Cache Smoke Verification")
    parser.add_argument("--live", action="store_true", help="Run live integration test with LLM")
    parser.add_argument("--prompt", type=str, default="مواعيد العيادة إيه؟", help="User prompt")
    parser.add_argument("--category", type=str, default="general", help="Category filter")

    args = parser.parse_args()
    if args.live:
        asyncio.run(run_live_smoke(args.prompt, args.category))
    else:
        asyncio.run(run_offline_smoke())


if __name__ == "__main__":
    main()
