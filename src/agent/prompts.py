"""
Egyptian Polyclinic Medical Receptionist Persona, System Prompts & Guardrail Directives (Feature 5.1).

Designed for real-time WebRTC voice interactions via LiveKit Agents, Deepgram STT (nova-3),
Groq LLM (Llama 3.3 70B / 3.1 8B), and ElevenLabs TTS (eleven_turbo_v2_5).

Architectural highlights:
- Strict separation between `build_static_system_prompt()` (100% deterministic, zero timestamps,
  compatible with `PromptPrefixBuilder` Tier 3 KV-cache) and `build_dynamic_context()` (Cairo time,
  language, and degradation tier).
- Defense-in-depth medical safety rules aligned with `spec/tech.md` Invariant 3 & OWASP LLM01.
- Single source of truth for deterministic spoken messages via `src/agent/messages.py`.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from src.agent.messages import (
    MEDICAL_SAFETY_REMINDER_AR,
    SYSTEM_UNTRUSTED_DATA_RULES,
    arabic_weekday_name,
    format_emergency_message,
    format_error_fallback_message,
    format_goodbye_message,
    format_greeting_message,
    format_handoff_message,
    format_interruption_acknowledgment,
    format_medical_refusal_message,
    format_out_of_scope_message,
    format_tool_filler_message,
    is_english,
    to_cairo_datetime,
)
from src.config import settings

# Maximum token budget for the static system prompt (NFR-1)
STATIC_PROMPT_MAX_TOKENS: int = 1200

# ==============================================================================
# 1. Static Guideline Blocks (Cache-Stable, Zero Dynamic Placeholders)
# ==============================================================================

VOICE_STYLE_GUIDELINES: str = """## VOICE & STYLE RULES (TTS):
1. Dialect: Default to warm Egyptian Arabic (العامية المصرية المهذبة, e.g., "يا فندم", "حضرتك", "تحت أمرك", "ألف سلامة على حضرتك"). Mirror Modern Standard Arabic or English if the caller uses them.
2. Zero Markdown: NEVER output asterisks, bold/italic, bullets, numbered lists, headers, tables, backticks, or XML tags. Use plain spoken sentences with natural commas and periods.
3. Pacing: Reply in 1 to 3 short sentences. Ask at most ONE question per turn. Offer at most 2 or 3 options at once.
4. Numbers & Time: Speak fees and times naturally ("350 جنيه", "الساعة ستة مساءً"). Read mobile numbers in digit groups ("010 - 1234 - 5678").
5. Barge-In: If interrupted, acknowledge briefly and answer the new point without repeating prior text."""

MEDICAL_SAFETY_GUIDELINES: str = """## MEDICAL SAFETY GUARDRAILS (STRICT INVARIANT):
1. Zero Diagnosis, Drugs, or Reassurance: NEVER diagnose conditions, name diseases, recommend medications or dosages, interpret lab results, or give medical reassurance. Refuse medical advice politely and offer to book the specialist or transfer to reception.
2. Administrative Specialty Routing Only: If a caller mentions non-emergency symptoms and asks who to book, suggest the clinic specialty for booking only, stating that the doctor will examine and assess the case (e.g., "ممكن حضرتك تحجز كشف عند دكتور العظام وهو يفحص ويقيّم الحالة بدقة").
3. Emergency Escalation: On life-threatening symptoms (chest pain, shortness of breath, heavy bleeding, fainting, stroke, poisoning), immediately instruct the caller to dial ambulance {emergency_phone} or go to the nearest ER, and immediately call `transfer_to_receptionist` with emergency urgency.
4. Strict Fact Grounding: Fees, test prep rules (fasting), insurance, doctor credentials, shifts, and queue numbers MUST come strictly from tool outputs. Never guess."""

TOOL_USAGE_GUIDELINES: str = """## CLINIC TOOLS & WRITE CONFIRMATION PROTOCOL:
1. `check_doctor_availability`: Query doctors, specialties, shifts, slots, and examination/consultation fees.
2. `book_appointment`: Reserve a queue slot (`نمرة الحجز`) only after collecting and confirming all fields.
3. `manage_appointment`: Look up, reschedule, or cancel an appointment by phone number or booking code.
4. `search_clinic_knowledge`: Retrieve clinic policies, lab/scan prep, accepted insurance, address, and services.
5. `transfer_to_receptionist`: Escalate immediately on human request, frustration, billing dispute, or emergency.
6. Pre-Write Confirmation: Collect missing fields ONE question per turn (doctor/specialty, day/date, shift, visit type `كشف جديد` vs `استشارة`, full name, mobile). Before `book_appointment` or cancel/reschedule in `manage_appointment`, read back doctor, day, shift, visit type, name, and mobile in digit groups, and wait for explicit caller confirmation ("أيوه", "تمام", "yes"). NEVER state a queue number (`نمرة الحجز`) or fee before the tool returns it."""

FEW_SHOT_EXAMPLES: str = """## EXAMPLES:
Example 1 (Booking Read-Back):
Caller: <caller_utterance>اسمي أحمد محمود ورقمي 01012345678، كشف جديد</caller_utterance>
Assistant: تمام يا أستاذ أحمد، للتأكيد قبل التسجيل، كشف جديد مع دكتور طارق سليمان باطنة يوم السبت شيفت المساء، باسم أحمد محمود، والموبايل 010 - 1234 - 5678. أسجل الحجز لحضرتك؟

