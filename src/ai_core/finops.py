"""
FinOps Token Budgets, Daily Cost Circuit Breaker & Tool Payload Pruner (Feature 4.7).

Enforces deterministic financial and token guardrails (`spec/tech.md` Invariant 8):
1. Per-Call Cumulative Token Budget (`finops_call_token_budget = 8,000` tokens):
   - Resolves `session_id` automatically via `contextvars` hierarchy:
     `finops_session_scope` -> `trace_scope.session_id` -> `caller_session_scope.session_id` / `caller_phone`.
   - Clamps final-turn `effective_max_tokens` to `min(stage_cap, remaining_call_tokens)` when remaining
     tokens are between `finops_min_turn_tokens` (16) and `stage_cap` (150 / 256).
   - Blocks further LLM calls (`CALL_BUDGET_EXCEEDED`) once cumulative call tokens reach `>= 8,000`
     (or remaining `< 16`), triggering a polite Arabic wrap-up and receptionist escalation (Tier 4).
2. Cairo-Day Spend Accumulator, 80% Alert & $10/day Cost Circuit Breaker:
   - Tracks daily USD spend keyed by Cairo calendar date (`Africa/Cairo`, `YYYY-MM-DD`) for automatic
     midnight rollover without external cron jobs.
   - Emits an idempotent `WARNING_80_PERCENT` `FinOpsAlert` once per Cairo day at `>= $8.00` (80% of $10).
   - Emits a `CRITICAL_100_PERCENT` `FinOpsAlert` and trips the Cost Circuit Breaker (`DAILY_CAP_EXCEEDED`)
     at `>= $10.00`, causing `ModelGateway` to degrade to Tier 3 (KB search-only) or Tier 4 (receptionist).
3. Schema-Aware Tool Payload Pruning (`prune_tool_payload`, `format_pruned_tool_message`):
   - Strips verbose internal fields from clinic tool outputs before appending to LLM message state,
     retaining essential allowlisted keys and enforcing list-item (5), string-field (300 chars), and
     serialized JSON (1,200 chars) caps.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import json
import logging
import secrets
import threading
from collections import OrderedDict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.ai_core.tracing import estimate_llm_cost_usd, get_current_trace
from src.config import Settings, get_settings
from src.tools.doctor_availability import get_cairo_today
from src.tools.gates import get_current_caller_session
from src.tools.schemas import ToolResult

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Domain Enums & Pydantic Models
# ==============================================================================


class FinOpsGateStatus(str, Enum):
    """Pre-flight FinOps gate verdict for an incoming LLM generation request."""

    ALLOWED = "ALLOWED"
    CALL_BUDGET_EXCEEDED = "CALL_BUDGET_EXCEEDED"
    DAILY_CAP_EXCEEDED = "DAILY_CAP_EXCEEDED"


class AlertLevel(str, Enum):
    """Severity level for FinOps budget alerts."""

    WARNING_80_PERCENT = "WARNING_80_PERCENT"
    CRITICAL_100_PERCENT = "CRITICAL_100_PERCENT"


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class FinOpsAlert(BaseModel):
    """Structured FinOps spend alert emitted at 80% warning and 100% daily cap breach."""

    model_config = ConfigDict(extra="forbid")

    alert_id: str = Field(
        default_factory=lambda: f"finops-{secrets.token_hex(6)}",
        description="Unique alert identifier.",
    )
    cairo_date: str = Field(description="Cairo calendar date (YYYY-MM-DD) for the spend bucket.")
    level: AlertLevel = Field(description="Alert threshold level (80% warning vs 100% breach).")
    spend_usd: float = Field(ge=0.0, description="Cumulative daily spend in USD when triggered.")
    daily_cap_usd: float = Field(ge=0.0, description="Configured daily spend cap in USD.")
    spend_ratio: float = Field(ge=0.0, description="Ratio of spend_usd / daily_cap_usd.")
    timestamp_iso: str = Field(default_factory=_utc_now_iso, description="UTC ISO-8601 timestamp.")
    message: str = Field(description="Human-readable alert summary.")


class CallBudgetSnapshot(BaseModel):
    """Immutable snapshot of a single call session's cumulative token & cost ledger."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(description="Call / room session identifier.")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    budget_tokens: int = Field(default=8000, ge=0)
    remaining_tokens: int = Field(default=8000, ge=0)
    turns_count: int = Field(default=0, ge=0)
    exhausted: bool = Field(default=False)


