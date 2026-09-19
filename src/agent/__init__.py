"""
LiveKit Voice Agent Core Package.

Contains prompt templates, session manager, and real-time voice pipeline.
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
    # Prompts & Guidelines
    "DEFAULT_SYSTEM_PROMPT",
    "VOICE_STYLE_GUIDELINES",
    "TOOL_USAGE_GUIDELINES",
    "get_system_prompt",
    "build_greeting_message",
    "build_handoff_message",
    "build_error_fallback_message",
    "build_interruption_acknowledgment",
    # Session Management
    "CallMetrics",
    "CallSession",
    "CallStatus",
    "ExtractedContext",
    "MessageRole",
    "SessionManager",
    "TurnMessage",
    "session_manager",
]

