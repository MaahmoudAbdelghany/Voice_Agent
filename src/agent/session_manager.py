"""
Medical Call Session State, Turn Memory, and Metric Tracking for Egyptian Polyclinic Voice AI Agent.

Provides:
- Clinic-first call context (`ClinicCallContext`, `BookingRef`, `EscalationInfo`) with legacy restaurant field compatibility.
- Enforced call lifecycle state machine (`CallLifecycle`) separated from momentary activity (`CallActivity`).
- Per-turn stage latency tracking (`TurnLatency`) with nearest-rank P50/P95/max percentiles, SLO breach counters (>800ms), and tool timeout counters (>400ms).
- FinOps ledger snapshot integration (`FinOpsController`) and hierarchical Langfuse `trace_id` linkage.
- Tool-pair-safe sliding-window conversation memory with deterministic context summary injection.
- PII-redacted atomic JSON persistence (`asyncio.to_thread` async wrapper) and automatic eviction of ended sessions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from src.config import get_settings

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Lifecycle, Activity & Role Enums
# ==============================================================================


class CallLifecycle(str, Enum):
    """Canonical lifecycle state of a voice call session (R3.1)."""

    INITIATED = "initiated"
    ACTIVE = "active"
    ESCALATED = "escalated"
    ENDED = "ended"
    FAILED = "failed"


class CallActivity(str, Enum):
    """Momentary real-time activity of a call for live UI display (R3.3)."""

    IDLE = "idle"
    LISTENING = "listening"
    SPEAKING = "speaking"
    TOOL_CALLING = "tool_calling"


class CallStatus(str, Enum):
    """
    Backward-compatible call status enum.
    Includes canonical lifecycle states plus legacy momentary states so existing
    dashboard filters, scripts, and tests continue to work without breakage.
    """

    INITIATED = "initiated"
    ACTIVE = "active"
    SPEAKING = "speaking"
    LISTENING = "listening"
    TOOL_CALLING = "tool_calling"
    ESCALATED = "escalated"
    ENDED = "ended"
    FAILED = "failed"


# Allowed lifecycle transitions (R3.1 / R3.2). Terminal states (ENDED, FAILED) have empty sets.
ALLOWED_LIFECYCLE_TRANSITIONS: dict[CallLifecycle, set[CallLifecycle]] = {
    CallLifecycle.INITIATED: {
        CallLifecycle.INITIATED,
        CallLifecycle.ACTIVE,
        CallLifecycle.ESCALATED,
        CallLifecycle.ENDED,
        CallLifecycle.FAILED,
    },
    CallLifecycle.ACTIVE: {
        CallLifecycle.ACTIVE,
        CallLifecycle.ESCALATED,
        CallLifecycle.ENDED,
        CallLifecycle.FAILED,
    },
    CallLifecycle.ESCALATED: {
        CallLifecycle.ESCALATED,
        CallLifecycle.ENDED,
        CallLifecycle.FAILED,
    },
    CallLifecycle.ENDED: {CallLifecycle.ENDED},
    CallLifecycle.FAILED: {CallLifecycle.FAILED},
}

_LEGACY_ACTIVITY_STATUSES: dict[str, CallActivity] = {
    "speaking": CallActivity.SPEAKING,
    "listening": CallActivity.LISTENING,
    "tool_calling": CallActivity.TOOL_CALLING,
}


class MessageRole(str, Enum):
    """Role of a message participant in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ==============================================================================
# 2. Clinic Call Context & Sub-Models (R1, R2)
# ==============================================================================


class BookingRef(BaseModel):
    """Reference to an appointment action executed during the call (R2.2, R2.3)."""

    booking_code: str
    action: str = Field(
        default="booked",
        description="Booking lifecycle action: 'booked', 'cancelled', or 'rescheduled'.",
    )
    queue_number: int | None = None
    appointment_date: str | None = None
    doctor_name: str | None = None
    specialty_name: str | None = None
    shift_window: str | None = None
    visit_type: str | None = None
    fee: float | None = None


class EscalationInfo(BaseModel):
    """Structured receptionist escalation details (R2.4)."""

    reason: str | None = None
    department: str | None = None
    urgency: str | None = None
    handoff_id: str | None = None
    queue_position: int | None = None


class ClinicCallContext(BaseModel):
    """
    Clinic-first call context and extracted slots gathered across turns (R1.1–R1.3).

    Maintains backward-compatible aliases (`customer_name`, `customer_phone`,
    `order_id`, `reservation_draft`, `dietary_preferences`, `allergies`,
    `escalated`, `escalation_reason`, `escalation_department`) so legacy JSON
    files and dashboard pages continue to function seamlessly until Phase 7.
    """

    # Primary clinic fields (R1.1)
    patient_name: str | None = None
    patient_phone: str | None = None
    language: str = "ar"
    requested_specialty: str | None = None
    requested_doctor_id: int | None = None
    requested_doctor_name: str | None = None
    requested_date: str | None = None
    visit_type: str | None = None
    bookings: list[BookingRef] = Field(default_factory=list)
    escalation: EscalationInfo | None = None
    emergency_flag: bool = False
    current_intent: str | None = None
    sentiment: str = "neutral"
    custom_notes: dict[str, Any] = Field(default_factory=dict)

    # Deprecated legacy restaurant fields kept as Optional for backward compatibility (R1.3, C6)
    customer_name: str | None = None
    customer_phone: str | None = None
    order_id: str | None = None
    reservation_draft: dict[str, Any] = Field(default_factory=dict)
    dietary_preferences: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    escalated: bool = False
    escalation_reason: str | None = None
    escalation_department: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _sync_legacy_and_clinic_fields(cls, data: Any) -> Any:
        """Synchronize patient_* and customer_* fields when loading from dicts/JSON."""
        if not isinstance(data, dict):
            return data
        out = dict(data)

        # Sync name
        p_name = out.get("patient_name")
        c_name = out.get("customer_name")
        if p_name and not c_name:
            out["customer_name"] = p_name
        elif c_name and not p_name:
            out["patient_name"] = c_name

        # Sync phone
        p_phone = out.get("patient_phone")
        c_phone = out.get("customer_phone")
        if p_phone and not c_phone:
            out["customer_phone"] = p_phone
        elif c_phone and not p_phone:
            out["patient_phone"] = c_phone

        # Sync escalation object <-> flat legacy escalation fields
        esc = out.get("escalation")
        if isinstance(esc, dict):
            out["escalated"] = True
            if esc.get("reason") and not out.get("escalation_reason"):
                out["escalation_reason"] = esc.get("reason")
            if esc.get("department") and not out.get("escalation_department"):
                out["escalation_department"] = esc.get("department")
        elif isinstance(esc, EscalationInfo):
            out["escalated"] = True
            if esc.reason and not out.get("escalation_reason"):
                out["escalation_reason"] = esc.reason
            if esc.department and not out.get("escalation_department"):
                out["escalation_department"] = esc.department
        elif out.get("escalated"):
            out["escalation"] = {
                "reason": out.get("escalation_reason"),
                "department": out.get("escalation_department"),
                "urgency": "high",
            }

        return out

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        # Keep paired aliases in sync on direct attribute assignment
        if name == "patient_name":
            super().__setattr__("customer_name", value)
        elif name == "customer_name":
            super().__setattr__("patient_name", value)
        elif name == "patient_phone":
            super().__setattr__("customer_phone", value)
        elif name == "customer_phone":
            super().__setattr__("patient_phone", value)
        elif name == "escalation" and value is not None:
            super().__setattr__("escalated", True)
            if isinstance(value, EscalationInfo):
                super().__setattr__("escalation_reason", value.reason)
                super().__setattr__("escalation_department", value.department)

    @property
    def booking_codes(self) -> list[str]:
        """List of all booking codes recorded in this call session."""
        return [b.booking_code for b in self.bookings if b.booking_code]