class DailySpendSnapshot(BaseModel):
    """Immutable snapshot of a Cairo calendar day's cumulative token & USD spend bucket."""

    model_config = ConfigDict(extra="forbid")

    cairo_date: str = Field(description="Cairo calendar date (YYYY-MM-DD).")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    spend_usd: float = Field(default=0.0, ge=0.0)
    daily_cap_usd: float = Field(default=10.0, ge=0.0)
    alert_threshold_usd: float = Field(default=8.0, ge=0.0)
    spend_ratio: float = Field(default=0.0, ge=0.0)
    alert_80_emitted: bool = Field(default=False)
    breaker_100_tripped: bool = Field(default=False)
    requests_count: int = Field(default=0, ge=0)


class FinOpsDecision(BaseModel):
    """Pre-flight budget evaluation decision returned by FinOpsController.check_budget()."""

    model_config = ConfigDict(extra="forbid")

    allowed: bool = Field(description="True if the LLM call is permitted to proceed.")
    status: FinOpsGateStatus = Field(description="Gate status classification.")
    stage: str = Field(description="Workflow stage name (dialogue, classification, extraction).")
    session_id: str | None = Field(default=None, description="Resolved call session ID, if any.")
    requested_max_tokens: int = Field(
        ge=0, description="Stage-resolved max_tokens before clamping."
    )
    effective_max_tokens: int = Field(
        ge=0,
        description="Clamped max_tokens to pass to the LLM provider (0 when blocked).",
    )
    clamped_by_call_budget: bool = Field(
        default=False,
        description="True if effective_max_tokens was reduced to fit remaining call tokens.",
    )
    call_tokens_used: int = Field(default=0, ge=0)
    call_tokens_remaining: int = Field(default=8000, ge=0)
    daily_spend_usd: float = Field(default=0.0, ge=0.0)
    daily_cap_usd: float = Field(default=10.0, ge=0.0)
    cairo_date: str = Field(description="Active Cairo date bucket (YYYY-MM-DD).")
    reason: str | None = Field(
        default=None,
        description="Machine-readable rejection reason when allowed=False.",
    )


# ==============================================================================
# 2. `contextvars` Session Scope & 3-Level Automatic Session ID Resolution
# ==============================================================================

_finops_session_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "finops_session_id", default=None
)


def get_current_finops_session_id() -> str | None:
    """Return the session_id explicitly bound via finops_session_scope, or None."""
    return _finops_session_id_var.get()


@contextmanager
def finops_session_scope(session_id: str) -> Iterator[str]:
    """
    Bind a call `session_id` to the current async/thread execution context for FinOps tracking.
    Automatically restores the previous session_id upon exit.
    """
    clean_id = str(session_id).strip()
    token = _finops_session_id_var.set(clean_id if clean_id else None)
    try:
        yield clean_id
    finally:
        _finops_session_id_var.reset(token)


def resolve_finops_session_id(explicit_session_id: str | None = None) -> str | None:
    """
    Resolve the active call `session_id` in priority order (R1.2):
    1. Explicit `session_id` parameter passed by caller.
    2. Active `finops_session_scope(session_id)` in `contextvars`.
    3. Active `trace_scope` (`get_current_trace().session_id`) from `src.ai_core.tracing`.
    4. Active `caller_session_scope` (`session_id` or `caller_phone`) from `src.tools.gates`.
    """
    if explicit_session_id and str(explicit_session_id).strip():
        return str(explicit_session_id).strip()

    scoped_id = _finops_session_id_var.get()
    if scoped_id:
        return scoped_id

    active_trace = get_current_trace()
    if active_trace is not None and active_trace.session_id:
        return str(active_trace.session_id).strip()

    caller_ctx = get_current_caller_session()
    if caller_ctx is not None:
        if caller_ctx.session_id:
            return str(caller_ctx.session_id).strip()
        if caller_ctx.caller_phone:
            return f"caller:{caller_ctx.caller_phone}"

    return None


