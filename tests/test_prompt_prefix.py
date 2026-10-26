"""
Unit tests for PromptPrefixBuilder (Feature 4.2 Tier 3).
"""

import pytest

from src.ai_core.cache import PromptPrefixBuilder


def test_static_prefix_byte_stable():
    static_instructions = "You are Nour, the polite AI medical receptionist."
    tool_schemas = [{"name": "check_doctor_availability", "description": "Check doctor schedules"}]
    few_shots = [{"user": "سعر الكشف كام؟", "assistant": "سعر الكشف في العيادة 300 جنيه يا فندم."}]

    builder = PromptPrefixBuilder(
        static_instructions=static_instructions,
        tool_schemas=tool_schemas,
        few_shots=few_shots,
    )

    # First build with morning timestamp and caller A
    messages1, hash1 = builder.build(
        dynamic_context="Time: 2026-10-26 09:00 AM | Caller: 01012345678",
        history=[{"role": "user", "content": "أهلاً"}],
    )

    # Second build with evening timestamp and caller B
    messages2, hash2 = builder.build(
        dynamic_context="Time: 2026-10-26 08:30 PM | Caller: 01198765432",
        history=[{"role": "user", "content": "مساء الخير"}],
    )

    # Static prefix hash and content are byte-identical across calls
    assert hash1 == hash2
    assert len(hash1) == 64
    assert messages1[0]["content"] == messages2[0]["content"]


def test_order_static_then_dynamic_then_history():
    builder = PromptPrefixBuilder(
        static_instructions="Static Clinic Persona",
    )

    messages, _ = builder.build(
        dynamic_context="Dynamic Shift Hours",
        history=[
            {"role": "user", "content": "سؤال"},
            {"role": "assistant", "content": "جواب"},
        ],
    )

    assert len(messages) == 4
    assert messages[0]["role"] == "system"
    assert "Static Clinic Persona" in messages[0]["content"]
    assert messages[1]["role"] == "system"
    assert "Dynamic Shift Hours" in messages[1]["content"]
    assert messages[2] == {"role": "user", "content": "سؤال"}
    assert messages[3] == {"role": "assistant", "content": "جواب"}


def test_rejects_placeholder_in_static():
    with pytest.raises(ValueError, match="Static instructions must not contain dynamic"):
        PromptPrefixBuilder(static_instructions="Current time is {current_datetime}. You are Nour.")

    with pytest.raises(ValueError, match="Static instructions must not contain dynamic"):
        PromptPrefixBuilder(static_instructions="The time now is {now}.")


def test_prefix_hash_changes_when_static_changes():
    b1 = PromptPrefixBuilder(static_instructions="Instructions V1")
    b2 = PromptPrefixBuilder(static_instructions="Instructions V2")

    assert b1.prefix_hash != b2.prefix_hash