Example 2 (Medication Refusal & Specialty Routing):
Caller: <caller_utterance>عندي وجع في ركبتي، آخد مسكن إيه؟</caller_utterance>
Assistant: ألف سلامة على حضرتك يا فندم. حرصاً على سلامتك مش بقدر أوصف أدوية أو تشخيص، لكن ممكن حضرتك تحجز كشف عند دكتور العظام وهو يفحص ويقيّم الحالة. تحب أشوف مواعيد دكتور العظام؟

Example 3 (Emergency Escalation):
Caller: <caller_utterance>والدي عنده ألم شديد في الصدر ومش قادر يتنفس</caller_utterance>
Assistant: سلامته يا فندم، الحالة طارئة، أرجوك اتصل بالإسعاف فوراً على رقم {emergency_phone} أو اتجه لأقرب طوارئ، وهحول حضرتك حالاً للاستقبال. [calls transfer_to_receptionist(urgency="emergency", department="emergency")]"""

STATIC_SYSTEM_PROMPT_TEMPLATE: str = """You are {agent_name}, the polite Voice AI Medical Receptionist for {clinic_name} ({clinic_tagline}), handling patient calls for an Egyptian polyclinic.

## CLINIC DIRECTORY:
- Assistant: {agent_name} | Clinic: {clinic_name} ({clinic_tagline})
- Address: {clinic_address} | Phone: {clinic_phone}
- Hours: {clinic_working_hours} | Emergency: {emergency_phone}

{voice_style}

{medical_safety}

{tool_usage}

{untrusted_data_rules}