# ==============================================================================
# 3. Internal Mutable Ledgers & FinOpsController
# ==============================================================================


class _SessionLedger:
    """Lightweight mutable per-call token and cost accumulator."""

    __slots__ = (
        "completion_tokens",
        "prompt_tokens",
        "session_id",
        "total_cost_usd",
        "total_tokens",
        "turns_count",
    )

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.total_cost_usd: float = 0.0
        self.turns_count: int = 0

    def to_snapshot(self, budget_tokens: int, min_turn_tokens: int) -> CallBudgetSnapshot:
        remaining = max(0, budget_tokens - self.total_tokens)
        exhausted = self.total_tokens >= budget_tokens or remaining < min_turn_tokens
        return CallBudgetSnapshot(
            session_id=self.session_id,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            total_cost_usd=round(self.total_cost_usd, 8),
            budget_tokens=budget_tokens,
            remaining_tokens=remaining,
            turns_count=self.turns_count,
            exhausted=exhausted,
        )


class _DailyBucket:
    """Lightweight mutable per-Cairo-day token and USD spend accumulator."""

    __slots__ = (
        "alert_80_emitted",
        "breaker_100_tripped",
        "cairo_date",
        "completion_tokens",
        "prompt_tokens",
        "requests_count",
        "spend_usd",
        "total_tokens",
    )

    def __init__(self, cairo_date: str) -> None:
        self.cairo_date = cairo_date
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.spend_usd: float = 0.0
        self.alert_80_emitted: bool = False
        self.breaker_100_tripped: bool = False
        self.requests_count: int = 0

    def to_snapshot(self, daily_cap_usd: float, alert_ratio: float) -> DailySpendSnapshot:
        alert_threshold = round(daily_cap_usd * alert_ratio, 6)
        ratio = (self.spend_usd / daily_cap_usd) if daily_cap_usd > 0 else 0.0
        return DailySpendSnapshot(
            cairo_date=self.cairo_date,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            spend_usd=round(self.spend_usd, 8),
            daily_cap_usd=daily_cap_usd,
            alert_threshold_usd=alert_threshold,
            spend_ratio=round(ratio, 6),
            alert_80_emitted=self.alert_80_emitted,
            breaker_100_tripped=self.breaker_100_tripped,
            requests_count=self.requests_count,
        )


