"""
Unit tests for Voice Agent Prompts and Conversational Guidelines.
"""

from src.agent.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    VOICE_STYLE_GUIDELINES,
    TOOL_USAGE_GUIDELINES,
    get_system_prompt,
    build_greeting_message,
    build_handoff_message,
    build_error_fallback_message,
    build_interruption_acknowledgment,
)
from src.config import settings


def test_default_system_prompt():
    """Verify default system prompt contains core persona, rules, and placeholders."""
    assert settings.agent_name in DEFAULT_SYSTEM_PROMPT
    assert settings.restaurant_name in DEFAULT_SYSTEM_PROMPT
    assert "search_restaurant_knowledge" in DEFAULT_SYSTEM_PROMPT
    assert "get_order_status" in DEFAULT_SYSTEM_PROMPT
    assert "book_reservation" in DEFAULT_SYSTEM_PROMPT
    assert "escalate_to_human" in DEFAULT_SYSTEM_PROMPT
    assert "Never Use Markdown Syntax" in DEFAULT_SYSTEM_PROMPT


def test_get_system_prompt_custom():
    """Verify dynamic system prompt customization."""
    custom_prompt = get_system_prompt(
        restaurant_name="Al-Sham Gourmet",
        agent_name="Layla",
        restaurant_phone="+20 100 000 0000",
        restaurant_address="Zamalek, Cairo",
        restaurant_hours="10 AM - 12 AM",
        custom_instructions="Mention the 20% weekend discount on shawarma.",
        language="ar",
    )

    assert "Al-Sham Gourmet" in custom_prompt
    assert "Layla" in custom_prompt
    assert "+20 100 000 0000" in custom_prompt
    assert "Zamalek, Cairo" in custom_prompt
    assert "Mention the 20% weekend discount on shawarma." in custom_prompt
    assert "تحدث بلغة عربية عامية مهذبة ومرحبة جداً" in custom_prompt


def test_get_system_prompt_english():
    """Verify dynamic system prompt with English instructions."""
    english_prompt = get_system_prompt(language="en")
    assert "Speak in fluent, polite, and warm English." in english_prompt


def test_build_greeting_message():
    """Verify greetings in both Arabic and English."""
    ar_greeting = build_greeting_message(restaurant_name="مطعمنا", agent_name="سامي", language="ar")
    assert "مطعمنا" in ar_greeting
    assert "سامي" in ar_greeting
    assert "أقدر أساعدك بإيه النهاردة؟" in ar_greeting

    en_greeting = build_greeting_message(restaurant_name="Syrian House", agent_name="Sami", language="en")
    assert "Syrian House" in en_greeting
    assert "Sami" in en_greeting
    assert "How can I help you today?" in en_greeting


def test_build_handoff_message():
    """Verify escalation handoff messages."""
    ar_handoff = build_handoff_message(department_name="قسم المطبخ", estimated_wait_seconds=45, language="ar")
    assert "قسم المطبخ" in ar_handoff
    assert "45 ثانية" in ar_handoff

    en_handoff = build_handoff_message(department_name="Kitchen Manager", estimated_wait_seconds=30, language="en")
    assert "Kitchen Manager" in en_handoff
    assert "30 seconds" in en_handoff


def test_build_fallback_and_acknowledgments():
    """Verify verbal error fallbacks and interruption acknowledgments."""
    ar_fallback = build_error_fallback_message(language="ar")
    assert "بعتذر لحضرتك" in ar_fallback

    en_fallback = build_error_fallback_message(language="en")
    assert "apologize" in en_fallback

    ar_ack = build_interruption_acknowledgment(language="ar")
    assert "تمام يا فندم" in ar_ack

    en_ack = build_interruption_acknowledgment(language="en")
    assert "Understood" in en_ack
