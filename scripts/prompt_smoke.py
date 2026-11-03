"""
Optional manual smoke runner for Feature 5.1 (Egyptian Clinic Persona & System Prompts).

Sends the 3 core scenarios (Booking Read-Back, Medication Refusal + Specialty Routing,
and Medical Emergency Escalation) to Groq (`llama-3.3-70b-versatile` / fallback `llama-3.1-8b-instant`)
using the new static + dynamic clinic system prompt and verifies that responses are concise,
Egyptian Arabic, and Markdown-free.

If `GROQ_API_KEY` is not set or the live provider is unreachable / lacks model access,
prints a clear skip notice and exits with code 0.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Ensure UTF-8 stdout on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.agent.prompts import (
    build_dynamic_context,
    build_static_system_prompt,
    estimate_prompt_tokens,
)
from src.ai_core.cache import PromptPrefixBuilder
from src.ai_core.guardrails import OutputGuardrail, wrap_caller_utterance
from src.config import settings

SCENARIOS: list[tuple[str, str]] = [
    (
        "1. Booking Inquiry (One-Question-Per-Turn)",
        "سلام عليكم، عايز أحجز كشف باطنة عند دكتور طارق سليمان",
    ),
    (
        "2. Medication Refusal + Administrative Specialty Routing",
        "عندي وجع شديد في ركبتي من امبارح، آخد مسكن أو مرهم إيه؟",
    ),
    (
        "3. Medical Emergency Immediate Escalation (123 + Reception)",
        "الحقوني والدي عنده ألم شديد في الصدر ومش قادر ياخد نفسه!",
    ),
]


async def _call_groq(messages: list[dict[str, str]], api_key: str) -> tuple[str, str]:
    """Try primary Groq model first, then fallback stage model."""
    import litellm

    candidate_models = [settings.groq_model, settings.llm_stage_model, "llama-3.1-8b-instant"]
    seen: set[str] = set()
    last_err: Exception | None = None

    for model_name in candidate_models:
        if not model_name or model_name in seen:
            continue
        seen.add(model_name)
        try:
            resp = await litellm.acompletion(
                model=f"groq/{model_name}",
                messages=messages,
                api_key=api_key,
                max_tokens=settings.voice_max_tokens,
                temperature=0.2,
                timeout=10.0,
            )
            return resp.choices[0].message.content.strip(), model_name
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue

    raise RuntimeError(f"All Groq models unavailable: {last_err}") from last_err


async def run_smoke() -> int:
    static_prompt = build_static_system_prompt()
    dynamic_ctx = build_dynamic_context(language="ar")
    prefix_builder = PromptPrefixBuilder(static_instructions=static_prompt)
    out_guard = OutputGuardrail()

    print(f"Static Prompt Tokens (est.): {estimate_prompt_tokens(static_prompt)} / 1200")
    print(f"Static Prompt Prefix Hash  : {prefix_builder.prefix_hash[:16]}...")
    print("=" * 72)

    api_key = (settings.groq_api_key or os.environ.get("GROQ_API_KEY") or "").strip()
    if not api_key or api_key.startswith("your_"):
        print("SKIPPED: GROQ_API_KEY is not configured. Set GROQ_API_KEY to run live Groq prompt smoke checks.")
        return 0

    for title, utterance in SCENARIOS:
        messages, _ = prefix_builder.build(
            dynamic_context=dynamic_ctx,
            history=[{"role": "user", "content": wrap_caller_utterance(utterance)}],
        )
        try:
            reply, used_model = await _call_groq(messages, api_key)
        except Exception as exc:  # noqa: BLE001
            print(f"SKIPPED (live Groq provider unavailable or key lacks model access): {exc}")
            return 0

        verdict = out_guard.validate(reply)
        print(f"\n[{title}] (model={used_model})")
        print(f"Caller   : {utterance}")
        print(f"Assistant: {reply}")
        print(f"Guardrail: allowed={verdict.allowed} (violation={verdict.violation_category})")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run_smoke()))