class FinOpsController:
    """
    Deterministic FinOps budget controller and daily cost circuit breaker.

    Enforces:
    - Per-call cumulative token budget (`finops_call_token_budget = 8,000`) with
      final-turn `max_tokens` clamping and Tier 4 wrap-up on exhaustion.
    - Daily USD spend cap (`finops_daily_spend_cap_usd = $10.00`) keyed by Cairo calendar
      date (`Africa/Cairo`) with an idempotent 80% early warning (`$8.00`) and 100%
      Cost Circuit Breaker degrading to Tier 3 (KB search-only) / Tier 4 (receptionist).
    """

    MAX_DAILY_BUCKETS_RETAINED = 7

    def __init__(
        self,
        settings: Settings | None = None,
        date_provider: Callable[[], dt.date] | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._date_provider = date_provider or get_cairo_today
        self._lock = threading.RLock()

        self._sessions: OrderedDict[str, _SessionLedger] = OrderedDict()
        self._daily_buckets: OrderedDict[str, _DailyBucket] = OrderedDict()
        self.recent_alerts: deque[FinOpsAlert] = deque(maxlen=100)
        self._alert_callbacks: list[Callable[[FinOpsAlert], None]] = []

    def reset(self) -> None:
        """Clear all session ledgers, daily spend buckets, and alerts (for isolated tests)."""
        with self._lock:
            self._sessions.clear()
            self._daily_buckets.clear()
            self.recent_alerts.clear()

    def register_alert_callback(self, callback: Callable[[FinOpsAlert], None]) -> None:
        """Register a synchronous callback invoked whenever an 80% or 100% FinOpsAlert fires."""
        with self._lock:
            self._alert_callbacks.append(callback)

    def _current_cairo_date_str(self) -> str:
        return self._date_provider().isoformat()

    def _get_or_create_daily_bucket(self, cairo_date: str) -> _DailyBucket:
        bucket = self._daily_buckets.get(cairo_date)
        if bucket is None:
            bucket = _DailyBucket(cairo_date=cairo_date)
            self._daily_buckets[cairo_date] = bucket
            while len(self._daily_buckets) > self.MAX_DAILY_BUCKETS_RETAINED:
                self._daily_buckets.popitem(last=False)
        else:
            self._daily_buckets.move_to_end(cairo_date)
        return bucket

    def _get_or_create_session_ledger(self, session_id: str) -> _SessionLedger:
        ledger = self._sessions.get(session_id)
        if ledger is None:
            ledger = _SessionLedger(session_id=session_id)
            self._sessions[session_id] = ledger
            max_sessions = max(1, int(self.settings.finops_max_tracked_sessions))
            while len(self._sessions) > max_sessions:
                self._sessions.popitem(last=False)
        else:
            self._sessions.move_to_end(session_id)
        return ledger

    def _resolve_stage_max_tokens(self, stage: Any, requested_max_tokens: int | None) -> int:
        stage_val = getattr(stage, "value", str(stage)).lower()
        limit = (
            int(self.settings.voice_max_tokens)
            if stage_val == "dialogue"
            else int(self.settings.stage_max_tokens)
        )
        if requested_max_tokens is not None and requested_max_tokens > 0:
            return min(int(requested_max_tokens), limit)
        return limit

    def get_session_snapshot(self, session_id: str | None = None) -> CallBudgetSnapshot | None:
        """Return the current CallBudgetSnapshot for `session_id` (or active context), if tracked."""
        eff_sid = resolve_finops_session_id(session_id)
        if not eff_sid:
            return None
        with self._lock:
            ledger = self._sessions.get(eff_sid)
            if ledger is None:
                return CallBudgetSnapshot(
                    session_id=eff_sid,
                    budget_tokens=int(self.settings.finops_call_token_budget),
                    remaining_tokens=int(self.settings.finops_call_token_budget),
                )
            return ledger.to_snapshot(
                budget_tokens=int(self.settings.finops_call_token_budget),
                min_turn_tokens=int(self.settings.finops_min_turn_tokens),
            )

    def get_daily_snapshot(self, cairo_date: str | None = None) -> DailySpendSnapshot:
        """Return the DailySpendSnapshot for `cairo_date` (defaults to today in Cairo time)."""
        with self._lock:
            date_key = cairo_date or self._current_cairo_date_str()
            bucket = self._get_or_create_daily_bucket(date_key)
            return bucket.to_snapshot(
                daily_cap_usd=float(self.settings.finops_daily_spend_cap_usd),
                alert_ratio=float(self.settings.finops_daily_alert_ratio),
            )

    @property
    def tracked_sessions_count(self) -> int:
        """Return number of session ledgers currently held in the bounded LRU."""
        with self._lock:
            return len(self._sessions)

    def check_budget(
        self,
        stage: Any,
        requested_max_tokens: int | None = None,
        session_id: str | None = None,
    ) -> FinOpsDecision:
        """
        Evaluate whether an incoming LLM call is permitted under the daily spend cap
        and per-call token budget, clamping `effective_max_tokens` when near the call limit.
        """
        stage_val = getattr(stage, "value", str(stage)).lower()
        base_max_tokens = self._resolve_stage_max_tokens(stage_val, requested_max_tokens)
        eff_sid = resolve_finops_session_id(session_id)

        with self._lock:
            cairo_date = self._current_cairo_date_str()
            bucket = self._get_or_create_daily_bucket(cairo_date)
            daily_cap = float(self.settings.finops_daily_spend_cap_usd)
            call_budget = int(self.settings.finops_call_token_budget)
            min_turn = int(self.settings.finops_min_turn_tokens)

            ledger = self._sessions.get(eff_sid) if eff_sid else None
            used_tokens = ledger.total_tokens if ledger is not None else 0
            remaining_tokens = max(0, call_budget - used_tokens)

            if not self.settings.finops_enabled:
                return FinOpsDecision(
                    allowed=True,
                    status=FinOpsGateStatus.ALLOWED,
                    stage=stage_val,
                    session_id=eff_sid,
                    requested_max_tokens=base_max_tokens,
                    effective_max_tokens=base_max_tokens,
                    clamped_by_call_budget=False,
                    call_tokens_used=used_tokens,
                    call_tokens_remaining=remaining_tokens,
                    daily_spend_usd=round(bucket.spend_usd, 8),
                    daily_cap_usd=daily_cap,
                    cairo_date=cairo_date,
                )

            # 1. Check Daily Spend Cap ($10.00/day Cost Circuit Breaker)
            if bucket.breaker_100_tripped or bucket.spend_usd >= daily_cap:
                bucket.breaker_100_tripped = True
                return FinOpsDecision(
                    allowed=False,
                    status=FinOpsGateStatus.DAILY_CAP_EXCEEDED,
                    stage=stage_val,
                    session_id=eff_sid,
                    requested_max_tokens=base_max_tokens,
                    effective_max_tokens=0,
                    clamped_by_call_budget=False,
                    call_tokens_used=used_tokens,
                    call_tokens_remaining=remaining_tokens,
                    daily_spend_usd=round(bucket.spend_usd, 8),
                    daily_cap_usd=daily_cap,
                    cairo_date=cairo_date,
                    reason="daily_cost_cap_exceeded",
                )

            # 2. Check Per-Call Cumulative Token Budget (8,000 tokens/call)
            if eff_sid is not None:
                if used_tokens >= call_budget or remaining_tokens < min_turn:
                    return FinOpsDecision(
                        allowed=False,
                        status=FinOpsGateStatus.CALL_BUDGET_EXCEEDED,
                        stage=stage_val,
                        session_id=eff_sid,
                        requested_max_tokens=base_max_tokens,
                        effective_max_tokens=0,
                        clamped_by_call_budget=False,
                        call_tokens_used=used_tokens,
                        call_tokens_remaining=remaining_tokens,
                        daily_spend_usd=round(bucket.spend_usd, 8),
                        daily_cap_usd=daily_cap,
                        cairo_date=cairo_date,
                        reason="call_token_budget_exceeded",
                    )

                if remaining_tokens < base_max_tokens:
                    return FinOpsDecision(
                        allowed=True,
                        status=FinOpsGateStatus.ALLOWED,
                        stage=stage_val,
                        session_id=eff_sid,
                        requested_max_tokens=base_max_tokens,
                        effective_max_tokens=remaining_tokens,
                        clamped_by_call_budget=True,
                        call_tokens_used=used_tokens,
                        call_tokens_remaining=remaining_tokens,
                        daily_spend_usd=round(bucket.spend_usd, 8),
                        daily_cap_usd=daily_cap,
                        cairo_date=cairo_date,
                    )

            return FinOpsDecision(
                allowed=True,
                status=FinOpsGateStatus.ALLOWED,
                stage=stage_val,
                session_id=eff_sid,
                requested_max_tokens=base_max_tokens,
                effective_max_tokens=base_max_tokens,
                clamped_by_call_budget=False,
                call_tokens_used=used_tokens,
                call_tokens_remaining=remaining_tokens,
                daily_spend_usd=round(bucket.spend_usd, 8),
                daily_cap_usd=daily_cap,
                cairo_date=cairo_date,
            )

    def record_usage(
        self,
        model: str | None,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        session_id: str | None = None,
        total_tokens: int | None = None,
        cost_usd: float | None = None,
    ) -> tuple[CallBudgetSnapshot | None, DailySpendSnapshot]:
        """
        Record token usage and USD cost for a completed (or partially completed) LLM call.
        Automatically evaluates 80% warning and 100% daily cap circuit breaker thresholds.
        """
        p_tok = max(0, int(prompt_tokens))
        c_tok = max(0, int(completion_tokens))
        t_tok = max(0, int(total_tokens)) if total_tokens is not None else (p_tok + c_tok)
        eff_cost = (
            max(0.0, float(cost_usd))
            if cost_usd is not None
            else estimate_llm_cost_usd(model, p_tok, c_tok, settings=self.settings)
        )
        eff_sid = resolve_finops_session_id(session_id)

        emitted_alerts: list[FinOpsAlert] = []
        callbacks_to_run: list[Callable[[FinOpsAlert], None]] = []

        with self._lock:
            cairo_date = self._current_cairo_date_str()
            bucket = self._get_or_create_daily_bucket(cairo_date)
            bucket.prompt_tokens += p_tok
            bucket.completion_tokens += c_tok
            bucket.total_tokens += t_tok
            bucket.spend_usd = round(bucket.spend_usd + eff_cost, 8)
            bucket.requests_count += 1

            daily_cap = float(self.settings.finops_daily_spend_cap_usd)
            alert_ratio = float(self.settings.finops_daily_alert_ratio)
            alert_threshold = round(daily_cap * alert_ratio, 8)
            ratio = (bucket.spend_usd / daily_cap) if daily_cap > 0 else 0.0

            # Check 80% early warning threshold (once per Cairo day)
            if not bucket.alert_80_emitted and bucket.spend_usd >= alert_threshold:
                bucket.alert_80_emitted = True
                alert_80 = FinOpsAlert(
                    cairo_date=cairo_date,
                    level=AlertLevel.WARNING_80_PERCENT,
                    spend_usd=bucket.spend_usd,
                    daily_cap_usd=daily_cap,
                    spend_ratio=round(ratio, 4),
                    message=(
                        f"FinOps 80% daily spend alert for {cairo_date}: "
                        f"${bucket.spend_usd:.4f} / ${daily_cap:.2f} ({ratio * 100:.1f}%)"
                    ),
                )
                self.recent_alerts.append(alert_80)
                emitted_alerts.append(alert_80)

            # Check 100% Cost Circuit Breaker threshold (once per Cairo day)
            if not bucket.breaker_100_tripped and bucket.spend_usd >= daily_cap:
                bucket.breaker_100_tripped = True
                alert_100 = FinOpsAlert(
                    cairo_date=cairo_date,
                    level=AlertLevel.CRITICAL_100_PERCENT,
                    spend_usd=bucket.spend_usd,
                    daily_cap_usd=daily_cap,
                    spend_ratio=round(ratio, 4),
                    message=(
                        f"FinOps 100% daily spend cap breached for {cairo_date}: "
                        f"${bucket.spend_usd:.4f} / ${daily_cap:.2f}. "
                        "Cost Circuit Breaker OPEN (degrading to Tier 3 / Tier 4)."
                    ),
                )
                self.recent_alerts.append(alert_100)
                emitted_alerts.append(alert_100)

            call_snap: CallBudgetSnapshot | None = None
            if eff_sid is not None:
                ledger = self._get_or_create_session_ledger(eff_sid)
                ledger.prompt_tokens += p_tok
                ledger.completion_tokens += c_tok
                ledger.total_tokens += t_tok
                ledger.total_cost_usd = round(ledger.total_cost_usd + eff_cost, 8)
                ledger.turns_count += 1
                call_snap = ledger.to_snapshot(
                    budget_tokens=int(self.settings.finops_call_token_budget),
                    min_turn_tokens=int(self.settings.finops_min_turn_tokens),
                )

            daily_snap = bucket.to_snapshot(daily_cap_usd=daily_cap, alert_ratio=alert_ratio)
            if emitted_alerts and self._alert_callbacks:
                callbacks_to_run = list(self._alert_callbacks)

        # Log and invoke callbacks outside the lock
        for alert in emitted_alerts:
            logger.warning(alert.message)
            for cb in callbacks_to_run:
                try:
                    cb(alert)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"FinOps alert callback error: {exc}")

        return call_snap, daily_snap


