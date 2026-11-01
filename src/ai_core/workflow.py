"""
Deterministic Appointment Workflow State Machine (Feature 4.5).

Enforces the compound reliability law (0.95^10 ≈ 59.8%) by governing state-mutating
and inquiry clinic workflows (`BOOK`, `CANCEL`, `RESCHEDULE`, `LOOKUP`) through an
explicit finite state machine (`AppointmentWorkflowStateMachine`) rather than
unconstrained multi-turn LLM autonomy:

State Transitions:
    INIT -> SLOT_COLLECTION -> PRECONDITION_GATE -> IDEMPOTENCY_CHECK
         -> ATOMIC_EXECUTION -> COMPLETED / REJECTED_BY_GATE / ESCALATED

Guarantees:
1. Server-side caller phone injection via `CallerSessionContext` (`contextvars`).
2. Missing slots halt at `SLOT_COLLECTION` without database writes.
3. Hard Python `DeterministicWriteGate` preconditions before any DB mutation.
4. 24-hour `IdempotencyStore` replay (`idempotent_replay=True`) on duplicate booking retries.
5. Strict step-budget ceiling (`workflow_max_steps = 6`) transitioning to `ESCALATED`
   (`error_class="step_budget_exhausted"`) if exceeded.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.config import Settings, get_settings
from src.db.repository import ClinicRepository
from src.db.schemas import VisitType, clean_egyptian_phone
from src.db.session import get_async_session
from src.tools.appointment_booking import AppointmentBookingTool
from src.tools.doctor_availability import get_cairo_today
from src.tools.gates import (
    DeterministicWriteGate,
    GateVerdict,
    IdempotencyStore,
    get_current_caller_session,
    get_idempotency_store,
    resolve_effective_caller_phone,
)
from src.tools.manage_appointment import ManageAppointmentTool
from src.tools.schemas import (
    ManageAppointmentAction,
    ToolResult,
    parse_colloquial_date,
    parse_visit_type,
)

logger = logging.getLogger(__name__)


class WorkflowState(str, Enum):
    """Explicit finite states of the deterministic appointment workflow."""

    INIT = "INIT"
    SLOT_COLLECTION = "SLOT_COLLECTION"
    PRECONDITION_GATE = "PRECONDITION_GATE"
    IDEMPOTENCY_CHECK = "IDEMPOTENCY_CHECK"
    ATOMIC_EXECUTION = "ATOMIC_EXECUTION"
    COMPLETED = "COMPLETED"
    REJECTED_BY_GATE = "REJECTED_BY_GATE"
    ESCALATED = "ESCALATED"


class WorkflowAction(str, Enum):
    """Supported appointment workflow actions."""

    BOOK = "book"
    CANCEL = "cancel"
    RESCHEDULE = "reschedule"
    LOOKUP = "lookup"


class WorkflowStepTrace(BaseModel):
    """Telemetry record for a single deterministic state transition."""

    model_config = ConfigDict(extra="forbid")

    step_index: int = Field(ge=1, description="1-based index of the state transition.")
    from_state: WorkflowState = Field(description="Source state.")
    to_state: WorkflowState = Field(description="Destination state.")
    duration_ms: float = Field(ge=0.0, description="Duration spent in step (ms).")
    detail: str = Field(description="Concise summary of the step outcome.")


class WorkflowExecutionResult(BaseModel):
    """Unified execution envelope returned by AppointmentWorkflowStateMachine."""

    model_config = ConfigDict(extra="ignore")

    success: bool = Field(description="True if workflow reached COMPLETED state.")
    action: WorkflowAction = Field(description="Executed workflow action.")
    terminal_state: WorkflowState = Field(description="Final state reached by the workflow.")
    tool_result: ToolResult = Field(description="Voice-ready ToolResult payload.")
    idempotency_key: str | None = Field(
        default=None,
        description="Deterministic SHA-256 Idempotency-Key (when applicable).",
    )
    idempotent_replay: bool = Field(
        default=False,
        description="True if result was served via idempotent replay without new DB write.",
    )
    gate_verdict: GateVerdict | None = Field(
        default=None,
        description="Precondition safety gate verdict.",
    )
    spoof_attempt_blocked: bool = Field(
        default=False,
        description="True if caller phone spoofing was detected and overridden.",
    )
    escalate: bool = Field(
        default=False,
        description="True if call should be escalated to human receptionist.",
    )
    error_class: str | None = Field(
        default=None,
        description="Semantic or domain error classification when success=False.",
    )
    steps_taken: int = Field(default=0, ge=0, description="Total state transitions executed.")
    step_traces: list[WorkflowStepTrace] = Field(
        default_factory=list,
        description="Ordered trace of state transitions.",
    )
    total_latency_ms: float = Field(default=0.0, ge=0.0, description="Total execution time in ms.")


class _StepBudgetExhaustedError(Exception):
    """Internal exception raised when workflow transitions exceed max_steps."""


class AppointmentWorkflowStateMachine:
    """
    Deterministic DAG / finite state machine governing appointment booking,
    cancellation, rescheduling, and lookup flows.
    """

    def __init__(
        self,
        session_factory: Any = None,
        gate: DeterministicWriteGate | None = None,
        idempotency_store: IdempotencyStore | None = None,
        settings: Settings | None = None,
        max_steps: int | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.session_factory = session_factory
        self.idempotency_store = idempotency_store or get_idempotency_store()
        self.gate = gate or DeterministicWriteGate(
            session_factory=self.session_factory,
            idempotency_store=self.idempotency_store,
            settings=self.settings,
        )
        self.max_steps: int = (
            int(max_steps) if max_steps is not None else int(self.settings.workflow_max_steps)
        )

    def _record_transition(
        self,
        traces: list[WorkflowStepTrace],
        from_state: WorkflowState,
        to_state: WorkflowState,
        step_start: float,
        detail: str,
    ) -> WorkflowState:
        """
        Append a state transition trace and enforce the hard step budget (`max_steps`).
        Raises `_StepBudgetExhaustedError` if `len(traces) + 1 > self.max_steps`.
        """
        next_idx = len(traces) + 1
        if next_idx > self.max_steps:
            raise _StepBudgetExhaustedError(
                f"Workflow exceeded max_steps budget ({self.max_steps}) transitioning {from_state.value} -> {to_state.value}"
            )
        elapsed_ms = (time.perf_counter() - step_start) * 1000.0
        traces.append(
            WorkflowStepTrace(
                step_index=next_idx,
                from_state=from_state,
                to_state=to_state,
                duration_ms=elapsed_ms,
                detail=detail,
            )
        )
        return to_state

    async def execute(
        self,
        action: WorkflowAction | str,
        *,
        patient_name: str | None = None,
        patient_phone: str | None = None,
        phone: str | None = None,
        doctor_id: int | None = None,
        doctor_name: str | None = None,
        date: dt.date | dt.datetime | str | None = None,
        new_date: dt.date | dt.datetime | str | None = None,
        visit_type: VisitType | str | None = VisitType.EXAMINATION,
        booking_code: str | None = None,
        reason: str | None = None,
        notes: str | None = None,
    ) -> WorkflowExecutionResult:
        """
        Execute an appointment workflow deterministically across finite states.
        Automatically records a child span when an active trace context exists.
        """
        from src.ai_core.tracing import SpanKind, SpanStatus, get_current_trace, span_scope

        if get_current_trace() is None:
            return await self._execute_impl(
                action,
                patient_name=patient_name,
                patient_phone=patient_phone,
                phone=phone,
                doctor_id=doctor_id,
                doctor_name=doctor_name,
                date=date,
                new_date=new_date,
                visit_type=visit_type,
                booking_code=booking_code,
                reason=reason,
                notes=notes,
            )

        action_label = action.value if isinstance(action, WorkflowAction) else str(action)
        with span_scope(
            f"workflow.{action_label}",
            kind=SpanKind.WORKFLOW,
            input_payload={
                "action": action_label,
                "patient_name": patient_name,
                "patient_phone": patient_phone or phone,
                "doctor_id": doctor_id,
                "doctor_name": doctor_name,
                "date": str(date) if date is not None else None,
                "new_date": str(new_date) if new_date is not None else None,
                "booking_code": booking_code,
            },
        ) as sp:
            res = await self._execute_impl(
                action,
                patient_name=patient_name,
                patient_phone=patient_phone,
                phone=phone,
                doctor_id=doctor_id,
                doctor_name=doctor_name,
                date=date,
                new_date=new_date,
                visit_type=visit_type,
                booking_code=booking_code,
                reason=reason,
                notes=notes,
            )
            sp.set_attributes(
                {
                    "action": res.action.value,
                    "terminal_state": res.terminal_state.value,
                    "steps_taken": res.steps_taken,
                    "idempotent_replay": res.idempotent_replay,
                    "spoof_attempt_blocked": res.spoof_attempt_blocked,
                    "escalate": res.escalate,
                }
            )
            sp.set_output(
                {
                    "success": res.success,
                    "terminal_state": res.terminal_state.value,
                    "message": res.tool_result.message,
                    "error": res.tool_result.error,
                }
            )
            if not res.success:
                sp.set_status(
                    SpanStatus.ERROR,
                    error_class=res.error_class or "workflow_failed",
                    error_message=res.tool_result.message,
                )
            return res

    async def _execute_impl(
        self,
        action: WorkflowAction | str,
        *,
        patient_name: str | None = None,
        patient_phone: str | None = None,
        phone: str | None = None,
        doctor_id: int | None = None,
        doctor_name: str | None = None,
        date: dt.date | dt.datetime | str | None = None,
        new_date: dt.date | dt.datetime | str | None = None,
        visit_type: VisitType | str | None = VisitType.EXAMINATION,
        booking_code: str | None = None,
        reason: str | None = None,
        notes: str | None = None,
    ) -> WorkflowExecutionResult:
        overall_start = time.perf_counter()
        traces: list[WorkflowStepTrace] = []
        current_state = WorkflowState.INIT
        spoof_blocked = False
        verdict: GateVerdict | None = None
        idem_key: str | None = None

        try:
            wf_action = (
                action
                if isinstance(action, WorkflowAction)
                else WorkflowAction(str(action).strip().lower())
            )
        except ValueError:
            msg = "عذراً، هذا الإجراء غير مدعوم في نظام المواعيد."
            return WorkflowExecutionResult(
                success=False,
                action=WorkflowAction.LOOKUP,
                terminal_state=WorkflowState.REJECTED_BY_GATE,
                tool_result=ToolResult(success=False, message=msg, error="unsupported_action"),
                error_class="unsupported_action",
                steps_taken=0,
                step_traces=[],
                total_latency_ms=(time.perf_counter() - overall_start) * 1000.0,
            )

        try:
            # ==================================================================
            # State 1: INIT -> SLOT_COLLECTION
            # ==================================================================
            step_t = time.perf_counter()
            raw_phone = patient_phone if patient_phone is not None else phone
            effective_phone, spoof_blocked = resolve_effective_caller_phone(
                raw_phone, settings=self.settings
            )

            effective_name = patient_name.strip() if isinstance(patient_name, str) else None
            if not effective_name:
                session_ctx = get_current_caller_session()
                if session_ctx and session_ctx.caller_name:
                    effective_name = session_ctx.caller_name

            current_state = self._record_transition(
                traces,
                current_state,
                WorkflowState.SLOT_COLLECTION,
                step_t,
                f"Resolved caller identity and slots for action={wf_action.value} (spoof_blocked={spoof_blocked})",
            )

            # Validate required slots per action before touching DB
            slot_error_msg: str | None = None
            slot_error_code: str | None = None
            cairo_today = get_cairo_today()

            if wf_action == WorkflowAction.BOOK:
                if not effective_name or len(effective_name) < 2:
                    slot_error_msg = "ممكن تقولي اسم المريض بالكامل عشان نكمل الحجز؟"
                    slot_error_code = "missing_patient_name"
                elif not effective_phone:
                    slot_error_msg = "ممكن تقولي رقم موبايل مصري للتواصل وتأكيد الحجز؟"
                    slot_error_code = "missing_patient_phone"
                else:
                    try:
                        clean_egyptian_phone(effective_phone)
                    except ValueError:
                        slot_error_msg = "رقم الموبايل مش واضح. ممكن تقولي رقم موبايل مصري يبدأ بـ 010 أو 011 أو 012 أو 015؟"
                        slot_error_code = "invalid_patient_phone"

                if (
                    slot_error_code is None
                    and doctor_id is None
                    and not (doctor_name and str(doctor_name).strip())
                ):
                    slot_error_msg = "ممكن تقولي اسم الدكتور اللي حضرتك عايز تحجز معاه؟"
                    slot_error_code = "missing_doctor"

                if slot_error_code is None:
                    if date is None or (isinstance(date, str) and not date.strip()):
                        slot_error_msg = (
                            "ممكن تقولي حضرتك عايز تحجز يوم إيه؟ مثلاً بكرة أو يوم السبت."
                        )
                        slot_error_code = "missing_date"
                    else:
                        try:
                            if not isinstance(date, (dt.date, dt.datetime)):
                                parse_colloquial_date(str(date), today=cairo_today)
                        except (ValueError, TypeError):
                            slot_error_msg = (
                                "ممكن تقولي حضرتك عايز تحجز يوم إيه؟ مثلاً بكرة أو يوم السبت."
                            )
                            slot_error_code = "invalid_date"

            elif wf_action in (WorkflowAction.CANCEL, WorkflowAction.LOOKUP):
                if not (booking_code and str(booking_code).strip()) and not effective_phone:
                    slot_error_msg = (
                        "يرجى التأكد من تزويدنا بكود الحجز أو رقم الموبايل لتنفيذ طلبك."
                    )
                    slot_error_code = "missing_identifier"

            elif wf_action == WorkflowAction.RESCHEDULE:
                if not (booking_code and str(booking_code).strip()):
                    slot_error_msg = (
                        "لتأجيل الميعاد، يرجى تزويدنا بكود الحجز والتاريخ الجديد المطلوب."
                    )
                    slot_error_code = "missing_booking_code"
                elif new_date is None or (isinstance(new_date, str) and not new_date.strip()):
                    slot_error_msg = (
                        "ممكن توضح التاريخ الجديد اللي تحب تنقل الحجز ليه؟ مثلاً بكرة أو يوم السبت."
                    )
                    slot_error_code = "missing_new_date"
                else:
                    try:
                        if not isinstance(new_date, (dt.date, dt.datetime)):
                            parse_colloquial_date(str(new_date), today=cairo_today)
                    except (ValueError, TypeError):
                        slot_error_msg = "ممكن توضح التاريخ الجديد اللي تحب تنقل الحجز ليه؟ مثلاً بكرة أو يوم السبت."
                        slot_error_code = "invalid_date"

            if slot_error_code is not None:
                t_res = ToolResult(
                    success=False,
                    message=slot_error_msg or "بيانات غير مكتملة.",
                    error=slot_error_code,
                    data={"spoof_attempt_blocked": spoof_blocked},
                )
                return WorkflowExecutionResult(
                    success=False,
                    action=wf_action,
                    terminal_state=WorkflowState.SLOT_COLLECTION,
                    tool_result=t_res,
                    spoof_attempt_blocked=spoof_blocked,
                    error_class="missing_or_invalid_slot",
                    steps_taken=len(traces),
                    step_traces=traces,
                    total_latency_ms=(time.perf_counter() - overall_start) * 1000.0,
                )

            # ==================================================================
            # State 2: SLOT_COLLECTION -> PRECONDITION_GATE
            # ==================================================================
            step_t = time.perf_counter()
            async with get_async_session(self.session_factory) as session:
                repo = ClinicRepository(session)

                if wf_action == WorkflowAction.BOOK:
                    verdict = await self.gate.verify_booking(
                        repo,
                        patient_name=effective_name,
                        patient_phone=effective_phone,
                        doctor_id=doctor_id,
                        doctor_name=doctor_name,
                        date=date,
                        visit_type=visit_type,
                        notes=notes,
                    )
                elif wf_action == WorkflowAction.CANCEL:
                    verdict = await self.gate.verify_cancellation(
                        repo,
                        booking_code=booking_code,
                        phone=effective_phone,
                    )
                elif wf_action == WorkflowAction.RESCHEDULE:
                    verdict = await self.gate.verify_reschedule(
                        repo,
                        booking_code=booking_code,
                        phone=effective_phone,
                        new_date=new_date,
                    )
                else:
                    # LOOKUP gate check: verify ownership if booking_code and effective_phone given
                    verdict = GateVerdict(
                        allowed=True,
                        action="lookup",
                        effective_caller_phone=effective_phone,
                        spoof_attempt_blocked=spoof_blocked,
                    )
                    if booking_code and effective_phone:
                        appt = await repo.get_appointment_by_code(booking_code)
                        if appt and appt.patient:
                            try:
                                if clean_egyptian_phone(appt.patient.phone) != clean_egyptian_phone(
                                    effective_phone
                                ):
                                    verdict = GateVerdict(
                                        allowed=False,
                                        action="lookup",
                                        error_code="phone_mismatch",
                                        message_ar="عذراً، كود الحجز ده مش متسجل بنفس رقم الموبايل المطلوب.",
                                        effective_caller_phone=effective_phone,
                                        spoof_attempt_blocked=spoof_blocked,
                                    )
                            except ValueError:
                                pass

                current_state = self._record_transition(
                    traces,
                    current_state,
                    WorkflowState.PRECONDITION_GATE,
                    step_t,
                    f"Gate evaluated action={wf_action.value}: allowed={verdict.allowed}, error_code={verdict.error_code}",
                )

                if not verdict.allowed:
                    step_t = time.perf_counter()
                    current_state = self._record_transition(
                        traces,
                        current_state,
                        WorkflowState.REJECTED_BY_GATE,
                        step_t,
                        f"Rejected by deterministic gate: {verdict.error_code}",
                    )
                    extra_data: dict[str, Any] = {
                        "gate_verdict": verdict.model_dump(),
                        "spoof_attempt_blocked": spoof_blocked,
                    }
                    if verdict.next_available is not None or verdict.error_code in (
                        "no_shift",
                        "shift_ended",
                        "shift_full",
                    ):
                        extra_data["next_available"] = verdict.next_available
                    if verdict.candidates:
                        extra_data["candidates"] = verdict.candidates

                    t_res = ToolResult(
                        success=False,
                        message=verdict.message_ar or "تعذر تنفيذ الطلب.",
                        error=verdict.error_code or "gate_rejected",
                        data=extra_data,
                    )
                    return WorkflowExecutionResult(
                        success=False,
                        action=wf_action,
                        terminal_state=WorkflowState.REJECTED_BY_GATE,
                        tool_result=t_res,
                        gate_verdict=verdict,
                        spoof_attempt_blocked=spoof_blocked,
                        error_class=verdict.error_code or "gate_rejected",
                        steps_taken=len(traces),
                        step_traces=traces,
                        total_latency_ms=(time.perf_counter() - overall_start) * 1000.0,
                    )

                idem_key = verdict.idempotency_key

                # ==============================================================
                # State 3: PRECONDITION_GATE -> IDEMPOTENCY_CHECK (for BOOK)
                # ==============================================================
                if wf_action == WorkflowAction.BOOK and idem_key is not None:
                    step_t = time.perf_counter()
                    assert verdict.effective_caller_phone is not None
                    assert verdict.doctor_id is not None
                    assert verdict.target_date is not None

                    replay_res = await self.gate.check_idempotent_booking_replay(
                        repo,
                        idempotency_key=idem_key,
                        effective_phone=verdict.effective_caller_phone,
                        doctor_id=verdict.doctor_id,
                        target_date=dt.date.fromisoformat(verdict.target_date),
                        patient_name=effective_name or "",
                        spoof_blocked=spoof_blocked,
                    )
                    current_state = self._record_transition(
                        traces,
                        current_state,
                        WorkflowState.IDEMPOTENCY_CHECK,
                        step_t,
                        f"Checked idempotency key={idem_key[:12]}... hit={replay_res is not None}",
                    )
                    if replay_res is not None:
                        step_t = time.perf_counter()
                        current_state = self._record_transition(
                            traces,
                            current_state,
                            WorkflowState.COMPLETED,
                            step_t,
                            f"Returned idempotent replay for booking_code={replay_res.data.get('booking_code') if replay_res.data else ''}",
                        )
                        return WorkflowExecutionResult(
                            success=True,
                            action=wf_action,
                            terminal_state=WorkflowState.COMPLETED,
                            tool_result=replay_res,
                            idempotency_key=idem_key,
                            idempotent_replay=True,
                            gate_verdict=verdict,
                            spoof_attempt_blocked=spoof_blocked,
                            steps_taken=len(traces),
                            step_traces=traces,
                            total_latency_ms=(time.perf_counter() - overall_start) * 1000.0,
                        )

            # ==================================================================
            # State 4: -> ATOMIC_EXECUTION
            # ==================================================================
            step_t = time.perf_counter()
            if wf_action == WorkflowAction.BOOK:
                assert verdict is not None
                assert verdict.doctor_id is not None
                assert verdict.target_date is not None
                assert verdict.effective_caller_phone is not None

                booking_tool = AppointmentBookingTool(session_factory=self.session_factory)
                exec_res = await booking_tool.aexecute(
                    patient_name=effective_name,
                    patient_phone=verdict.effective_caller_phone,
                    doctor_id=verdict.doctor_id,
                    date=dt.date.fromisoformat(verdict.target_date),
                    visit_type=parse_visit_type(verdict.effective_visit_type),
                    notes=notes,
                )
            else:
                manage_tool = ManageAppointmentTool(session_factory=self.session_factory)
                exec_res = await manage_tool.aexecute(
                    action=ManageAppointmentAction(wf_action.value),
                    booking_code=booking_code,
                    phone=effective_phone,
                    new_date=new_date,
                    reason=reason,
                )

            current_state = self._record_transition(
                traces,
                current_state,
                WorkflowState.ATOMIC_EXECUTION,
                step_t,
                f"Executed atomic DB transaction for action={wf_action.value}: success={exec_res.success}",
            )

            # Handle race condition or unexpected rejection during ATOMIC_EXECUTION
            if not exec_res.success:
                step_t = time.perf_counter()
                current_state = self._record_transition(
                    traces,
                    current_state,
                    WorkflowState.REJECTED_BY_GATE,
                    step_t,
                    f"Atomic execution rejected: {exec_res.error}",
                )
                return WorkflowExecutionResult(
                    success=False,
                    action=wf_action,
                    terminal_state=WorkflowState.REJECTED_BY_GATE,
                    tool_result=exec_res,
                    idempotency_key=idem_key,
                    idempotent_replay=False,
                    gate_verdict=verdict,
                    spoof_attempt_blocked=spoof_blocked,
                    error_class=exec_res.error or "execution_failed",
                    steps_taken=len(traces),
                    step_traces=traces,
                    total_latency_ms=(time.perf_counter() - overall_start) * 1000.0,
                )

            # ==================================================================
            # State 5: ATOMIC_EXECUTION -> COMPLETED
            # ==================================================================
            step_t = time.perf_counter()
            if exec_res.data is not None:
                exec_res.data["spoof_attempt_blocked"] = spoof_blocked
                if idem_key is not None:
                    exec_res.data["idempotency_key"] = idem_key
                    exec_res.data["idempotent_replay"] = False

            current_state = self._record_transition(
                traces,
                current_state,
                WorkflowState.COMPLETED,
                step_t,
                f"Workflow completed successfully for action={wf_action.value}",
            )

            return WorkflowExecutionResult(
                success=True,
                action=wf_action,
                terminal_state=WorkflowState.COMPLETED,
                tool_result=exec_res,
                idempotency_key=idem_key,
                idempotent_replay=False,
                gate_verdict=verdict,
                spoof_attempt_blocked=spoof_blocked,
                steps_taken=len(traces),
                step_traces=traces,
                total_latency_ms=(time.perf_counter() - overall_start) * 1000.0,
            )

        except _StepBudgetExhaustedError as exc:
            logger.warning("AppointmentWorkflowStateMachine step budget exhausted: %s", exc)
            esc_msg = (
                "عذراً، استغرقت عملية التحقق خطوات أكثر من المعتاد. "
                "جاري تحويل حضرتك لموظف الاستقبال لإتمام طلبك فوراً."
            )
            t_res = ToolResult(
                success=False,
                message=esc_msg,
                error="step_budget_exhausted",
                data={"spoof_attempt_blocked": spoof_blocked},
            )
            return WorkflowExecutionResult(
                success=False,
                action=wf_action,
                terminal_state=WorkflowState.ESCALATED,
                tool_result=t_res,
                idempotency_key=idem_key,
                gate_verdict=verdict,
                spoof_attempt_blocked=spoof_blocked,
                escalate=True,
                error_class="step_budget_exhausted",
                steps_taken=len(traces),
                step_traces=traces,
                total_latency_ms=(time.perf_counter() - overall_start) * 1000.0,
            )
        except Exception as exc:
            # Privacy invariant (NFR3): never log raw phone numbers
            logger.exception("Unhandled error in AppointmentWorkflowStateMachine")
            err_msg = (
                "عذراً، حدث خطأ تقني غير متوقع أثناء تنفيذ طلبك. "
                "جاري تحويلك لموظف الاستقبال للمساعدة."
            )
            t_res = ToolResult(
                success=False,
                message=err_msg,
                error=f"workflow_exception: {type(exc).__name__}",
                data={"spoof_attempt_blocked": spoof_blocked},
            )
            return WorkflowExecutionResult(
                success=False,
                action=wf_action,
                terminal_state=WorkflowState.ESCALATED,
                tool_result=t_res,
                idempotency_key=idem_key,
                gate_verdict=verdict,
                spoof_attempt_blocked=spoof_blocked,
                escalate=True,
                error_class="workflow_exception",
                steps_taken=len(traces),
                step_traces=traces,
                total_latency_ms=(time.perf_counter() - overall_start) * 1000.0,
            )


_workflow_instance: AppointmentWorkflowStateMachine | None = None


def get_appointment_workflow() -> AppointmentWorkflowStateMachine:
    """Return global singleton AppointmentWorkflowStateMachine instance."""
    global _workflow_instance
    if _workflow_instance is None:
        _workflow_instance = AppointmentWorkflowStateMachine()
    return _workflow_instance


__all__ = [
    "AppointmentWorkflowStateMachine",
    "WorkflowAction",
    "WorkflowExecutionResult",
    "WorkflowState",
    "WorkflowStepTrace",
    "get_appointment_workflow",
]
