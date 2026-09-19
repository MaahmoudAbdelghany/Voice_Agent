"""
Call Session State, Turn Memory, and Context Tracking for Voice AI Agent.

Provides thread-safe session lifecycle management, sliding-window conversational memory,
extracted entity tracking (order IDs, reservations, allergies, sentiment),
latency/interruption metrics, and JSON persistence for the Streamlit dashboard.
"""

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
import json
import logging
import threading
from typing import Any, Dict, List, Optional, Union
import uuid

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ==============================================================================
# Enums and Data Models
# ==============================================================================

class CallStatus(str, Enum):
    """Lifecycle status of a live voice call."""
    INITIATED = "initiated"
    ACTIVE = "active"
    SPEAKING = "speaking"
    LISTENING = "listening"
    TOOL_CALLING = "tool_calling"
    ESCALATED = "escalated"
    ENDED = "ended"


class MessageRole(str, Enum):
    """Role of a message participant in the conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TurnMessage(BaseModel):
    """A single turn or message within a voice conversation."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tool_name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_arguments: Optional[Dict[str, Any]] = None
    tool_result: Optional[Dict[str, Any]] = None
    latency_ms: Optional[float] = None
    stt_latency_ms: Optional[float] = None
    llm_latency_ms: Optional[float] = None
    tts_latency_ms: Optional[float] = None
    interrupted: bool = False

    def to_openai_format(self) -> Dict[str, Any]:
        """Convert message to OpenAI / Groq chat completion format."""
        msg: Dict[str, Any] = {
            "role": self.role.value,
            "content": self.content,
        }
        if self.tool_name and self.role == MessageRole.TOOL:
            msg["name"] = self.tool_name
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


class ExtractedContext(BaseModel):
    """Extracted business context, entities, and slots gathered across turns."""
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    language: str = "ar"
    order_id: Optional[str] = None
    reservation_draft: Dict[str, Any] = Field(default_factory=dict)
    dietary_preferences: List[str] = Field(default_factory=list)
    allergies: List[str] = Field(default_factory=list)
    sentiment: str = "neutral"
    escalated: bool = False
    escalation_reason: Optional[str] = None
    escalation_department: Optional[str] = None
    custom_notes: Dict[str, Any] = Field(default_factory=dict)


class CallMetrics(BaseModel):
    """Real-time performance and operational metrics for a voice session."""
    total_user_turns: int = 0
    total_assistant_turns: int = 0
    total_tool_calls: int = 0
    total_interruptions: int = 0
    total_latency_ms: float = 0.0
    measured_latency_turns: int = 0
    average_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    duration_seconds: float = 0.0


# ==============================================================================
# Single Call Session Representation
# ==============================================================================