# ==============================================================================
# 4. Schema-Aware Tool Payload Pruner (R14.4 / R4)
# ==============================================================================

# Essential top-level keys inside `ToolResult.data` per clinic tool
TOOL_DATA_ALLOWLISTS: dict[str, frozenset[str]] = {
    "check_doctor_availability": frozenset(
        {
            "found",
            "doctor_id",
            "doctor_name",
            "title",
            "specialty",
            "date",
            "day_of_week",
            "shift_start",
            "shift_end",
            "available_slots",
            "booked_count",
            "max_capacity",
            "is_full",
            "examination_fee_egp",
            "consultation_fee_egp",
            "doctors",
            "schedules",
            "next_available_dates",
        }
    ),
    "book_appointment": frozenset(
        {
            "booking_code",
            "appointment_id",
            "queue_number",
            "doctor_id",
            "doctor_name",
            "specialty",
            "appointment_date",
            "date",
            "shift_start",
            "shift_end",
            "visit_type",
            "fee_egp",
            "status",
            "idempotent_replay",
        }
    ),
    "manage_appointment": frozenset(
        {
            "action",
            "booking_code",
            "appointment_id",
            "queue_number",
            "doctor_id",
            "doctor_name",
            "specialty",
            "appointment_date",
            "date",
            "new_date",
            "shift_start",
            "shift_end",
            "visit_type",
            "fee_egp",
            "status",
            "appointments",
        }
    ),
    "search_clinic_knowledge": frozenset(
        {
            "found",
            "category",
            "top_score",
            "results",
        }
    ),
    "transfer_to_receptionist": frozenset(
        {
            "handoff_id",
            "alert_id",
            "priority",
            "reason",
            "department",
            "reception_open",
            "emergency_detected",
            "emergency_phone",
        }
    ),
}