# Backward-compatible alias (R1.3)
ExtractedContext = ClinicCallContext


# ==============================================================================
# 3. Turn Messages & Latency Breakdown Models (R4)
# ==============================================================================


class TurnLatency(BaseModel):
    """Per-turn stage latency record in milliseconds (R4.1)."""

    stt_ms: float | None = None
    llm_ttft_ms: float | None = None
    tts_ms: float | None = None
    tool_ms: float | None = None
    e2e_ms: float | None = None


class StagePercentiles(BaseModel):
    """Nearest-rank percentile summary for a single latency stage (R4.2)."""

    p50_ms: float = 0.0
    p95_ms: float = 0.0
    max_ms: float = 0.0
    avg_ms: float = 0.0
    samples: int = 0


def compute_nearest_rank_percentiles(values: list[float]) -> StagePercentiles:
    """
    Compute nearest-rank P50, P95, max, and average for a list of positive latency samples (R4.2).
    Returns all zeros when `values` is empty (E3).
    """
    clean = sorted(float(v) for v in values if v is not None and v > 0)
    n = len(clean)
    if n == 0:
        return StagePercentiles()

    def _nearest_rank(pct: float) -> float:
        idx = max(0, min(n - 1, math.ceil((pct / 100.0) * n) - 1))
        return round(clean[idx], 2)

    return StagePercentiles(
        p50_ms=_nearest_rank(50.0),
        p95_ms=_nearest_rank(95.0),
        max_ms=round(clean[-1], 2),
        avg_ms=round(sum(clean) / n, 2),
        samples=n,
    )


class TurnMessage(BaseModel):
    """A single turn or message within a voice conversation."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tool_name: str | None = None
    tool_call_id: str | None = None
    tool_arguments: dict[str, Any] | None = None
    tool_result: dict[str, Any] | None = None
    latency_ms: float | None = None
    stt_latency_ms: float | None = None
    llm_latency_ms: float | None = None
    tts_latency_ms: float | None = None
    tool_latency_ms: float | None = None
    interrupted: bool = False
    trace_id: str | None = None

    def to_openai_format(self) -> dict[str, Any]:
        """Convert message to OpenAI / Groq chat completion format."""
        msg: dict[str, Any] = {
            "role": self.role.value,
            "content": self.content,
        }
        if self.tool_name and self.role == MessageRole.TOOL:
            msg["name"] = self.tool_name
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        return msg


class CallMetrics(BaseModel):
    """
    Real-time performance, operational, and FinOps metrics for a voice session (R4.1–R4.5).
    """

    total_user_turns: int = 0
    total_assistant_turns: int = 0
    total_tool_calls: int = 0
    tool_calls_succeeded: int = 0
    tool_calls_failed: int = 0
    tool_timeouts: int = 0
    total_interruptions: int = 0
    total_latency_ms: float = 0.0
    measured_latency_turns: int = 0
    average_latency_ms: float = 0.0
    max_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    slo_breach_turns: int = 0
    duration_seconds: float = 0.0

    # Per-stage latency samples & computed percentiles
    turn_latencies: list[TurnLatency] = Field(default_factory=list)
    stage_percentiles: dict[str, StagePercentiles] = Field(default_factory=dict)

    # FinOps single-source-of-truth snapshot & Langfuse trace linkage (R4.4, R4.5)
    finops_snapshot: dict[str, Any] | None = None
    trace_ids: list[str] = Field(default_factory=list)

    def record_turn_latency(
        self,
        *,
        stt_ms: float | None = None,
        llm_ttft_ms: float | None = None,
        tts_ms: float | None = None,
        tool_ms: float | None = None,
        e2e_ms: float | None = None,
        slo_threshold_ms: float | None = None,
    ) -> None:
        """Record a turn's stage latencies and recompute stage percentiles & SLO breaches."""
        has_any = any(
            v is not None and v > 0
            for v in (stt_ms, llm_ttft_ms, tts_ms, tool_ms, e2e_ms)
        )
        if not has_any:
            return

        rec = TurnLatency(
            stt_ms=stt_ms if (stt_ms and stt_ms > 0) else None,
            llm_ttft_ms=llm_ttft_ms if (llm_ttft_ms and llm_ttft_ms > 0) else None,
            tts_ms=tts_ms if (tts_ms and tts_ms > 0) else None,
            tool_ms=tool_ms if (tool_ms and tool_ms > 0) else None,
            e2e_ms=e2e_ms if (e2e_ms and e2e_ms > 0) else None,
        )
        self.turn_latencies.append(rec)

        threshold = (
            slo_threshold_ms
            if slo_threshold_ms is not None
            else get_settings().session_slo_turn_ms
        )

        if rec.e2e_ms is not None and rec.e2e_ms > 0:
            self.total_latency_ms += rec.e2e_ms
            self.measured_latency_turns += 1
            self.average_latency_ms = round(
                self.total_latency_ms / self.measured_latency_turns, 2
            )
            self.max_latency_ms = max(self.max_latency_ms, rec.e2e_ms)
            if rec.e2e_ms > threshold:
                self.slo_breach_turns += 1

        self.recompute_percentiles()

    def recompute_percentiles(self) -> None:
        """Recompute nearest-rank P50/P95/max across all recorded stages (R4.2)."""
        stt_vals = [t.stt_ms for t in self.turn_latencies if t.stt_ms is not None]
        llm_vals = [
            t.llm_ttft_ms for t in self.turn_latencies if t.llm_ttft_ms is not None
        ]
        tts_vals = [t.tts_ms for t in self.turn_latencies if t.tts_ms is not None]
        tool_vals = [t.tool_ms for t in self.turn_latencies if t.tool_ms is not None]
        e2e_vals = [t.e2e_ms for t in self.turn_latencies if t.e2e_ms is not None]

        e2e_stats = compute_nearest_rank_percentiles(e2e_vals)
        self.stage_percentiles = {
            "stt": compute_nearest_rank_percentiles(stt_vals),
            "llm_ttft": compute_nearest_rank_percentiles(llm_vals),
            "tts": compute_nearest_rank_percentiles(tts_vals),
            "tool": compute_nearest_rank_percentiles(tool_vals),
            "e2e": e2e_stats,
        }
        if e2e_stats.samples > 0:
            self.p50_latency_ms = e2e_stats.p50_ms
            self.p95_latency_ms = e2e_stats.p95_ms
            self.max_latency_ms = max(self.max_latency_ms, e2e_stats.max_ms)