class CallSession(BaseModel):
    """State, memory, and analytics for an individual voice call session."""
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    room_name: str = ""
    participant_identity: str = ""
    status: CallStatus = CallStatus.INITIATED
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    context: ExtractedContext = Field(default_factory=ExtractedContext)
    metrics: CallMetrics = Field(default_factory=CallMetrics)
    messages: List[TurnMessage] = Field(default_factory=list)

    def add_turn(
        self,
        role: MessageRole,
        content: str,
        tool_name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        tool_arguments: Optional[Dict[str, Any]] = None,
        tool_result: Optional[Dict[str, Any]] = None,
        latency_ms: Optional[float] = None,
        stt_latency_ms: Optional[float] = None,
        llm_latency_ms: Optional[float] = None,
        tts_latency_ms: Optional[float] = None,
        interrupted: bool = False,
    ) -> TurnMessage:
        """Add a conversation turn and update call metrics."""
        msg = TurnMessage(
            role=role,
            content=content,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_arguments=tool_arguments,
            tool_result=tool_result,
            latency_ms=latency_ms,
            stt_latency_ms=stt_latency_ms,
            llm_latency_ms=llm_latency_ms,
            tts_latency_ms=tts_latency_ms,
            interrupted=interrupted,
        )
        self.messages.append(msg)

        # Update metrics
        if role == MessageRole.USER:
            self.metrics.total_user_turns += 1
            if self.status != CallStatus.ENDED:
                self.status = CallStatus.ACTIVE
        elif role == MessageRole.ASSISTANT:
            self.metrics.total_assistant_turns += 1
        elif role == MessageRole.TOOL:
            self.metrics.total_tool_calls += 1

        if interrupted:
            self.metrics.total_interruptions += 1

        if latency_ms and latency_ms > 0:
            self.metrics.total_latency_ms += latency_ms
            self.metrics.measured_latency_turns += 1
            self.metrics.average_latency_ms = (
                self.metrics.total_latency_ms / self.metrics.measured_latency_turns
            )
            if latency_ms > self.metrics.max_latency_ms:
                self.metrics.max_latency_ms = latency_ms

        return msg

    def add_user_message(
        self,
        content: str,
        stt_latency_ms: Optional[float] = None,
    ) -> TurnMessage:
        """Convenience method to append a user speech transcription."""
        return self.add_turn(
            role=MessageRole.USER,
            content=content,
            stt_latency_ms=stt_latency_ms,
        )

    def add_assistant_message(
        self,
        content: str,
        latency_ms: Optional[float] = None,
        llm_latency_ms: Optional[float] = None,
        tts_latency_ms: Optional[float] = None,
        interrupted: bool = False,
    ) -> TurnMessage:
        """Convenience method to append assistant vocal response."""
        return self.add_turn(
            role=MessageRole.ASSISTANT,
            content=content,
            latency_ms=latency_ms,
            llm_latency_ms=llm_latency_ms,
            tts_latency_ms=tts_latency_ms,
            interrupted=interrupted,
        )

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        result: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        latency_ms: Optional[float] = None,
    ) -> TurnMessage:
        """Log a tool execution turn and extract known entities."""
        content = json.dumps(result, ensure_ascii=False)
        turn = self.add_turn(
            role=MessageRole.TOOL,
            content=content,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_arguments=arguments,
            tool_result=result,
            latency_ms=latency_ms,
        )

        # Context extraction based on tool results
        if tool_name == "get_order_status":
            if "order_id" in arguments:
                self.context.order_id = str(arguments["order_id"])
            elif "order_id" in result:
                self.context.order_id = str(result["order_id"])

        elif tool_name == "book_reservation":
            if result.get("success") or result.get("reservation_id"):
                self.context.reservation_draft = {**arguments, **result}
                if "customer_name" in arguments:
                    self.context.customer_name = arguments["customer_name"]
                if "phone" in arguments:
                    self.context.customer_phone = arguments["phone"]

        elif tool_name == "escalate_to_human":
            self.context.escalated = True
            self.context.escalation_reason = arguments.get("reason")
            self.context.escalation_department = arguments.get("department")
            self.status = CallStatus.ESCALATED

        return turn

    def record_interruption(self) -> None:
        """Record a caller barge-in / speech interruption event."""
        self.metrics.total_interruptions += 1
        if self.messages and self.messages[-1].role == MessageRole.ASSISTANT:
            self.messages[-1].interrupted = True

    def update_context(self, **kwargs: Any) -> None:
        """Update extracted slots and entities."""
        for key, value in kwargs.items():
            if hasattr(self.context, key):
                setattr(self.context, key, value)
            else:
                self.context.custom_notes[key] = value

    def get_conversation_history(
        self,
        max_turns: Optional[int] = None,
        include_system: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve formatted conversation history for LLM context window.

        Args:
            max_turns: Limit history to the last N turns (sliding window).
            include_system: Whether to include SYSTEM role messages.

        Returns:
            List of OpenAI/Groq message dictionaries.
        """
        filtered = [
            msg for msg in self.messages
            if include_system or msg.role != MessageRole.SYSTEM
        ]

        if max_turns is not None and max_turns > 0:
            # Always keep system messages if present, and slide the remaining
            sys_msgs = [m for m in filtered if m.role == MessageRole.SYSTEM]
            non_sys_msgs = [m for m in filtered if m.role != MessageRole.SYSTEM]
            recent_non_sys = non_sys_msgs[-max_turns:]
            final_msgs = sys_msgs + recent_non_sys if include_system else recent_non_sys
            return [m.to_openai_format() for m in final_msgs]

        return [m.to_openai_format() for m in filtered]

    def end_call(self, status: Optional[CallStatus] = None) -> None:
        """Mark call as completed and calculate duration."""
        self.end_time = datetime.now(timezone.utc)
        self.status = status or (
            CallStatus.ESCALATED if self.context.escalated else CallStatus.ENDED
        )
        self.metrics.duration_seconds = max(
            0.0, (self.end_time - self.start_time).total_seconds()
        )

    def to_summary_dict(self) -> Dict[str, Any]:
        """Compact summary dictionary suitable for analytics dashboards."""
        return {
            "session_id": self.session_id,
            "room_name": self.room_name,
            "participant_identity": self.participant_identity,
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.metrics.duration_seconds,
            "customer_name": self.context.customer_name,
            "customer_phone": self.context.customer_phone,
            "language": self.context.language,
            "order_id": self.context.order_id,
            "escalated": self.context.escalated,
            "escalation_department": self.context.escalation_department,
            "total_user_turns": self.metrics.total_user_turns,
            "total_assistant_turns": self.metrics.total_assistant_turns,
            "total_tool_calls": self.metrics.total_tool_calls,
            "total_interruptions": self.metrics.total_interruptions,
            "average_latency_ms": round(self.metrics.average_latency_ms, 2),
            "max_latency_ms": round(self.metrics.max_latency_ms, 2),
            "total_messages": len(self.messages),
        }


# ==============================================================================
# Central Session Manager & Registry
# ==============================================================================

class SessionManager:
    """
    Thread-safe registry and persistence manager for active and historical call sessions.
    """

    def __init__(self, storage_dir: Optional[Union[str, Path]] = None) -> None:
        self._sessions: Dict[str, CallSession] = {}
        self._lock = threading.RLock()
        self.storage_dir = Path(storage_dir) if storage_dir else Path("data/calls")
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def create_session(
        self,
        session_id: Optional[str] = None,
        room_name: str = "",
        participant_identity: str = "",
        language: str = "ar",
        customer_phone: Optional[str] = None,
    ) -> CallSession:
        """Create and register a new call session."""
        sid = session_id or str(uuid.uuid4())
        session = CallSession(
            session_id=sid,
            room_name=room_name,
            participant_identity=participant_identity,
        )
        session.context.language = language
        session.context.customer_phone = customer_phone

        with self._lock:
            self._sessions[sid] = session

        logger.info(f"Created new voice session {sid} in room '{room_name}'")
        return session

    def get_session(self, session_id: str) -> Optional[CallSession]:
        """Retrieve an in-memory session by ID."""
        with self._lock:
            return self._sessions.get(session_id)

    def get_or_create_session(
        self,
        session_id: str,
        room_name: str = "",
        participant_identity: str = "",
    ) -> CallSession:
        """Get an existing session or initialize a new one if absent."""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                session = self.create_session(
                    session_id=session_id,
                    room_name=room_name,
                    participant_identity=participant_identity,
                )
            return session

    def list_active_sessions(self) -> List[CallSession]:
        """List all currently active sessions (not ended)."""
        with self._lock:
            return [
                s for s in self._sessions.values()
                if s.status not in (CallStatus.ENDED, CallStatus.ESCALATED)
            ]

    def list_all_sessions(self) -> List[CallSession]:
        """List all tracked in-memory sessions."""
        with self._lock:
            return list(self._sessions.values())

    def save_session(self, session_id: str) -> Optional[Path]:
        """
        Persist a call session to disk as a JSON artifact.
        
        Args:
            session_id: Target session ID.

        Returns:
            Path to saved JSON file, or None if session not found.
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning(f"Cannot save session {session_id}: Not found")
            return None

        file_path = self.storage_dir / f"{session_id}.json"
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(session.model_dump_json(indent=2))
            logger.info(f"Saved session {session_id} to {file_path}")
            return file_path
        except Exception as e:
            logger.exception(f"Failed to persist session {session_id}: {e}")
            return None

    def load_session(self, session_id: str) -> Optional[CallSession]:
        """
        Load a call session from disk and register it in memory.
        """
        file_path = self.storage_dir / f"{session_id}.json"
        if not file_path.exists():
            return None

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            session = CallSession.model_validate(data)
            with self._lock:
                self._sessions[session.session_id] = session
            return session
        except Exception as e:
            logger.exception(f"Failed to load session from {file_path}: {e}")
            return None

    def load_all_persisted_sessions(self) -> List[CallSession]:
        """Scan storage directory and load all stored sessions."""
        loaded: List[CallSession] = []
        for file_path in self.storage_dir.glob("*.json"):
            sid = file_path.stem
            session = self.load_session(sid)
            if session:
                loaded.append(session)
        return loaded

    def get_aggregated_metrics(self) -> Dict[str, Any]:
        """Compute aggregate performance and call volume metrics."""
        with self._lock:
            sessions = list(self._sessions.values())

        total_calls = len(sessions)
        if total_calls == 0:
            return {
                "total_calls": 0,
                "active_calls": 0,
                "escalated_calls": 0,
                "total_duration_seconds": 0.0,
                "average_duration_seconds": 0.0,
                "total_interruptions": 0,
                "average_latency_ms": 0.0,
                "total_tool_calls": 0,
            }

        active_calls = sum(
            1 for s in sessions if s.status not in (CallStatus.ENDED, CallStatus.ESCALATED)
        )
        escalated_calls = sum(1 for s in sessions if s.context.escalated)
        total_duration = sum(s.metrics.duration_seconds for s in sessions)
        total_interruptions = sum(s.metrics.total_interruptions for s in sessions)
        total_tool_calls = sum(s.metrics.total_tool_calls for s in sessions)
        measured_latencies = [
            s.metrics.average_latency_ms
            for s in sessions
            if s.metrics.average_latency_ms > 0
        ]
        avg_latency = (
            sum(measured_latencies) / len(measured_latencies)
            if measured_latencies
            else 0.0
        )

        return {
            "total_calls": total_calls,
            "active_calls": active_calls,
            "escalated_calls": escalated_calls,
            "total_duration_seconds": round(total_duration, 2),
            "average_duration_seconds": round(total_duration / total_calls, 2),
            "total_interruptions": total_interruptions,
            "average_latency_ms": round(avg_latency, 2),
            "total_tool_calls": total_tool_calls,
        }


# Global singleton instance
session_manager = SessionManager()
