"""
LiveKit Voice Agent Core Package.

Contains prompt templates, deterministic clinic messages, session manager, and real-time voice pipeline.
"""

from src.agent.messages import (
    MEDICAL_SAFETY_REMINDER_AR,
    SYSTEM_UNTRUSTED_DATA_RULES,
)
from src.agent.prompts import (
    DEFAULT_SYSTEM_PROMPT,
    FEW_SHOT_EXAMPLES,
    MEDICAL_SAFETY_GUIDELINES,
    STATIC_PROMPT_MAX_TOKENS,
    TOOL_USAGE_GUIDELINES,
    VOICE_STYLE_GUIDELINES,
    build_dynamic_context,
    build_emergency_message,
    build_error_fallback_message,
    build_goodbye_message,
    build_greeting_message,
    build_handoff_message,
    build_interruption_acknowledgment,
    build_medical_refusal_message,
    build_out_of_scope_message,
    build_static_system_prompt,
    build_tool_filler_message,
    estimate_prompt_tokens,
    get_system_prompt,
)
from src.agent.session_manager import (
    CallMetrics,
    CallSession,
    CallStatus,
    ExtractedContext,
    MessageRole,
    SessionManager,
    TurnMessage,
    session_manager,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "FEW_SHOT_EXAMPLES",
    "MEDICAL_SAFETY_GUIDELINES",
    "MEDICAL_SAFETY_REMINDER_AR",
    "STATIC_PROMPT_MAX_TOKENS",
    "SYSTEM_UNTRUSTED_DATA_RULES",
    "TOOL_USAGE_GUIDELINES",
    "VOICE_STYLE_GUIDELINES",
    "CallMetrics",
    "CallSession",
    "CallStatus",
    "ExtractedContext",
    "MessageRole",
    "SessionManager",
    "TurnMessage",
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
    "session_manager",
]