# ==============================================================================
# 4. Single Call Session Representation
# ==============================================================================


def _resolve_verified_caller_phone() -> str | None:
    """Return the verified caller phone from `caller_session_scope` if active, else None (R1.2)."""
    try:
        from src.tools.gates import get_current_caller_session

        ctx = get_current_caller_session()
        if ctx is not None and ctx.caller_phone:
            return ctx.caller_phone
    except Exception as exc:  # noqa: BLE001
        logger.debug("Verified caller phone resolution skipped: %s", exc)
    return None


def _resolve_active_trace_id() -> str | None:
    """Return the active trace_id from `src.ai_core.tracing` if any (R4.5)."""
    try:
        from src.ai_core.tracing import get_current_trace_id

        return get_current_trace_id()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Active trace_id lookup skipped: %s", exc)
        return None


class CallSession(BaseModel):
    """State, memory, and analytics for an individual voice call session."""

    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    room_name: str = ""
    participant_identity: str = ""
    lifecycle: CallLifecycle = CallLifecycle.INITIATED
    activity: CallActivity = CallActivity.IDLE
    status: CallStatus = CallStatus.INITIATED
    start_time: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    context: ClinicCallContext = Field(default_factory=ClinicCallContext)
    metrics: CallMetrics = Field(default_factory=CallMetrics)
    messages: list[TurnMessage] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_status_on_load(cls, data: Any) -> Any:
        """
        Map legacy status values ('speaking', 'listening', 'tool_calling') from old JSON files
        into `lifecycle=ACTIVE` + matching `activity` (R3.4).
        """
        if not isinstance(data, dict):
            return data
        out = dict(data)
        raw_status = str(out.get("status", "initiated")).lower()
        raw_lifecycle = out.get("lifecycle")

        if raw_status in _LEGACY_ACTIVITY_STATUSES:
            out["lifecycle"] = CallLifecycle.ACTIVE.value
            out["activity"] = _LEGACY_ACTIVITY_STATUSES[raw_status].value
            out["status"] = CallStatus.ACTIVE.value
        elif raw_lifecycle is None:
            try:
                lc = CallLifecycle(raw_status)
                out["lifecycle"] = lc.value
                out["status"] = CallStatus(lc.value).value
            except ValueError:
                out["lifecycle"] = CallLifecycle.INITIATED.value
                out["status"] = CallStatus.INITIATED.value
        else:
            try:
                lc = CallLifecycle(str(raw_lifecycle).lower())
                out["lifecycle"] = lc.value
                out["status"] = CallStatus(lc.value).value
            except ValueError:
                out["lifecycle"] = CallLifecycle.INITIATED.value
                out["status"] = CallStatus.INITIATED.value

        return out

    @model_validator(mode="after")
    def _backfill_latencies_from_legacy_messages(self) -> CallSession:
        """
        When loading legacy JSON sessions that have message latencies but no
        `turn_latencies` list yet, reconstruct stage percentiles automatically.
        """
        if not self.metrics.turn_latencies and self.messages:
            for m in self.messages:
                if any(
                    v is not None and v > 0
                    for v in (
                        m.stt_latency_ms,
                        m.llm_latency_ms,
                        m.tts_latency_ms,
                        m.tool_latency_ms,
                        m.latency_ms,
                    )
                ):
                    self.metrics.turn_latencies.append(
                        TurnLatency(
                            stt_ms=m.stt_latency_ms,
                            llm_ttft_ms=m.llm_latency_ms,
                            tts_ms=m.tts_latency_ms,
                            tool_ms=m.tool_latency_ms,
                            e2e_ms=m.latency_ms,
                        )
                    )
            if self.metrics.turn_latencies:
                self.metrics.recompute_percentiles()
                threshold = get_settings().session_slo_turn_ms
                self.metrics.slo_breach_turns = sum(
                    1
                    for t in self.metrics.turn_latencies
                    if t.e2e_ms is not None and t.e2e_ms > threshold
                )
        return self

    # ------------------------------------------------------------------
    # Lifecycle & Activity Management (R3.1–R3.4)
    # ------------------------------------------------------------------

    def transition_to(self, target: CallLifecycle | CallStatus | str) -> bool:
        """
        Transition the call lifecycle if allowed by `ALLOWED_LIFECYCLE_TRANSITIONS` (R3.1, R3.2).
        Invalid transitions (e.g., from ENDED back to ACTIVE) are logged and rejected without raising.
        """
        try:
            raw = target.value if isinstance(target, Enum) else str(target).lower()
            if raw in _LEGACY_ACTIVITY_STATUSES:
                self.set_activity(_LEGACY_ACTIVITY_STATUSES[raw])
                target_lc = CallLifecycle.ACTIVE
            else:
                target_lc = CallLifecycle(raw)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Session %s rejected unknown lifecycle state %r: %s",
                self.session_id,
                target,
                exc,
            )
            return False

        allowed = ALLOWED_LIFECYCLE_TRANSITIONS.get(self.lifecycle, set())
        if target_lc not in allowed:
            logger.warning(
                "Session %s rejected invalid lifecycle transition %s -> %s",
                self.session_id,
                self.lifecycle.value,
                target_lc.value,
            )
            return False

        super().__setattr__("lifecycle", target_lc)
        super().__setattr__("status", CallStatus(target_lc.value))
        if target_lc in (CallLifecycle.ENDED, CallLifecycle.FAILED):
            super().__setattr__("activity", CallActivity.IDLE)
        return True

    def set_activity(self, activity: CallActivity | str) -> None:
        """Update momentary call activity without mutating canonical lifecycle (R3.3)."""
        try:
            act = (
                activity
                if isinstance(activity, CallActivity)
                else CallActivity(str(activity).lower())
            )
            super().__setattr__("activity", act)
        except (ValueError, TypeError) as exc:
            logger.debug("Ignored invalid activity %r: %s", activity, exc)

    def __setattr__(self, name: str, value: Any) -> None:
        """Intercept direct `.status = ...` or `.lifecycle = ...` assignments to enforce transition rules."""
        if name in ("status", "lifecycle") and "lifecycle" in self.__dict__:
            self.transition_to(value)
            return
        super().__setattr__(name, value)

    # ------------------------------------------------------------------
    # Turn & Latency Recording (R4.1–R4.5)
    # ------------------------------------------------------------------

    def _capture_active_trace_id(self) -> str | None:
        """Capture active trace_id from tracer and append to `metrics.trace_ids` if new (R4.5)."""
        tid = _resolve_active_trace_id()
        if tid and tid not in self.metrics.trace_ids:
            self.metrics.trace_ids.append(tid)
        return tid

    def _sync_verified_phone_from_scope(self) -> None:
        """Populate `patient_phone` from verified `caller_session_scope` if present (R1.2)."""
        verified = _resolve_verified_caller_phone()
        if verified:
            self.context.patient_phone = verified

    def add_turn(
        self,
        role: MessageRole,
        content: str,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_arguments: dict[str, Any] | None = None,
        tool_result: dict[str, Any] | None = None,
        latency_ms: float | None = None,
        stt_latency_ms: float | None = None,
        llm_latency_ms: float | None = None,
        tts_latency_ms: float | None = None,
        tool_latency_ms: float | None = None,
        interrupted: bool = False,
    ) -> TurnMessage:
        """Add a conversation turn and update call metrics safely (NFR-5)."""
        self._sync_verified_phone_from_scope()
        trace_id = self._capture_active_trace_id()

        effective_tool_ms = (
            tool_latency_ms
            if tool_latency_ms is not None
            else (latency_ms if role == MessageRole.TOOL else None)
        )
        effective_e2e_ms = latency_ms if role != MessageRole.TOOL else None

        msg = TurnMessage(
            role=role,
            content=str(content) if content is not None else "",
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_arguments=tool_arguments,
            tool_result=tool_result,
            latency_ms=latency_ms,
            stt_latency_ms=stt_latency_ms,
            llm_latency_ms=llm_latency_ms,
            tts_latency_ms=tts_latency_ms,
            tool_latency_ms=effective_tool_ms,
            interrupted=interrupted,
            trace_id=trace_id,
        )
        self.messages.append(msg)

        # Update role counters & lifecycle
        if role == MessageRole.USER:
            self.metrics.total_user_turns += 1
            if self.lifecycle == CallLifecycle.INITIATED:
                self.transition_to(CallLifecycle.ACTIVE)
        elif role == MessageRole.ASSISTANT:
            self.metrics.total_assistant_turns += 1
            if self.lifecycle == CallLifecycle.INITIATED:
                self.transition_to(CallLifecycle.ACTIVE)
        elif role == MessageRole.TOOL:
            self.metrics.total_tool_calls += 1

        if interrupted:
            self.metrics.total_interruptions += 1

        self.metrics.record_turn_latency(
            stt_ms=stt_latency_ms,
            llm_ttft_ms=llm_latency_ms,
            tts_ms=tts_latency_ms,
            tool_ms=effective_tool_ms,
            e2e_ms=effective_e2e_ms,
        )

        return msg

    def add_user_message(
        self,
        content: str,
        stt_latency_ms: float | None = None,
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
        latency_ms: float | None = None,
        llm_latency_ms: float | None = None,
        tts_latency_ms: float | None = None,
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

    # ------------------------------------------------------------------
    # Tool Execution & Deterministic Clinic Context Extraction (R2.1–R2.6)
    # ------------------------------------------------------------------

    def record_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        result: dict[str, Any] | Any,
        tool_call_id: str | None = None,
        latency_ms: float | None = None,
    ) -> TurnMessage:
        """
        Log a tool execution turn, update tool success/failure/timeout counters,
        and deterministically extract clinic context slots (R2.1–R2.6, NFR-5).
        """
        safe_args = arguments if isinstance(arguments, dict) else {}
        safe_result = result if isinstance(result, dict) else {}

        try:
            content = json.dumps(safe_result, ensure_ascii=False, default=str)
        except (TypeError, ValueError, OverflowError):
            content = str(result)

        turn = self.add_turn(
            role=MessageRole.TOOL,
            content=content,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            tool_arguments=safe_args,
            tool_result=safe_result,
            latency_ms=latency_ms,
            tool_latency_ms=latency_ms,
        )

        # Tool timeout check (>400ms default, R4.3)
        timeout_threshold = get_settings().session_tool_timeout_ms
        if latency_ms is not None and latency_ms > timeout_threshold:
            self.metrics.tool_timeouts += 1

        # Determine tool success vs failure (R2.6, R4.3)
        is_success = self._is_tool_result_successful(tool_name, safe_result)
        if is_success:
            self.metrics.tool_calls_succeeded += 1
        else:
            self.metrics.tool_calls_failed += 1

        # Extract context without ever raising into the pipeline (NFR-5)
        try:
            self._extract_context_from_tool(
                tool_name=tool_name,
                arguments=safe_args,
                result=safe_result,
                is_success=is_success,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Context extraction error in session %s for tool %s: %s",
                self.session_id,
                tool_name,
                exc,
            )

        return turn

    @staticmethod
    def _unwrap_tool_payload(result: dict[str, Any]) -> dict[str, Any]:
        """Unwrap `ToolResult(success=..., data={...})` envelope if present, else return dict as-is."""
        if not isinstance(result, dict):
            return {}
        nested = result.get("data")
        if isinstance(nested, dict):
            merged = {**result, **nested}
            return merged
        return result

    @staticmethod
    def _is_tool_result_successful(tool_name: str, result: dict[str, Any]) -> bool:
        """Determine whether a tool invocation succeeded (R2.6)."""
        if not isinstance(result, dict) or not result:
            return False
        if "success" in result:
            return bool(result["success"])
        if result.get("error"):
            return False
        status = str(result.get("status", "")).lower()
        return status not in ("error", "failed", "not_found", "rejected")

    def _extract_context_from_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        is_success: bool,
    ) -> None:
        """Dispatch deterministic slot extraction by tool name (R2.1–R2.6)."""
        # Always sync verified phone from caller_session_scope; NEVER take patient_phone from LLM args (R1.2)
        self._sync_verified_phone_from_scope()
        payload = self._unwrap_tool_payload(result)

        # 1. Doctor Availability Lookup (R2.1)
        if tool_name == "check_doctor_availability":
            self.context.current_intent = "check_availability"
            spec = (
                payload.get("specialty_name_ar")
                or payload.get("specialty")
                or arguments.get("specialty")
            )
            if spec:
                self.context.requested_specialty = str(spec)

            doc_id = payload.get("doctor_id")
            if isinstance(doc_id, int):
                self.context.requested_doctor_id = doc_id

            doc_name = (
                payload.get("doctor_name_ar")
                or payload.get("doctor_name")
                or arguments.get("doctor_name_or_id")
                or arguments.get("doctor_name")
            )
            if doc_name and not str(doc_name).isdigit():
                self.context.requested_doctor_name = str(doc_name)

            target_date = payload.get("target_date") or arguments.get("date")
            if target_date:
                self.context.requested_date = str(target_date)

        # 2. Appointment Booking (R2.2, R2.6)
        elif tool_name == "book_appointment":
            self.context.current_intent = "book_appointment"
            if not is_success:
                return

            booking_code = payload.get("booking_code")
            if not booking_code:
                return

            p_name = payload.get("patient_name") or arguments.get("patient_name")
            if p_name:
                self.context.patient_name = str(p_name)

            v_type = (
                payload.get("visit_type")
                or arguments.get("visit_type")
                or payload.get("visit_type_ar")
            )
            if v_type:
                self.context.visit_type = str(v_type)

            doc_name = (
                payload.get("doctor_name_ar")
                or payload.get("doctor_name")
                or arguments.get("doctor_name")
            )
            if doc_name:
                self.context.requested_doctor_name = str(doc_name)

            spec = payload.get("specialty_name_ar") or payload.get("specialty")
            if spec:
                self.context.requested_specialty = str(spec)

            appt_date = payload.get("appointment_date") or arguments.get("date")
            if appt_date:
                self.context.requested_date = str(appt_date)

            q_num = payload.get("queue_number")
            fee_val = payload.get("fee")

            self.context.bookings.append(
                BookingRef(
                    booking_code=str(booking_code),
                    action="booked",
                    queue_number=int(q_num) if isinstance(q_num, int) else None,
                    appointment_date=str(appt_date) if appt_date else None,
                    doctor_name=str(doc_name) if doc_name else None,
                    specialty_name=str(spec) if spec else None,
                    shift_window=payload.get("shift_window"),
                    visit_type=str(v_type) if v_type else None,
                    fee=float(fee_val) if isinstance(fee_val, (int, float)) else None,
                )
            )

        # 3. Manage Appointment: Lookup / Cancel / Reschedule (R2.3, R2.6)
        elif tool_name == "manage_appointment":
            action = str(
                payload.get("action") or arguments.get("action") or "lookup"
            ).lower()
            self.context.current_intent = f"manage_appointment:{action}"
            if not is_success:
                return

            status_val = str(payload.get("status", "")).lower()
            if status_val in ("not_found", "error", "failed", "rejected"):
                return

            appts = payload.get("appointments")
            first_appt = (
                appts[0]
                if isinstance(appts, list) and appts and isinstance(appts[0], dict)
                else {}
            )
            b_code = (
                payload.get("booking_code")
                or first_appt.get("booking_code")
                or arguments.get("booking_code")
            )
            if action in ("cancel", "cancelled") and b_code:
                self.context.bookings.append(
                    BookingRef(
                        booking_code=str(b_code),
                        action="cancelled",
                        queue_number=first_appt.get("queue_number"),
                        appointment_date=first_appt.get("appointment_date"),
                        doctor_name=first_appt.get("doctor_name_ar")
                        or first_appt.get("doctor_name"),
                    )
                )
            elif action in ("reschedule", "rescheduled") and b_code:
                new_date = (
                    first_appt.get("appointment_date")
                    or payload.get("new_date")
                    or arguments.get("new_date")
                )
                self.context.bookings.append(
                    BookingRef(
                        booking_code=str(b_code),
                        action="rescheduled",
                        queue_number=first_appt.get("queue_number"),
                        appointment_date=str(new_date) if new_date else None,
                        doctor_name=first_appt.get("doctor_name_ar")
                        or first_appt.get("doctor_name"),
                    )
                )

        # 4. Clinic Knowledge Search
        elif tool_name == "search_clinic_knowledge":
            self.context.current_intent = "knowledge_inquiry"

        # 5. Receptionist Escalation / Human Handoff (R2.4)
        elif tool_name in ("transfer_to_receptionist", "escalate_to_human"):
            self.context.current_intent = "escalation"
            reason = (
                arguments.get("reason")
                or payload.get("reason")
                or "Receptionist transfer"
            )
            dept = (
                arguments.get("department")
                or payload.get("department")
                or "reception"
            )
            urgency = str(
                arguments.get("urgency") or payload.get("urgency") or "normal"
            ).lower()

            if hasattr(dept, "value"):
                dept = dept.value
            if hasattr(urgency, "value"):
                urgency = urgency.value

            esc = EscalationInfo(
                reason=str(reason) if reason else None,
                department=str(dept) if dept else None,
                urgency=str(urgency),
                handoff_id=payload.get("handoff_id") or payload.get("escalation_id"),
                queue_position=payload.get("queue_position"),
            )
            self.context.escalation = esc
            self.context.escalated = True
            self.context.escalation_reason = esc.reason
            self.context.escalation_department = esc.department

            if urgency == "emergency":
                self.mark_emergency(reason=str(reason))

            self.transition_to(CallLifecycle.ESCALATED)

        # 6. Legacy Restaurant Tools (kept for backward compatibility with old tests/scripts)
        elif tool_name in ("get_order_status", "check_order_status"):
            if "order_id" in arguments:
                self.context.order_id = str(arguments["order_id"])
            elif "order_id" in payload:
                self.context.order_id = str(payload["order_id"])

        elif tool_name == "book_reservation":
            if payload.get("success") or payload.get("reservation_id"):
                self.context.reservation_draft = {**arguments, **payload}
                if arguments.get("customer_name"):
                    self.context.customer_name = str(arguments["customer_name"])
                # Only populate legacy customer_phone if no verified scope is active
                if not _resolve_verified_caller_phone():
                    raw_p = arguments.get("phone_number") or arguments.get("phone")
                    if raw_p:
                        self.context.customer_phone = str(raw_p)

    def mark_emergency(self, reason: str | None = None) -> None:
        """
        Mark this call session as a medical emergency (R2.5).
        Invoked when `InputGuardrail` returns `ESCALATE_EMERGENCY` or `transfer_to_receptionist`
        is called with `urgency=emergency`.
        """
        self.context.emergency_flag = True
        self.context.current_intent = "emergency"
        if reason and not self.context.escalation:
            self.context.escalation = EscalationInfo(
                reason=reason,
                department="emergency",
                urgency="emergency",
            )
            self.context.escalated = True
            self.context.escalation_reason = reason
            self.context.escalation_department = "emergency"

    def record_interruption(self) -> None:
        """Record a caller barge-in / speech interruption event."""
        self.metrics.total_interruptions += 1
        if self.messages and self.messages[-1].role == MessageRole.ASSISTANT:
            self.messages[-1].interrupted = True

    def update_context(self, **kwargs: Any) -> None:
        """Update extracted slots and entities."""
        for key, value in kwargs.items():
            # Never allow untrusted update_context to overwrite a verified caller phone
            if key in ("patient_phone", "customer_phone"):
                verified = _resolve_verified_caller_phone()
                if verified:
                    self.context.patient_phone = verified
                    continue
            if hasattr(self.context, key):
                setattr(self.context, key, value)
            else:
                self.context.custom_notes[key] = value

    # ------------------------------------------------------------------
    # Conversation Memory: Deterministic Context Summary & Sliding Window (R5.1–R5.3)
    # ------------------------------------------------------------------

    def build_context_summary(self) -> str:
        """
        Build a short deterministic system message summarizing known `ClinicCallContext` slots (R5.3).
        Returns an empty string when no meaningful clinic/caller context has been gathered yet.
        Zero LLM calls are made.
        """
        ctx = self.context
        parts: list[str] = []

        if ctx.patient_name:
            parts.append(f"المريض: {ctx.patient_name}")
        if ctx.requested_specialty:
            parts.append(f"التخصص المطلوب: {ctx.requested_specialty}")
        if ctx.requested_doctor_name:
            doc_str = ctx.requested_doctor_name
            if ctx.requested_doctor_id:
                doc_str += f" (ID={ctx.requested_doctor_id})"
            parts.append(f"الطبيب: {doc_str}")
        elif ctx.requested_doctor_id:
            parts.append(f"معرف الطبيب: {ctx.requested_doctor_id}")
        if ctx.requested_date:
            parts.append(f"التاريخ: {ctx.requested_date}")
        if ctx.visit_type:
            parts.append(f"نوع الزيارة: {ctx.visit_type}")

        if ctx.bookings:
            b_summaries = []
            for b in ctx.bookings:
                item = f"{b.booking_code} ({b.action}"
                if b.queue_number is not None:
                    item += f", نمرة {b.queue_number}"
                if b.appointment_date:
                    item += f", {b.appointment_date}"
                item += ")"
                b_summaries.append(item)
            parts.append("الحجوزات: " + " | ".join(b_summaries))

        if ctx.emergency_flag:
            parts.append("تنبيه: حالة طوارئ طبية")
        elif ctx.escalation and ctx.escalation.reason:
            parts.append(f"تحويل للاستقبال: {ctx.escalation.reason}")

        if not parts:
            return ""

        return "[ملخص سياق المكالمة الحالي] " + " — ".join(parts)

    def get_conversation_history(
        self,
        max_turns: int | None = None,
        include_system: bool = True,
        include_context_summary: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Retrieve formatted conversation history for the LLM context window (R5.1–R5.3).

        - Defaults to `settings.session_history_window` (12 non-system messages) when `max_turns` is None.
        - Never starts the non-system window with an orphan `TOOL` message whose originating
          `ASSISTANT` or `USER` message was sliced off (R5.2).
        - Prepends a deterministic `build_context_summary()` system message when `include_system`
          and `include_context_summary` are True and context is non-empty (R5.3).
        """
        window = (
            max_turns
            if max_turns is not None
            else get_settings().session_history_window
        )

        sys_msgs = [m for m in self.messages if m.role == MessageRole.SYSTEM]
        non_sys_msgs = [m for m in self.messages if m.role != MessageRole.SYSTEM]

        if window is not None and window > 0 and len(non_sys_msgs) > window:
            start_idx = len(non_sys_msgs) - window
            # Ensure we never start on an orphan TOOL message (R5.2)
            # If the slice starts on a TOOL turn, include its preceding ASSISTANT turn if within budget,
            # otherwise advance past leading orphan TOOL turns so the window never starts with TOOL.
            while start_idx < len(non_sys_msgs) and non_sys_msgs[start_idx].role == MessageRole.TOOL:
                start_idx += 1
            recent_non_sys = non_sys_msgs[start_idx:]
        else:
            # Even without truncation, guard against leading orphan tool messages
            start_idx = 0
            while start_idx < len(non_sys_msgs) and non_sys_msgs[start_idx].role == MessageRole.TOOL:
                start_idx += 1
            recent_non_sys = non_sys_msgs[start_idx:]

        output: list[dict[str, Any]] = []
        if include_system:
            output.extend(m.to_openai_format() for m in sys_msgs)
            if include_context_summary:
                summary = self.build_context_summary()
                if summary:
                    output.append({"role": MessageRole.SYSTEM.value, "content": summary})

        output.extend(m.to_openai_format() for m in recent_non_sys)
        return output

    # ------------------------------------------------------------------
    # Call Termination, FinOps Snapshot & PII-Redacted Export (R4.4, R6.1)
    # ------------------------------------------------------------------

    def refresh_finops_snapshot(self) -> dict[str, Any] | None:
        """
        Read cumulative token & USD cost from `FinOpsController` for this `session_id` (R4.4).
        Stores and returns the snapshot dict if tracked.
        """
        try:
            from src.ai_core.finops import get_finops_controller

            snap = get_finops_controller().get_session_snapshot(self.session_id)
            if snap is not None:
                snap_dict = snap.model_dump()
                self.metrics.finops_snapshot = snap_dict
                return snap_dict
        except Exception as exc:  # noqa: BLE001
            logger.debug("FinOps snapshot lookup skipped for %s: %s", self.session_id, exc)
        return self.metrics.finops_snapshot

    def end_call(self, status: CallStatus | CallLifecycle | None = None) -> None:
        """Mark call as completed, calculate duration, and capture FinOps snapshot (R4.4)."""
        self.end_time = datetime.now(timezone.utc)
        if status is not None:
            self.transition_to(status)
        elif self.lifecycle not in (
            CallLifecycle.ESCALATED,
            CallLifecycle.ENDED,
            CallLifecycle.FAILED,
        ):
            target = (
                CallLifecycle.ESCALATED
                if (self.context.escalated or self.context.escalation is not None)
                else CallLifecycle.ENDED
            )
            self.transition_to(target)

        self.set_activity(CallActivity.IDLE)
        self.metrics.duration_seconds = max(
            0.0, (self.end_time - self.start_time).total_seconds()
        )
        self.metrics.recompute_percentiles()
        self.refresh_finops_snapshot()

    def to_persisted_dict(self) -> dict[str, Any]:
        """
        Produce a PII-redacted dictionary representation suitable for disk persistence (R6.1).
        Uses `get_pii_redactor()` from `src.ai_core.guardrails` to mask Egyptian phone numbers,
        14-digit national IDs, emails, and credit cards across `context` and `messages`
        without mutating the in-memory `CallSession` object.
        """
        raw = json.loads(self.model_dump_json())
        try:
            from src.ai_core.guardrails import get_pii_redactor

            redactor = get_pii_redactor()
            if "context" in raw:
                raw["context"] = redactor.redact_dict(raw["context"])
            if "messages" in raw and isinstance(raw["messages"], list):
                raw["messages"] = redactor.redact_dict(raw["messages"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("PII redaction fallback during session export: %s", exc)
        return raw

    def to_summary_dict(self) -> dict[str, Any]:
        """Compact summary dictionary suitable for analytics dashboards."""
        finops = self.metrics.finops_snapshot or {}
        return {
            "session_id": self.session_id,
            "room_name": self.room_name,
            "participant_identity": self.participant_identity,
            "lifecycle": self.lifecycle.value,
            "activity": self.activity.value,
            "status": self.status.value,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.metrics.duration_seconds,
            "patient_name": self.context.patient_name,
            "patient_phone": self.context.patient_phone,
            "customer_name": self.context.customer_name,
            "customer_phone": self.context.customer_phone,
            "language": self.context.language,
            "requested_specialty": self.context.requested_specialty,
            "requested_doctor_name": self.context.requested_doctor_name,
            "booking_codes": self.context.booking_codes,
            "order_id": self.context.order_id,
            "escalated": self.context.escalated,
            "escalation_department": self.context.escalation_department,
            "emergency_flag": self.context.emergency_flag,
            "total_user_turns": self.metrics.total_user_turns,
            "total_assistant_turns": self.metrics.total_assistant_turns,
            "total_tool_calls": self.metrics.total_tool_calls,
            "tool_calls_succeeded": self.metrics.tool_calls_succeeded,
            "tool_calls_failed": self.metrics.tool_calls_failed,
            "tool_timeouts": self.metrics.tool_timeouts,
            "total_interruptions": self.metrics.total_interruptions,
            "average_latency_ms": round(self.metrics.average_latency_ms, 2),
            "p50_latency_ms": round(self.metrics.p50_latency_ms, 2),
            "p95_latency_ms": round(self.metrics.p95_latency_ms, 2),
            "max_latency_ms": round(self.metrics.max_latency_ms, 2),
            "slo_breach_turns": self.metrics.slo_breach_turns,
            "total_tokens": finops.get("total_tokens", 0),
            "total_cost_usd": finops.get("total_cost_usd", 0.0),
            "trace_ids": list(self.metrics.trace_ids),
            "total_messages": len(self.messages),
        }


# ==============================================================================
# 5. Central Session Manager & Registry (R4.6, R6.1–R6.6)
# ==============================================================================


class SessionManager:
    """
    Thread-safe registry and PII-redacted atomic persistence manager for call sessions.
    """

    def __init__(self, storage_dir: str | Path | None = None) -> None:
        self._sessions: dict[str, CallSession] = {}
        self._lock = threading.RLock()
        default_dir = get_settings().session_storage_dir
        self.storage_dir = Path(storage_dir) if storage_dir else Path(default_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def create_session(
        self,
        session_id: str | None = None,
        room_name: str = "",
        participant_identity: str = "",
        language: str = "ar",
        customer_phone: str | None = None,
        patient_phone: str | None = None,
    ) -> CallSession:
        """Create and register a new call session."""
        sid = session_id or str(uuid.uuid4())
        session = CallSession(
            session_id=sid,
            room_name=room_name,
            participant_identity=participant_identity,
        )
        session.context.language = language

        # Verified scope takes priority over explicit init argument (R1.2)
        verified_phone = _resolve_verified_caller_phone()
        eff_phone = verified_phone or patient_phone or customer_phone
        if eff_phone:
            session.context.patient_phone = eff_phone

        with self._lock:
            self._sessions[sid] = session

        logger.info("Created new voice session %s in room '%s'", sid, room_name)
        return session

    def get_session(self, session_id: str) -> CallSession | None:
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

    def evict_session(self, session_id: str) -> bool:
        """Remove a session from in-memory registry (R6.5)."""
        with self._lock:
            return self._sessions.pop(session_id, None) is not None

    def list_active_sessions(self) -> list[CallSession]:
        """List all currently active sessions (not ended/escalated/failed)."""
        with self._lock:
            return [
                s
                for s in self._sessions.values()
                if s.lifecycle
                not in (
                    CallLifecycle.ENDED,
                    CallLifecycle.ESCALATED,
                    CallLifecycle.FAILED,
                )
            ]

    def list_all_sessions(self) -> list[CallSession]:
        """List all tracked in-memory sessions."""
        with self._lock:
            return list(self._sessions.values())

    def save_session(
        self,
        session_id: str,
        *,
        evict_if_ended: bool | None = None,
    ) -> Path | None:
        """
        Persist a PII-redacted call session to disk atomically (temp file + `os.replace`) (R6.1, R6.2).

        Args:
            session_id: Target session ID.
            evict_if_ended: Explicit override for evicting terminal sessions after a successful write.
                            Note: direct `save_session()` keeps the session in memory by default unless
                            `evict_if_ended=True` is passed (or `end_and_persist()` is called), preserving
                            backward compatibility with callers that inspect the session right after save.

        Returns:
            Path to saved JSON file, or None if session not found or write failed.
        """
        session = self.get_session(session_id)
        if not session:
            logger.warning("Cannot save session %s: Not found", session_id)
            return None

        session.refresh_finops_snapshot()
        redacted_payload = session.to_persisted_dict()
        serialized = json.dumps(redacted_payload, ensure_ascii=False, indent=2)

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        file_path = self.storage_dir / f"{session_id}.json"
        tmp_path: Path | None = None

        try:
            fd, tmp_name = tempfile.mkstemp(
                prefix=f".{session_id}.",
                suffix=".tmp",
                dir=str(self.storage_dir),
            )
            tmp_path = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
            os.replace(str(tmp_path), str(file_path))
            logger.info("Saved PII-redacted session %s to %s", session_id, file_path)

            if evict_if_ended and session.lifecycle in (
                CallLifecycle.ENDED,
                CallLifecycle.ESCALATED,
                CallLifecycle.FAILED,
            ):
                self.evict_session(session_id)

            return file_path
        except Exception:
            logger.exception("Failed to persist session %s", session_id)
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            return None

    async def async_save_session(
        self,
        session_id: str,
        *,
        evict_if_ended: bool | None = None,
    ) -> Path | None:
        """
        Persist a call session on a worker thread via `asyncio.to_thread` so the
        real-time voice event loop is never blocked by disk I/O (R6.3, NFR-2).
        """
        return await asyncio.to_thread(
            self.save_session,
            session_id,
            evict_if_ended=evict_if_ended,
        )

    def end_and_persist(
        self,
        session_id: str,
        status: CallStatus | CallLifecycle | None = None,
        *,
        evict: bool | None = None,
    ) -> Path | None:
        """
        End the session, persist it atomically with PII redaction, and evict it from memory
        when `settings.session_evict_on_end` is enabled (R6.4, R6.5).
        """
        session = self.get_session(session_id)
        if not session:
            return None
        session.end_call(status=status)
        should_evict = (
            evict if evict is not None else get_settings().session_evict_on_end
        )
        return self.save_session(session_id, evict_if_ended=should_evict)

    async def async_end_and_persist(
        self,
        session_id: str,
        status: CallStatus | CallLifecycle | None = None,
        *,
        evict: bool | None = None,
    ) -> Path | None:
        """
        Async counterpart to `end_and_persist`: ends session in memory and offloads atomic
        file write to `asyncio.to_thread`, evicting from memory on success (R6.3–R6.5).
        """
        session = self.get_session(session_id)
        if not session:
            return None
        session.end_call(status=status)
        should_evict = (
            evict if evict is not None else get_settings().session_evict_on_end
        )
        return await self.async_save_session(session_id, evict_if_ended=should_evict)

    def load_session(self, session_id: str) -> CallSession | None:
        """Load a call session from disk and register it in memory (R6.6)."""
        file_path = self.storage_dir / f"{session_id}.json"
        if not file_path.exists():
            return None

        try:
            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)
            session = CallSession.model_validate(data)
            with self._lock:
                self._sessions[session.session_id] = session
            return session
        except Exception:
            logger.exception("Failed to load session from %s", file_path)
            return None

    def load_all_persisted_sessions(self) -> list[CallSession]:
        """Scan storage directory and load all stored `.json` sessions (R6.6)."""
        loaded: list[CallSession] = []
        for file_path in sorted(self.storage_dir.glob("*.json")):
            sid = file_path.stem
            session = self.load_session(sid)
            if session:
                loaded.append(session)
        return loaded

    def get_aggregated_metrics(self) -> dict[str, Any]:
        """
        Compute aggregate performance, SLO compliance, tool health, and FinOps cost
        metrics across tracked sessions (R4.6).
        """
        with self._lock:
            sessions = list(self._sessions.values())

        total_calls = len(sessions)
        if total_calls == 0:
            return {
                "total_calls": 0,
                "active_calls": 0,
                "escalated_calls": 0,
                "emergency_calls": 0,
                "total_duration_seconds": 0.0,
                "average_duration_seconds": 0.0,
                "total_interruptions": 0,
                "average_latency_ms": 0.0,
                "p50_e2e_ms": 0.0,
                "p95_e2e_ms": 0.0,
                "slo_breach_turns": 0,
                "slo_breach_ratio": 0.0,
                "total_tool_calls": 0,
                "tool_failure_ratio": 0.0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
            }

        active_calls = sum(
            1
            for s in sessions
            if s.lifecycle
            not in (
                CallLifecycle.ENDED,
                CallLifecycle.ESCALATED,
                CallLifecycle.FAILED,
            )
        )
        escalated_calls = sum(
            1
            for s in sessions
            if s.context.escalated or s.lifecycle == CallLifecycle.ESCALATED
        )
        emergency_calls = sum(1 for s in sessions if s.context.emergency_flag)
        total_duration = sum(s.metrics.duration_seconds for s in sessions)
        total_interruptions = sum(s.metrics.total_interruptions for s in sessions)
        total_tool_calls = sum(s.metrics.total_tool_calls for s in sessions)
        total_tool_failed = sum(s.metrics.tool_calls_failed for s in sessions)

        # Global e2e latency samples
        all_e2e: list[float] = []
        total_slo_breaches = 0
        for s in sessions:
            total_slo_breaches += s.metrics.slo_breach_turns
            for t in s.metrics.turn_latencies:
                if t.e2e_ms is not None and t.e2e_ms > 0:
                    all_e2e.append(t.e2e_ms)

        e2e_stats = compute_nearest_rank_percentiles(all_e2e)
        measured_session_avgs = [
            s.metrics.average_latency_ms
            for s in sessions
            if s.metrics.average_latency_ms > 0
        ]
        avg_latency = (
            sum(measured_session_avgs) / len(measured_session_avgs)
            if measured_session_avgs
            else 0.0
        )

        slo_breach_ratio = (
            round(total_slo_breaches / len(all_e2e), 4) if all_e2e else 0.0
        )
        tool_failure_ratio = (
            round(total_tool_failed / total_tool_calls, 4)
            if total_tool_calls > 0
            else 0.0
        )

        total_tokens = 0
        total_cost_usd = 0.0
        for s in sessions:
            snap = s.metrics.finops_snapshot or s.refresh_finops_snapshot() or {}
            total_tokens += int(snap.get("total_tokens", 0))
            total_cost_usd += float(snap.get("total_cost_usd", 0.0))

        return {
            "total_calls": total_calls,
            "active_calls": active_calls,
            "escalated_calls": escalated_calls,
            "emergency_calls": emergency_calls,
            "total_duration_seconds": round(total_duration, 2),
            "average_duration_seconds": round(total_duration / total_calls, 2),
            "total_interruptions": total_interruptions,
            "average_latency_ms": round(avg_latency, 2),
            "p50_e2e_ms": e2e_stats.p50_ms,
            "p95_e2e_ms": e2e_stats.p95_ms,
            "slo_breach_turns": total_slo_breaches,
            "slo_breach_ratio": slo_breach_ratio,
            "total_tool_calls": total_tool_calls,
            "tool_failure_ratio": tool_failure_ratio,
            "total_tokens": total_tokens,
            "total_cost_usd": round(total_cost_usd, 6),
        }


# Global singleton instance
session_manager = SessionManager()