{few_shots}"""


# ==============================================================================
# 2. Static & Dynamic Prompt Builders (Tier 3 Prefix-Cache Ready)
# ==============================================================================


def estimate_prompt_tokens(text: str) -> int:
    """
    Deterministic token count estimator for mixed English/Arabic prompts (~4 chars/token
    with word-count floor) used to enforce the <= 1,200 static token budget without external I/O.
    """
    if not text:
        return 0
    char_estimate = math.ceil(len(text) / 4.0)
    word_estimate = math.ceil(len(text.split()) * 1.3)
    return max(char_estimate, word_estimate)


def build_static_system_prompt(
    clinic_name: str | None = None,
    clinic_tagline: str | None = None,
    agent_name: str | None = None,
    clinic_phone: str | None = None,
    clinic_address: str | None = None,
    clinic_working_hours: str | None = None,
    emergency_phone: str | None = None,
) -> str:
    """
    Build the 100% static, deterministic clinic system prompt prefix.

    Contains ZERO dates, timestamps, caller data, or degradation state so that
    `PromptPrefixBuilder` produces an identical `prefix_hash` across turns and calls.
    """
    c_name = clinic_name or settings.clinic_name
    c_tagline = clinic_tagline or settings.clinic_tagline
    a_name = agent_name or settings.agent_name
    c_phone = clinic_phone or settings.clinic_phone
    c_addr = clinic_address or settings.clinic_address
    c_hours = clinic_working_hours or settings.clinic_working_hours
    em_phone = emergency_phone or settings.emergency_phone

    medical_safety = MEDICAL_SAFETY_GUIDELINES.format(emergency_phone=em_phone)
    few_shots = FEW_SHOT_EXAMPLES.format(emergency_phone=em_phone)

    return STATIC_SYSTEM_PROMPT_TEMPLATE.format(
        agent_name=a_name,
        clinic_name=c_name,
        clinic_tagline=c_tagline,
        clinic_address=c_addr,
        clinic_phone=c_phone,
        clinic_working_hours=c_hours,
        emergency_phone=em_phone,
        voice_style=VOICE_STYLE_GUIDELINES,
        medical_safety=medical_safety,
        tool_usage=TOOL_USAGE_GUIDELINES,
        untrusted_data_rules=SYSTEM_UNTRUSTED_DATA_RULES,
        few_shots=few_shots,
    ).strip()


def _normalize_degradation_tier(degradation_tier: Any) -> str:
    """Normalize a `DegradationTier` enum or string to its canonical uppercase name."""
    if degradation_tier is None:
        return ""
    val = getattr(degradation_tier, "value", degradation_tier)
    if not isinstance(val, str):
        return ""
    return val.strip().upper()


def build_dynamic_context(
    language: str = "ar",
    degradation_tier: Any = None,
    now: datetime | None = None,
    custom_instructions: str | None = None,
) -> str:
    """
    Build the per-call / per-turn dynamic context block containing:
    - Current Cairo date, Arabic weekday name, and 24-hour time (`Africa/Cairo`).
    - Preferred caller conversation language (`ar` vs `en`).
    - Operational degradation directive when in `TIER_3_SEARCH_ONLY` or `TIER_4_HUMAN_ESCALATION`.
    - Optional custom operational instructions.
    """
    cairo_now = to_cairo_datetime(now)
    date_str = cairo_now.strftime("%Y-%m-%d")
    time_str = cairo_now.strftime("%H:%M")
    weekday_en = cairo_now.strftime("%A")
    weekday_ar = arabic_weekday_name(cairo_now)

    lang_line = (
        "Preferred Caller Language: English (respond in fluent, polite, warm English)."
        if is_english(language)
        else "Preferred Caller Language: Arabic (تحدث بالعامية المصرية المهذبة والمرحبة)."
    )

    lines = [
        f"Current Cairo Date & Time: {date_str} ({weekday_en} / {weekday_ar}) {time_str} Africa/Cairo",
        lang_line,
    ]

    tier_name = _normalize_degradation_tier(degradation_tier)
    if tier_name == "TIER_3_SEARCH_ONLY":
        lines.append(
            "Operational Status (TIER_3_SEARCH_ONLY): Automated appointment booking and modifications are "
            "temporarily unavailable. Provide clinic, doctor, and fee information only, and offer to "
            "transfer the caller to the human receptionist for booking."
        )
    elif tier_name == "TIER_4_HUMAN_ESCALATION":
        lines.append(
            "Operational Status (TIER_4_HUMAN_ESCALATION): Automated assistant turn budget or service capacity "
            "is exhausted. Politely wrap up the conversation in one short sentence and transfer the caller "
            "to the human receptionist immediately."
        )

    if custom_instructions and custom_instructions.strip():
        lines.append(f"Additional Operational Instructions: {custom_instructions.strip()}")

    return "\n".join(lines)


def get_system_prompt(
    custom_instructions: str | None = None,
    language: str = "ar",
    degradation_tier: Any = None,
    now: datetime | None = None,
    clinic_name: str | None = None,
    clinic_tagline: str | None = None,
    agent_name: str | None = None,
    clinic_phone: str | None = None,
    clinic_address: str | None = None,
    clinic_working_hours: str | None = None,
    emergency_phone: str | None = None,
) -> str:
    """
    Assemble the complete system prompt for LiveKit `Agent(instructions=...)` by
    combining the cache-stable static prompt prefix with the dynamic call context.
    """
    static_block = build_static_system_prompt(
        clinic_name=clinic_name,
        clinic_tagline=clinic_tagline,
        agent_name=agent_name,
        clinic_phone=clinic_phone,
        clinic_address=clinic_address,
        clinic_working_hours=clinic_working_hours,
        emergency_phone=emergency_phone,
    )
    dynamic_block = build_dynamic_context(
        language=language,
        degradation_tier=degradation_tier,
        now=now,
        custom_instructions=custom_instructions,
    )
    return f"{static_block}\n\n## DYNAMIC CALL CONTEXT:\n{dynamic_block}"


# Default static system prompt constant for modules expecting a static string export
DEFAULT_SYSTEM_PROMPT: str = build_static_system_prompt()


# ==============================================================================
# 3. Deterministic Spoken Message Builders (Settings-Aware Wrappers)
# ==============================================================================


def build_greeting_message(
    clinic_name: str | None = None,
    agent_name: str | None = None,
    language: str = "ar",
    now: datetime | None = None,
) -> str:
    """Construct the initial spoken greeting using Cairo time of day and clinic identity."""
    return format_greeting_message(
        clinic_name=clinic_name or settings.clinic_name,
        agent_name=agent_name or settings.agent_name,
        language=language,
        now=now,
    )


def build_handoff_message(
    department_name: str | None = None,
    estimated_wait_seconds: int | None = None,
    language: str = "ar",
) -> str:
    """Construct the spoken message before transferring the caller to a human receptionist."""
    return format_handoff_message(
        department_name=department_name,
        estimated_wait_seconds=estimated_wait_seconds,
        language=language,
    )


def build_error_fallback_message(language: str = "ar") -> str:
    """Construct a polite verbal fallback if a tool or service call fails or times out."""
    return format_error_fallback_message(language=language)


def build_tool_filler_message(
    tool_name: str | None = None,
    language: str = "ar",
) -> str:
    """Construct a conversational filler when a tool call exceeds the 400ms latency threshold."""
    return format_tool_filler_message(tool_name=tool_name, language=language)


def build_emergency_message(
    emergency_phone: str | None = None,
    language: str = "ar",
) -> str:
    """Construct the deterministic emergency escalation message with ambulance hotline (`123`)."""
    return format_emergency_message(
        emergency_phone=emergency_phone or settings.emergency_phone,
        language=language,
    )


def build_out_of_scope_message(
    clinic_name: str | None = None,
    language: str = "ar",
) -> str:
    """Construct the polite out-of-scope / prompt-injection refusal message."""
    return format_out_of_scope_message(
        clinic_name=clinic_name or settings.clinic_name,
        language=language,
    )


def build_medical_refusal_message(language: str = "ar") -> str:
    """Construct the polite medical diagnosis / medication refusal message."""
    return format_medical_refusal_message(language=language)


def build_goodbye_message(
    clinic_name: str | None = None,
    language: str = "ar",
) -> str:
    """Construct the polite call-closing message."""
    return format_goodbye_message(
        clinic_name=clinic_name or settings.clinic_name,
        language=language,
    )


def build_interruption_acknowledgment(language: str = "ar") -> str:
    """Short verbal filler acknowledgment when the caller interrupts (barge-in)."""
    return format_interruption_acknowledgment(language=language)


__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "FEW_SHOT_EXAMPLES",
    "MEDICAL_SAFETY_GUIDELINES",
    "MEDICAL_SAFETY_REMINDER_AR",
    "STATIC_PROMPT_MAX_TOKENS",
    "STATIC_SYSTEM_PROMPT_TEMPLATE",
    "SYSTEM_UNTRUSTED_DATA_RULES",
    "TOOL_USAGE_GUIDELINES",
    "VOICE_STYLE_GUIDELINES",
    "build_dynamic_context",
    "build_emergency_message",
    "build_error_fallback_message",
    "build_goodbye_message",
    "build_greeting_message",
    "build_handoff_message",
    "build_interruption_acknowledgment",
    "build_medical_refusal_message",
    "build_out_of_scope_message",
    "build_static_system_prompt",
    "build_tool_filler_message",
    "estimate_prompt_tokens",
    "get_system_prompt",
]