# Essential keys retained inside nested list dicts (e.g. `doctors`, `schedules`, `appointments`, `results`)
_NESTED_ITEM_ALLOWLIST: frozenset[str] = frozenset(
    {
        "doctor_id",
        "doctor_name",
        "name_ar",
        "title",
        "specialty",
        "specialty_ar",
        "date",
        "appointment_date",
        "day_of_week",
        "shift_start",
        "shift_end",
        "available_slots",
        "max_capacity",
        "is_full",
        "examination_fee_egp",
        "consultation_fee_egp",
        "fee_egp",
        "booking_code",
        "appointment_id",
        "queue_number",
        "visit_type",
        "status",
        "section",
        "content",
        "text",
        "category",
        "score",
    }
)


def _truncate_str(val: str, max_chars: int) -> str:
    if len(val) <= max_chars:
        return val
    if max_chars <= 3:
        return val[:max_chars]
    return val[: max_chars - 3] + "..."


def _prune_value(
    val: Any,
    *,
    max_list_items: int,
    max_field_chars: int,
    depth: int = 0,
) -> Any:
    """Recursively prune values inside an allowlisted tool data dictionary."""
    if val is None or isinstance(val, (bool, int, float)):
        return val
    if isinstance(val, str):
        return _truncate_str(val, max_field_chars)
    if isinstance(val, (dt.date, dt.datetime, dt.time)):
        return val.isoformat()
    if isinstance(val, Enum):
        return val.value
    if isinstance(val, list):
        sliced = val[:max_list_items]
        return [
            _prune_value(
                item,
                max_list_items=max_list_items,
                max_field_chars=max_field_chars,
                depth=depth + 1,
            )
            for item in sliced
        ]
    if isinstance(val, dict):
        if depth >= 2:
            # Avoid deep nesting bloat
            return _truncate_str(
                json.dumps(val, ensure_ascii=False, default=str),
                max_field_chars,
            )
        pruned_dict: dict[str, Any] = {}
        for k, v in val.items():
            key_str = str(k)
            if depth > 0 and key_str not in _NESTED_ITEM_ALLOWLIST:
                continue
            if v is None:
                continue
            pruned_dict[key_str] = _prune_value(
                v,
                max_list_items=max_list_items,
                max_field_chars=max_field_chars,
                depth=depth + 1,
            )
        return pruned_dict
    return _truncate_str(str(val), max_field_chars)


def prune_tool_payload(
    tool_name: str,
    payload: ToolResult | dict[str, Any] | str,
    *,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """
    Deterministically prune a tool execution output before appending to LLM conversation state (R14.4).

    Preserves:
    - `success` (bool)
    - `message` (str, voice-friendly summary)
    - `error` (str | None, only if non-empty)
    - `data` (dict filtered to essential per-tool allowlisted keys, with list and string caps)
    """
    cfg = settings or get_settings()
    max_items = int(cfg.finops_max_tool_list_items)
    max_field_chars = int(cfg.finops_max_tool_field_chars)

    if isinstance(payload, ToolResult):
        raw_dict: dict[str, Any] = payload.model_dump()
    elif isinstance(payload, dict):
        raw_dict = dict(payload)
    elif isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            raw_dict = parsed if isinstance(parsed, dict) else {"success": True, "message": payload}
        except (ValueError, TypeError):
            raw_dict = {"success": True, "message": payload}
    else:
        raw_dict = {"success": True, "message": str(payload)}

    norm_tool = (tool_name or "").strip().lower()
    allowlist = TOOL_DATA_ALLOWLISTS.get(norm_tool)

    success = bool(raw_dict.get("success", True))
    message = _truncate_str(str(raw_dict.get("message", "") or ""), max_field_chars)
    error_val = raw_dict.get("error")

    out: dict[str, Any] = {
        "success": success,
        "message": message,
    }
    if error_val:
        out["error"] = _truncate_str(str(error_val), max_field_chars)

    raw_data = raw_dict.get("data")
    if isinstance(raw_data, dict) and raw_data:
        pruned_data: dict[str, Any] = {}
        for k, v in raw_data.items():
            key_str = str(k)
            if v is None:
                continue
            if allowlist is not None and key_str not in allowlist:
                continue
            if allowlist is None and key_str not in _NESTED_ITEM_ALLOWLIST:
                continue
            pruned_data[key_str] = _prune_value(
                v,
                max_list_items=max_items,
                max_field_chars=max_field_chars,
                depth=0,
            )
        if pruned_data:
            out["data"] = pruned_data

    return out


def format_pruned_tool_message(
    tool_name: str,
    payload: ToolResult | dict[str, Any] | str,
    *,
    settings: Settings | None = None,
) -> str:
    """
    Prune a tool payload and serialize it to a compact JSON string guaranteed not to exceed
    `settings.finops_max_tool_payload_chars` (default: 1,200 chars).
    """
    cfg = settings or get_settings()
    max_total_chars = int(cfg.finops_max_tool_payload_chars)
    pruned = prune_tool_payload(tool_name, payload, settings=cfg)
    serialized = json.dumps(pruned, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) <= max_total_chars:
        return serialized

    # Progressive fallback: keep only top-level scalar essentials in `data` + `message`
    if "data" in pruned and isinstance(pruned["data"], dict):
        scalar_data = {
            k: v
            for k, v in pruned["data"].items()
            if isinstance(v, (bool, int, float)) or (isinstance(v, str) and len(v) <= 80)
        }
        pruned["data"] = scalar_data
        serialized = json.dumps(pruned, ensure_ascii=False, separators=(",", ":"))
        if len(serialized) <= max_total_chars:
            return serialized

    # Final fallback: keep `success`, `message` (clamped), and `error`
    minimal: dict[str, Any] = {
        "success": pruned.get("success", True),
        "message": _truncate_str(str(pruned.get("message", "")), max(32, max_total_chars - 64)),
    }
    if "error" in pruned:
        minimal["error"] = _truncate_str(str(pruned["error"]), 64)
    serialized = json.dumps(minimal, ensure_ascii=False, separators=(",", ":"))
    return serialized[:max_total_chars]


# ==============================================================================
# 5. Singleton Factory
# ==============================================================================

_finops_instance: FinOpsController | None = None


def get_finops_controller() -> FinOpsController:
    """Return the global singleton FinOpsController instance."""
    global _finops_instance
    if _finops_instance is None:
        _finops_instance = FinOpsController()
    return _finops_instance
