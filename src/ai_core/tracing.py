"""
Hierarchical LLM Trace Logging & Self-Hosted Langfuse Exporter (Feature 4.6).

Implements an OpenTelemetry-compatible hierarchical span tracer with:
1. 128-bit W3C `trace_id` (32 lowercase hex) and 64-bit `span_id` / `parent_span_id` (16 lowercase hex).
2. `contextvars`-isolated `trace_scope()`, `span_scope()`, and `@traced_span` for zero cross-call contamination.
3. W3C Trace Context v1 (`00-<trace_id>-<span_id>-01`) parsing and header injection (`parse_traceparent`, `format_traceparent`, `inject_trace_headers`).
4. Sub-millisecond (< 1ms hot-path SLA) in-memory span recording with automatic token, USD cost, TTFT, latency, degradation tier, and error taxonomy rollup.
5. Off-hot-path Egyptian PII redaction (`EgyptianPIIRedactor.redact_dict`) prior to ring-buffer storage (`recent_traces`) and asynchronous batch HTTP export to self-hosted Langfuse (`/api/public/ingestion`).
6. Graceful no-op degradation when Langfuse is disabled, unconfigured, or unreachable.
"""

from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import functools
import inspect
import logging
import re
import secrets
import time
import types
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field

from src.ai_core.guardrails import EgyptianPIIRedactor, LlamaGuardVerdict, get_pii_redactor
from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


# ==============================================================================
# 1. Domain Enums & Taxonomies
# ==============================================================================


class SpanKind(str, Enum):
    """Operational stage classification for a hierarchical trace span."""

    TURN = "TURN"
    GUARDRAIL_INPUT = "GUARDRAIL_INPUT"
    GUARDRAIL_OUTPUT = "GUARDRAIL_OUTPUT"
    CACHE = "CACHE"
    ROUTER = "ROUTER"
    LLM = "LLM"
    RAG = "RAG"
    WORKFLOW = "WORKFLOW"
    TOOL = "TOOL"
    SAFETY_ASYNC = "SAFETY_ASYNC"


class SpanStatus(str, Enum):
    """Execution status of a span or root trace."""

    OK = "OK"
    ERROR = "ERROR"
    DEGRADED = "DEGRADED"
    BLOCKED = "BLOCKED"
    BYPASSED = "BYPASSED"


class ErrorCategory(str, Enum):
    """Two-class error taxonomy (infra vs semantic) + security block."""

    NONE = "NONE"
    INFRASTRUCTURE = "INFRASTRUCTURE"  # timeouts, 429, 5xx, connection errors
    SEMANTIC = (
        "SEMANTIC"  # schema validation, step_budget_exhausted, ungrounded fee, gate rejection
    )
    SECURITY_BLOCK = (
        "SECURITY_BLOCK"  # prompt injection, medical advice block, emergency escalation
    )


_INFRA_ERROR_CLASSES: frozenset[str] = frozenset(
    {
        "timeout",
        "connection_error",
        "rate_limit",
        "server_error",
        "all_providers_failed",
        "all_providers_unavailable",
        "degraded_search_only",
        "backend_error",
    }
)

_SECURITY_ERROR_CLASSES: frozenset[str] = frozenset(
    {
        "prompt_injection",
        "medical_diagnosis_or_prescription",
        "emergency_detected",
        "emergency",
        "system_or_secret_leak",
        "unsafe_code_or_sql",
        "medical_prescription",
        "medical_diagnosis",
    }
)


def classify_trace_error(error_class: str | None) -> ErrorCategory:
    """Classify an error_class string into ErrorCategory."""
    if not error_class:
        return ErrorCategory.NONE
    norm = error_class.strip().lower()
    if norm in _SECURITY_ERROR_CLASSES:
        return ErrorCategory.SECURITY_BLOCK
    if norm in _INFRA_ERROR_CLASSES:
        return ErrorCategory.INFRASTRUCTURE
    return ErrorCategory.SEMANTIC


# Priority order for rolling up degradation tiers (higher index = more degraded)
_DEGRADATION_PRIORITY: dict[str, int] = {
    "TIER_1_PRIMARY": 1,
    "TIER_2_BACKUP": 2,
    "TIER_3_SEARCH_ONLY": 3,
    "TIER_4_HUMAN_ESCALATION": 4,
}


# ==============================================================================
# 2. W3C Trace Context (`traceparent`) Utilities
# ==============================================================================

_W3C_TRACEPARENT_RE = re.compile(
    r"^\s*([0-9a-f]{2})-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})\s*$",
    re.IGNORECASE,
)


class TraceParent(BaseModel):
    """Parsed W3C Trace Context v1 header (`00-<trace_id>-<span_id>-<flags>`)."""

    model_config = ConfigDict(extra="forbid")

    version: str = "00"
    trace_id: str
    parent_span_id: str
    flags: str = "01"

    @property
    def sampled(self) -> bool:
        """Return True if the W3C sampled bit (0x01) is set."""
        try:
            return bool(int(self.flags, 16) & 0x01)
        except ValueError:
            return True


def generate_trace_id() -> str:
    """Generate a non-zero 128-bit W3C trace_id (32 lowercase hex chars)."""
    tid = secrets.token_hex(16)
    while tid == "0" * 32:
        tid = secrets.token_hex(16)
    return tid


def generate_span_id() -> str:
    """Generate a non-zero 64-bit W3C span_id (16 lowercase hex chars)."""
    sid = secrets.token_hex(8)
    while sid == "0" * 16:
        sid = secrets.token_hex(8)
    return sid


def format_traceparent(
    trace_id: str | None = None,
    span_id: str | None = None,
    sampled: bool = True,
) -> str:
    """
    Format a W3C Trace Context v1 `traceparent` header string:
    `00-<32-hex-trace-id>-<16-hex-span-id>-<01|00>`.
    If `trace_id` or `span_id` are omitted, resolves from the active `contextvars` context.
    """
    active_trace = get_current_trace()
    active_span = get_current_span()

    eff_trace_id = trace_id or (active_trace.trace_id if active_trace else generate_trace_id())
    eff_span_id = span_id or (
        active_span.span_id
        if active_span
        else (active_trace.root_span_id if active_trace else generate_span_id())
    )
    flags = "01" if sampled else "00"
    return f"00-{eff_trace_id.lower()}-{eff_span_id.lower()}-{flags}"


def parse_traceparent(header: str | None) -> TraceParent | None:
    """
    Parse and validate a W3C `traceparent` header string.
    Returns `None` if empty, malformed, version `ff`, or all-zero trace_id / span_id.
    """
    if not header or not isinstance(header, str):
        return None
    match = _W3C_TRACEPARENT_RE.match(header)
    if not match:
        return None

    version, trace_id, span_id, flags = (g.lower() for g in match.groups())
    if version == "ff":
        return None
    if trace_id == "0" * 32 or span_id == "0" * 16:
        return None

    return TraceParent(
        version=version,
        trace_id=trace_id,
        parent_span_id=span_id,
        flags=flags,
    )


def inject_trace_headers(headers: dict[str, str] | None = None) -> dict[str, str]:
    """
    Inject the active W3C `traceparent` header into an outbound HTTP/RPC headers dict.
    """
    out = dict(headers) if headers else {}
    active_trace = get_current_trace()
    if active_trace is not None:
        out["traceparent"] = format_traceparent(
            trace_id=active_trace.trace_id,
            span_id=get_current_span_id() or active_trace.root_span_id,
        )
    return out


# ==============================================================================
# 3. Deterministic LLM Token Cost Calculator
# ==============================================================================


def estimate_llm_cost_usd(
    model: str | None,
    prompt_tokens: int,
    completion_tokens: int,
    settings: Settings | None = None,
) -> float:
    """
    Deterministically calculate estimated USD cost for an LLM call using
    per-1M-token rates in `settings.llm_cost_per_1m_tokens`.
    """
    if prompt_tokens <= 0 and completion_tokens <= 0:
        return 0.0

    cfg = settings or get_settings()
    price_table = cfg.llm_cost_per_1m_tokens
    model_key = (model or "").strip()

    rates = price_table.get(model_key)
    if rates is None and "/" in model_key:
        short_key = model_key.split("/", 1)[1]
        rates = price_table.get(short_key)
    if rates is None:
        rates = price_table.get("default", {"prompt": 0.50, "completion": 0.80})

    prompt_rate = float(rates.get("prompt", 0.0))
    completion_rate = float(rates.get("completion", 0.0))

    cost = (max(0, prompt_tokens) * prompt_rate / 1_000_000.0) + (
        max(0, completion_tokens) * completion_rate / 1_000_000.0
    )
    return round(cost, 8)


# ==============================================================================
# 4. Pydantic Span & Trace Data Models
# ==============================================================================


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class SpanRecord(BaseModel):
    """Immutable-ready record representing a single span in a hierarchical trace."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(description="32-char lowercase hex W3C trace ID.")
    span_id: str = Field(description="16-char lowercase hex W3C span ID.")
    parent_span_id: str | None = Field(
        default=None,
        description="16-char lowercase hex parent span ID (or root span ID).",
    )
    name: str = Field(description="Human-readable span operation name.")
    kind: SpanKind = Field(default=SpanKind.TOOL, description="Operational stage classification.")
    status: SpanStatus = Field(default=SpanStatus.OK, description="Span outcome status.")
    start_time_iso: str = Field(default_factory=_utc_now_iso, description="UTC ISO-8601 start.")
    end_time_iso: str = Field(default_factory=_utc_now_iso, description="UTC ISO-8601 end.")
    latency_ms: float = Field(default=0.0, ge=0.0, description="Total span duration in ms.")
    ttft_ms: float | None = Field(
        default=None,
        description="Time-to-First-Token in ms (for LLM streaming spans).",
    )
    provider: str | None = Field(default=None, description="LLM provider name (e.g. groq, gemini).")
    model: str | None = Field(default=None, description="Model identifier.")
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    cost_usd: float = Field(default=0.0, ge=0.0, description="Estimated USD cost for this span.")
    degradation_tier: str | None = Field(
        default=None, description="Degradation tier if applicable."
    )
    error_category: ErrorCategory = Field(default=ErrorCategory.NONE)
    error_class: str | None = Field(default=None)
    error_message: str | None = Field(default=None)
    input_payload: Any = Field(default=None, description="PII-redacted span input.")
    output_payload: Any = Field(default=None, description="PII-redacted span output.")
    attributes: dict[str, Any] = Field(
        default_factory=dict,
        description="PII-redacted structured span metadata.",
    )


class TraceRecord(BaseModel):
    """Root hierarchical trace record for a complete conversational turn."""

    model_config = ConfigDict(extra="forbid")

    trace_id: str = Field(description="32-char lowercase hex W3C trace ID.")
    root_span_id: str = Field(description="16-char lowercase hex root turn span ID.")
    parent_span_id: str | None = Field(
        default=None,
        description="Upstream W3C parent_span_id when propagated via traceparent.",
    )
    name: str = Field(default="voice_turn", description="Trace name.")
    session_id: str | None = Field(default=None, description="Call or room session identifier.")
    branch_id: str | None = Field(default=None, description="Clinic tenant/branch identifier.")
    status: SpanStatus = Field(default=SpanStatus.OK)
    start_time_iso: str = Field(default_factory=_utc_now_iso)
    end_time_iso: str = Field(default_factory=_utc_now_iso)
    latency_ms: float = Field(default=0.0, ge=0.0)
    ttft_ms: float | None = Field(default=None)
    total_prompt_tokens: int = Field(default=0, ge=0)
    total_completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)
    total_cost_usd: float = Field(default=0.0, ge=0.0)
    degradation_tier: str = Field(default="TIER_1_PRIMARY")
    error_category: ErrorCategory = Field(default=ErrorCategory.NONE)
    error_class: str | None = Field(default=None)
    input_payload: Any = Field(default=None, description="PII-redacted turn input.")
    output_payload: Any = Field(default=None, description="PII-redacted turn output.")
    metadata: dict[str, Any] = Field(default_factory=dict)
    llama_guard_verdict: dict[str, Any] | None = Field(
        default=None,
        description="Attached off-hot-path AsyncLlamaGuardClassifier verdict.",
    )
    pii_redacted: bool = Field(
        default=False,
        description="True once EgyptianPIIRedactor has scrubbed all payloads.",
    )
    spans: list[SpanRecord] = Field(default_factory=list)


# ==============================================================================
# 5. Hot-Path Mutable Contexts & `contextvars` Isolation (< 0.1ms overhead)
# ==============================================================================


class SpanContext:
    """
    Lightweight mutable span context used on the hot path inside `span_scope()`.
    Avoids heavy serialization or regex scanning until background flush.
    """

    __slots__ = (
        "attributes",
        "completion_tokens",
        "cost_usd",
        "degradation_tier",
        "end_perf",
        "end_time_iso",
        "error_category",
        "error_class",
        "error_message",
        "input_payload",
        "kind",
        "model",
        "name",
        "output_payload",
        "parent_span_id",
        "prompt_tokens",
        "provider",
        "span_id",
        "start_perf",
        "start_time_iso",
        "status",
        "total_tokens",
        "trace_id",
        "ttft_ms",
    )

    def __init__(
        self,
        trace_id: str,
        span_id: str,
        parent_span_id: str | None,
        name: str,
        kind: SpanKind = SpanKind.TOOL,
        input_payload: Any = None,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.parent_span_id = parent_span_id
        self.name = name
        self.kind = kind
        self.status = SpanStatus.OK
        self.start_time_iso = _utc_now_iso()
        self.end_time_iso = self.start_time_iso
        self.start_perf = time.perf_counter()
        self.end_perf = self.start_perf
        self.ttft_ms: float | None = None
        self.provider: str | None = None
        self.model: str | None = None
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.cost_usd: float = 0.0
        self.degradation_tier: str | None = None
        self.error_category: ErrorCategory = ErrorCategory.NONE
        self.error_class: str | None = None
        self.error_message: str | None = None
        self.input_payload: Any = input_payload
        self.output_payload: Any = None
        self.attributes: dict[str, Any] = dict(attributes) if attributes else {}

    def set_input(self, payload: Any) -> None:
        """Set or update the span input payload."""
        self.input_payload = payload

    def set_output(self, payload: Any) -> None:
        """Set or update the span output payload."""
        self.output_payload = payload

    def set_attribute(self, key: str, value: Any) -> None:
        """Attach a key-value attribute to the span."""
        self.attributes[key] = value

    def set_attributes(self, mapping: dict[str, Any]) -> None:
        """Attach multiple key-value attributes to the span."""
        self.attributes.update(mapping)

    def set_status(
        self,
        status: SpanStatus,
        *,
        error_class: str | None = None,
        error_message: str | None = None,
        error_category: ErrorCategory | None = None,
    ) -> None:
        """Update span status and optional error taxonomy."""
        self.status = status
        if error_class is not None:
            self.error_class = error_class
            self.error_category = error_category or classify_trace_error(error_class)
        elif error_category is not None:
            self.error_category = error_category
        if error_message is not None:
            self.error_message = error_message

    def set_usage(
        self,
        *,
        provider: str | None = None,
        model: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        total_tokens: int | None = None,
        ttft_ms: float | None = None,
        degradation_tier: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        """Record LLM token counts, TTFT, provider/model, and calculate USD cost."""
        if provider is not None:
            self.provider = provider
        if model is not None:
            self.model = model
        self.prompt_tokens = max(0, int(prompt_tokens))
        self.completion_tokens = max(0, int(completion_tokens))
        self.total_tokens = (
            max(0, int(total_tokens))
            if total_tokens is not None
            else (self.prompt_tokens + self.completion_tokens)
        )
        if ttft_ms is not None:
            self.ttft_ms = float(ttft_ms)
        if degradation_tier is not None:
            self.degradation_tier = str(degradation_tier)
        self.cost_usd = estimate_llm_cost_usd(
            self.model,
            self.prompt_tokens,
            self.completion_tokens,
            settings=settings,
        )

    def finish(self) -> SpanRecord:
        """Close timing and build a SpanRecord (< 0.01ms via model_construct)."""
        self.end_perf = time.perf_counter()
        self.end_time_iso = _utc_now_iso()
        latency_ms = max(0.0, (self.end_perf - self.start_perf) * 1000.0)
        return SpanRecord.model_construct(
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id,
            name=self.name,
            kind=self.kind,
            status=self.status,
            start_time_iso=self.start_time_iso,
            end_time_iso=self.end_time_iso,
            latency_ms=round(latency_ms, 4),
            ttft_ms=round(self.ttft_ms, 4) if self.ttft_ms is not None else None,
            provider=self.provider,
            model=self.model,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            cost_usd=self.cost_usd,
            degradation_tier=self.degradation_tier,
            error_category=self.error_category,
            error_class=self.error_class,
            error_message=self.error_message,
            input_payload=self.input_payload,
            output_payload=self.output_payload,
            attributes=self.attributes,
        )


class TraceContext:
    """
    Lightweight mutable root trace context bound to a single conversational turn via `contextvars`.
    """

    __slots__ = (
        "branch_id",
        "degradation_tier",
        "end_perf",
        "end_time_iso",
        "error_category",
        "error_class",
        "input_payload",
        "llama_guard_verdict",
        "metadata",
        "name",
        "output_payload",
        "parent_span_id",
        "root_span_id",
        "session_id",
        "spans",
        "start_perf",
        "start_time_iso",
        "status",
        "trace_id",
    )

    def __init__(
        self,
        name: str = "voice_turn",
        *,
        trace_id: str | None = None,
        root_span_id: str | None = None,
        parent_span_id: str | None = None,
        session_id: str | None = None,
        branch_id: str | None = None,
        input_payload: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.trace_id = trace_id or generate_trace_id()
        self.root_span_id = root_span_id or generate_span_id()
        self.parent_span_id = parent_span_id
        self.name = name
        self.session_id = session_id
        self.branch_id = branch_id
        self.status = SpanStatus.OK
        self.start_time_iso = _utc_now_iso()
        self.end_time_iso = self.start_time_iso
        self.start_perf = time.perf_counter()
        self.end_perf = self.start_perf
        self.degradation_tier: str = "TIER_1_PRIMARY"
        self.error_category: ErrorCategory = ErrorCategory.NONE
        self.error_class: str | None = None
        self.input_payload: Any = input_payload
        self.output_payload: Any = None
        self.metadata: dict[str, Any] = dict(metadata) if metadata else {}
        self.llama_guard_verdict: dict[str, Any] | None = None
        self.spans: list[SpanRecord] = []

    def set_input(self, payload: Any) -> None:
        self.input_payload = payload

    def set_output(self, payload: Any) -> None:
        self.output_payload = payload

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    def add_span(self, span: SpanRecord) -> None:
        self.spans.append(span)

    def finish(self) -> TraceRecord:
        """
        Finalize timing and roll up tokens, USD cost, TTFT, degradation tier,
        and error taxonomy from all child spans.
        """
        self.end_perf = time.perf_counter()
        self.end_time_iso = _utc_now_iso()
        latency_ms = max(0.0, (self.end_perf - self.start_perf) * 1000.0)

        total_prompt = 0
        total_completion = 0
        total_tokens = 0
        total_cost = 0.0
        ttft_ms: float | None = None
        highest_tier = self.degradation_tier
        highest_tier_prio = _DEGRADATION_PRIORITY.get(highest_tier, 1)

        derived_status = self.status
        derived_err_cat = self.error_category
        derived_err_cls = self.error_class

        for sp in self.spans:
            total_prompt += sp.prompt_tokens
            total_completion += sp.completion_tokens
            total_tokens += sp.total_tokens
            total_cost += sp.cost_usd

            if sp.ttft_ms is not None and (sp.kind == SpanKind.LLM or ttft_ms is None):
                ttft_ms = sp.ttft_ms

            if sp.degradation_tier:
                prio = _DEGRADATION_PRIORITY.get(sp.degradation_tier, 1)
                if prio > highest_tier_prio:
                    highest_tier_prio = prio
                    highest_tier = sp.degradation_tier

            if sp.status == SpanStatus.BLOCKED and derived_status == SpanStatus.OK:
                derived_status = SpanStatus.BLOCKED
            elif sp.status == SpanStatus.ERROR and derived_status == SpanStatus.OK:
                derived_status = SpanStatus.ERROR
            elif sp.status == SpanStatus.DEGRADED and derived_status == SpanStatus.OK:
                derived_status = SpanStatus.DEGRADED

            if sp.error_class and not derived_err_cls:
                derived_err_cls = sp.error_class
                derived_err_cat = sp.error_category

        if highest_tier_prio > 1 and derived_status == SpanStatus.OK:
            derived_status = SpanStatus.DEGRADED

        return TraceRecord.model_construct(
            trace_id=self.trace_id,
            root_span_id=self.root_span_id,
            parent_span_id=self.parent_span_id,
            name=self.name,
            session_id=self.session_id,
            branch_id=self.branch_id,
            status=derived_status,
            start_time_iso=self.start_time_iso,
            end_time_iso=self.end_time_iso,
            latency_ms=round(latency_ms, 4),
            ttft_ms=round(ttft_ms, 4) if ttft_ms is not None else None,
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_tokens=total_tokens,
            total_cost_usd=round(total_cost, 8),
            degradation_tier=highest_tier,
            error_category=derived_err_cat,
            error_class=derived_err_cls,
            input_payload=self.input_payload,
            output_payload=self.output_payload,
            metadata=self.metadata,
            llama_guard_verdict=self.llama_guard_verdict,
            pii_redacted=False,
            spans=list(self.spans),
        )


# ContextVars for per-task async isolation
_current_trace_var: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "current_trace_context", default=None
)
_current_span_var: contextvars.ContextVar[SpanContext | None] = contextvars.ContextVar(
    "current_span_context", default=None
)


def get_current_trace() -> TraceContext | None:
    """Return the active TraceContext in the current async task, or None."""
    return _current_trace_var.get()


def get_current_span() -> SpanContext | None:
    """Return the active SpanContext in the current async task, or None."""
    return _current_span_var.get()


def get_current_trace_id() -> str | None:
    """Return the active 32-hex trace_id, or None."""
    t = _current_trace_var.get()
    return t.trace_id if t is not None else None


def get_current_span_id() -> str | None:
    """Return the active 16-hex span_id (or root_span_id if at root of trace), or None."""
    s = _current_span_var.get()
    if s is not None:
        return s.span_id
    t = _current_trace_var.get()
    return t.root_span_id if t is not None else None


# ==============================================================================
# 6. Asynchronous Batch Exporter & Self-Hosted Langfuse Client
# ==============================================================================


class AsyncTraceExporter:
    """
    Off-hot-path trace processor and self-hosted Langfuse batch HTTP exporter.

    Guarantees:
    1. Enqueue (`enqueue_trace`) is non-blocking (< 0.05ms on the hot path).
    2. During `flush()`, every trace and span payload is scrubbed via
       `EgyptianPIIRedactor.redact_dict()` BEFORE entering `recent_traces` or HTTP export.
    3. Sends OpenTelemetry/Langfuse batch events (`trace-create`, `generation-create`,
       `span-create`, `score-create`) to `{langfuse_host}/api/public/ingestion`.
    4. Degrades silently to a local no-op when Langfuse is disabled, unconfigured, or unreachable.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        redactor: EgyptianPIIRedactor | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.redactor = redactor or get_pii_redactor()
        self._http_transport = http_transport

        self._pending_traces: deque[TraceRecord] = deque()
        self._pending_events: deque[dict[str, Any]] = deque()
        self.recent_traces: deque[TraceRecord] = deque(
            maxlen=self.settings.tracing_ring_buffer_size
        )
        self._traces_by_id: dict[str, TraceRecord] = {}

        # Telemetry counters
        self.enqueued_count: int = 0
        self.dropped_queue_full_count: int = 0
        self.flushed_traces_count: int = 0
        self.exported_batches_count: int = 0
        self.failed_batches_count: int = 0

        self._flush_lock = asyncio.Lock()
        self._bg_tasks: set[asyncio.Task[Any]] = set()
        self._active_flush_task: asyncio.Task[int] | None = None

    def clear(self) -> None:
        """Reset all in-memory buffers and counters (useful for isolated tests)."""
        self._pending_traces.clear()
        self._pending_events.clear()
        self.recent_traces.clear()
        self._traces_by_id.clear()
        self.enqueued_count = 0
        self.dropped_queue_full_count = 0
        self.flushed_traces_count = 0
        self.exported_batches_count = 0
        self.failed_batches_count = 0

    def enqueue_trace(self, raw_trace: TraceRecord) -> None:
        """
        Non-blocking hot-path enqueue (< 0.05ms).
        Drops oldest pending trace if `tracing_max_queue_size` is reached.
        """
        if not self.settings.tracing_enabled:
            return

        if len(self._pending_traces) >= self.settings.tracing_max_queue_size:
            self._pending_traces.popleft()
            self.dropped_queue_full_count += 1

        self._pending_traces.append(raw_trace)
        self.enqueued_count += 1

    def _sanitize_trace(self, raw: TraceRecord) -> TraceRecord:
        """
        Scrub all PII across the trace and its child spans using `EgyptianPIIRedactor`.
        Executed off the hot path during flush.
        """
        redacted_spans: list[SpanRecord] = []
        for sp in raw.spans:
            redacted_spans.append(
                sp.model_copy(
                    update={
                        "input_payload": self.redactor.redact_dict(sp.input_payload),
                        "output_payload": self.redactor.redact_dict(sp.output_payload),
                        "attributes": self.redactor.redact_dict(sp.attributes),
                        "error_message": (
                            self.redactor.redact(sp.error_message) if sp.error_message else None
                        ),
                    }
                )
            )

        return raw.model_copy(
            update={
                "input_payload": self.redactor.redact_dict(raw.input_payload),
                "output_payload": self.redactor.redact_dict(raw.output_payload),
                "metadata": self.redactor.redact_dict(raw.metadata),
                "llama_guard_verdict": (
                    self.redactor.redact_dict(raw.llama_guard_verdict)
                    if raw.llama_guard_verdict
                    else None
                ),
                "pii_redacted": True,
                "spans": redacted_spans,
            }
        )

    def _build_langfuse_events(self, trace: TraceRecord) -> list[dict[str, Any]]:
        """
        Convert a PII-redacted `TraceRecord` into Langfuse `/api/public/ingestion` batch events:
        - `trace-create` for the root conversational turn
        - `generation-create` for `SpanKind.LLM` and `SpanKind.ROUTER`
        - `span-create` for all other spans (`GUARDRAIL_*`, `CACHE`, `RAG`, `WORKFLOW`, `TOOL`, `SAFETY_ASYNC`)
        """
        events: list[dict[str, Any]] = []
        now_iso = _utc_now_iso()

        events.append(
            {
                "id": str(uuid.uuid4()),
                "timestamp": now_iso,
                "type": "trace-create",
                "body": {
                    "id": trace.trace_id,
                    "name": trace.name,
                    "timestamp": trace.start_time_iso,
                    "sessionId": trace.session_id,
                    "input": trace.input_payload,
                    "output": trace.output_payload,
                    "metadata": {
                        **trace.metadata,
                        "root_span_id": trace.root_span_id,
                        "parent_span_id": trace.parent_span_id,
                        "branch_id": trace.branch_id,
                        "status": trace.status.value,
                        "latency_ms": trace.latency_ms,
                        "ttft_ms": trace.ttft_ms,
                        "total_prompt_tokens": trace.total_prompt_tokens,
                        "total_completion_tokens": trace.total_completion_tokens,
                        "total_tokens": trace.total_tokens,
                        "total_cost_usd": trace.total_cost_usd,
                        "degradation_tier": trace.degradation_tier,
                        "error_category": trace.error_category.value,
                        "error_class": trace.error_class,
                        "pii_redacted": trace.pii_redacted,
                    },
                },
            }
        )

        for sp in trace.spans:
            is_generation = sp.kind in (SpanKind.LLM, SpanKind.ROUTER)
            event_type = "generation-create" if is_generation else "span-create"
            body: dict[str, Any] = {
                "id": sp.span_id,
                "traceId": sp.trace_id,
                "parentObservationId": sp.parent_span_id,
                "name": sp.name,
                "startTime": sp.start_time_iso,
                "endTime": sp.end_time_iso,
                "input": sp.input_payload,
                "output": sp.output_payload,
                "level": "ERROR" if sp.status == SpanStatus.ERROR else "DEFAULT",
                "statusMessage": sp.error_message or sp.error_class,
                "metadata": {
                    **sp.attributes,
                    "kind": sp.kind.value,
                    "status": sp.status.value,
                    "latency_ms": sp.latency_ms,
                    "ttft_ms": sp.ttft_ms,
                    "provider": sp.provider,
                    "degradation_tier": sp.degradation_tier,
                    "error_category": sp.error_category.value,
                    "error_class": sp.error_class,
                    "cost_usd": sp.cost_usd,
                },
            }
            if is_generation:
                body["model"] = sp.model
                body["usage"] = {
                    "input": sp.prompt_tokens,
                    "output": sp.completion_tokens,
                    "total": sp.total_tokens,
                    "unit": "TOKENS",
                    "totalCost": sp.cost_usd,
                }
            events.append(
                {
                    "id": str(uuid.uuid4()),
                    "timestamp": now_iso,
                    "type": event_type,
                    "body": body,
                }
            )

        if trace.llama_guard_verdict is not None:
            events.append(
                {
                    "id": str(uuid.uuid4()),
                    "timestamp": now_iso,
                    "type": "score-create",
                    "body": {
                        "traceId": trace.trace_id,
                        "name": "llama_guard_safe",
                        "value": 1.0 if trace.llama_guard_verdict.get("safe", True) else 0.0,
                        "comment": ",".join(trace.llama_guard_verdict.get("category_codes", []))
                        or "safe",
                    },
                }
            )

        return events

    async def _post_langfuse_batch(self, batch: list[dict[str, Any]]) -> bool:
        """
        Send a batch of Langfuse ingestion events via `httpx.AsyncClient`.
        Returns True on HTTP 2xx, or False on any error/timeout (never raises).
        """
        if not batch or not self.settings.is_langfuse_configured():
            return False

        url = f"{self.settings.langfuse_host.rstrip('/')}/api/public/ingestion"
        auth = (self.settings.langfuse_public_key, self.settings.langfuse_secret_key)

        try:
            async with httpx.AsyncClient(
                transport=self._http_transport,
                timeout=self.settings.tracing_http_timeout_s,
            ) as client:
                resp = await client.post(
                    url,
                    json={"batch": batch},
                    auth=auth,
                    headers={"Content-Type": "application/json"},
                )
                if 200 <= resp.status_code < 300:
                    self.exported_batches_count += 1
                    return True
                logger.warning(
                    "Langfuse batch ingestion returned HTTP %s (degrading to no-op)",
                    resp.status_code,
                )
                self.failed_batches_count += 1
                return False
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Langfuse batch export failed (%s) — degrading gracefully to no-op",
                type(exc).__name__,
            )
            self.failed_batches_count += 1
            return False

    async def flush(self) -> int:
        """
        Drain all pending raw traces, execute mandatory Egyptian PII redaction,
        commit to `recent_traces` ring buffer, and export batches to self-hosted Langfuse
        if configured. Returns the number of traces flushed.
        """
        async with self._flush_lock:
            flushed = 0
            while self._pending_traces:
                raw_trace = self._pending_traces.popleft()
                sanitized = self._sanitize_trace(raw_trace)

                # Evict oldest ID mapping if ring buffer is at capacity
                if (
                    self.recent_traces.maxlen is not None
                    and len(self.recent_traces) >= self.recent_traces.maxlen
                ):
                    oldest = self.recent_traces[0]
                    self._traces_by_id.pop(oldest.trace_id, None)

                self.recent_traces.append(sanitized)
                self._traces_by_id[sanitized.trace_id] = sanitized
                self.flushed_traces_count += 1
                flushed += 1

                if self.settings.is_langfuse_configured():
                    for ev in self._build_langfuse_events(sanitized):
                        self._pending_events.append(ev)

            # Dispatch pending Langfuse events in chunks of `tracing_batch_size`
            if self.settings.is_langfuse_configured() and self._pending_events:
                batch_size = max(1, int(self.settings.tracing_batch_size))
                while self._pending_events:
                    chunk: list[dict[str, Any]] = []
                    while self._pending_events and len(chunk) < batch_size:
                        chunk.append(self._pending_events.popleft())
                    await self._post_langfuse_batch(chunk)
            else:
                self._pending_events.clear()

            return flushed

    def schedule_flush(self) -> asyncio.Task[int] | None:
        """
        Schedule an asynchronous background flush on the running event loop if available,
        coalescing concurrent requests into a single background flush task.
        """
        if self._active_flush_task is not None and not self._active_flush_task.done():
            return self._active_flush_task

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return None

        task = loop.create_task(self.flush())
        self._active_flush_task = task
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def attach_llama_guard_verdict(
        self,
        trace_id: str,
        verdict: LlamaGuardVerdict | dict[str, Any],
    ) -> bool:
        """
        Attach an off-hot-path `LlamaGuardVerdict` to its matching trace (either in
        `recent_traces` or still in `_pending_traces`).
        """
        verdict_dict = (
            verdict.model_dump() if isinstance(verdict, LlamaGuardVerdict) else dict(verdict)
        )
        sanitized_verdict = self.redactor.redact_dict(verdict_dict)

        # 1. Check already-flushed ring buffer
        existing = self._traces_by_id.get(trace_id)
        if existing is not None:
            existing.llama_guard_verdict = sanitized_verdict
            if self.settings.is_langfuse_configured():
                self._pending_events.append(
                    {
                        "id": str(uuid.uuid4()),
                        "timestamp": _utc_now_iso(),
                        "type": "score-create",
                        "body": {
                            "traceId": trace_id,
                            "name": "llama_guard_safe",
                            "value": 1.0 if sanitized_verdict.get("safe", True) else 0.0,
                            "comment": ",".join(sanitized_verdict.get("category_codes", []))
                            or "safe",
                        },
                    }
                )
            return True

        # 2. Check pending queue
        for pending in self._pending_traces:
            if pending.trace_id == trace_id:
                pending.llama_guard_verdict = sanitized_verdict
                return True

        return False

    def get_trace(self, trace_id: str) -> TraceRecord | None:
        """Look up a flushed, PII-redacted TraceRecord by `trace_id`."""
        return self._traces_by_id.get(trace_id)


# ==============================================================================
# 7. Hierarchical Tracer Facade & Context Managers
# ==============================================================================


class HierarchicalTracer:
    """
    Central Hierarchical Tracer managing trace/span lifecycles, `contextvars` state,
    and `AsyncTraceExporter` orchestration.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        exporter: AsyncTraceExporter | None = None,
        redactor: EgyptianPIIRedactor | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.redactor = redactor or get_pii_redactor()
        self.exporter = exporter or AsyncTraceExporter(
            settings=self.settings,
            redactor=self.redactor,
            http_transport=http_transport,
        )

    @property
    def recent_traces(self) -> deque[TraceRecord]:
        """Return bounded ring buffer of PII-redacted TraceRecords."""
        return self.exporter.recent_traces

    def get_trace(self, trace_id: str) -> TraceRecord | None:
        """Retrieve a flushed TraceRecord by `trace_id`."""
        return self.exporter.get_trace(trace_id)

    async def flush(self) -> int:
        """Flush all pending traces through PII redaction and batch export."""
        return await self.exporter.flush()

    def clear(self) -> None:
        """Clear all recorded traces and reset counters."""
        self.exporter.clear()

    def attach_llama_guard_verdict(
        self,
        trace_id: str,
        verdict: LlamaGuardVerdict | dict[str, Any],
    ) -> bool:
        """Attach an async Llama Guard safety verdict to a trace by `trace_id`."""
        return self.exporter.attach_llama_guard_verdict(trace_id, verdict)

    def _open_trace_context(
        self,
        name: str = "voice_turn",
        *,
        trace_id: str | None = None,
        traceparent: str | None = None,
        session_id: str | None = None,
        branch_id: str | None = None,
        input_payload: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> TraceContext:
        parsed_tp = parse_traceparent(traceparent) if traceparent else None
        eff_trace_id = trace_id or (parsed_tp.trace_id if parsed_tp else generate_trace_id())
        eff_parent_id = parsed_tp.parent_span_id if parsed_tp else None

        return TraceContext(
            name=name,
            trace_id=eff_trace_id,
            parent_span_id=eff_parent_id,
            session_id=session_id,
            branch_id=branch_id,
            input_payload=input_payload,
            metadata=metadata,
        )

    @contextmanager
    def sync_trace_scope(
        self,
        name: str = "voice_turn",
        *,
        trace_id: str | None = None,
        traceparent: str | None = None,
        session_id: str | None = None,
        branch_id: str | None = None,
        input_payload: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[TraceContext]:
        """Synchronous context manager for a hierarchical turn trace."""
        t_ctx = self._open_trace_context(
            name=name,
            trace_id=trace_id,
            traceparent=traceparent,
            session_id=session_id,
            branch_id=branch_id,
            input_payload=input_payload,
            metadata=metadata,
        )
        if not self.settings.tracing_enabled:
            yield t_ctx
            return

        trace_token = _current_trace_var.set(t_ctx)
        span_token = _current_span_var.set(None)
        try:
            yield t_ctx
        except Exception as exc:
            t_ctx.status = SpanStatus.ERROR
            t_ctx.error_class = type(exc).__name__
            t_ctx.error_category = classify_trace_error(t_ctx.error_class)
            raise
        finally:
            _current_span_var.reset(span_token)
            _current_trace_var.reset(trace_token)
            raw_record = t_ctx.finish()
            self.exporter.enqueue_trace(raw_record)
            self.exporter.schedule_flush()

    @asynccontextmanager
    async def trace_scope(
        self,
        name: str = "voice_turn",
        *,
        trace_id: str | None = None,
        traceparent: str | None = None,
        session_id: str | None = None,
        branch_id: str | None = None,
        input_payload: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[TraceContext]:
        """Async context manager for a hierarchical turn trace (< 0.1ms hot-path overhead)."""
        with self.sync_trace_scope(
            name=name,
            trace_id=trace_id,
            traceparent=traceparent,
            session_id=session_id,
            branch_id=branch_id,
            input_payload=input_payload,
            metadata=metadata,
        ) as t_ctx:
            yield t_ctx

    @contextmanager
    def span_scope(
        self,
        name: str,
        *,
        kind: SpanKind = SpanKind.TOOL,
        input_payload: Any = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[SpanContext]:
        """
        Open a nested child span within the active trace context.
        If no trace context is active or `tracing_enabled=False`, yields a lightweight
        detached `SpanContext` (strict no-op with zero side effects).
        """
        active_trace = _current_trace_var.get()
        if active_trace is None or not self.settings.tracing_enabled:
            dummy = SpanContext(
                trace_id="0" * 32,
                span_id="0" * 16,
                parent_span_id=None,
                name=name,
                kind=kind,
                input_payload=input_payload,
                attributes=attributes,
            )
            yield dummy
            return

        parent_span = _current_span_var.get()
        parent_id = parent_span.span_id if parent_span is not None else active_trace.root_span_id

        s_ctx = SpanContext(
            trace_id=active_trace.trace_id,
            span_id=generate_span_id(),
            parent_span_id=parent_id,
            name=name,
            kind=kind,
            input_payload=input_payload,
            attributes=attributes,
        )
        span_token = _current_span_var.set(s_ctx)
        try:
            yield s_ctx
        except Exception as exc:
            if s_ctx.status == SpanStatus.OK:
                s_ctx.set_status(
                    SpanStatus.ERROR,
                    error_class=type(exc).__name__,
                    error_message=str(exc),
                )
            raise
        finally:
            _current_span_var.reset(span_token)
            active_trace.add_span(s_ctx.finish())


# ==============================================================================
# 8. Singleton Accessors & Convenience Decorators
# ==============================================================================

_tracer_instance: HierarchicalTracer | None = None


def get_tracer() -> HierarchicalTracer:
    """Return global singleton `HierarchicalTracer` instance."""
    global _tracer_instance
    if _tracer_instance is None:
        _tracer_instance = HierarchicalTracer()
    return _tracer_instance


class _DualTraceScopeContextManager:
    """
    Supports both `async with trace_scope(...)` and `with trace_scope(...)` seamlessly.
    """

    def __init__(
        self,
        name: str = "voice_turn",
        *,
        tracer: HierarchicalTracer | None = None,
        trace_id: str | None = None,
        traceparent: str | None = None,
        session_id: str | None = None,
        branch_id: str | None = None,
        input_payload: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._tracer = tracer or get_tracer()
        self._kwargs: dict[str, Any] = {
            "name": name,
            "trace_id": trace_id,
            "traceparent": traceparent,
            "session_id": session_id,
            "branch_id": branch_id,
            "input_payload": input_payload,
            "metadata": metadata,
        }
        self._cm: Any = None

    def __enter__(self) -> TraceContext:
        self._cm = self._tracer.sync_trace_scope(**self._kwargs)
        return self._cm.__enter__()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> Any:
        return self._cm.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> TraceContext:
        self._cm = self._tracer.trace_scope(**self._kwargs)
        return await self._cm.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> Any:
        return await self._cm.__aexit__(exc_type, exc_val, exc_tb)


def trace_scope(
    name: str = "voice_turn",
    *,
    tracer: HierarchicalTracer | None = None,
    trace_id: str | None = None,
    traceparent: str | None = None,
    session_id: str | None = None,
    branch_id: str | None = None,
    input_payload: Any = None,
    metadata: dict[str, Any] | None = None,
) -> _DualTraceScopeContextManager:
    """
    Open a root conversational turn trace scope (works with both `async with` and `with`).
    """
    return _DualTraceScopeContextManager(
        name=name,
        tracer=tracer,
        trace_id=trace_id,
        traceparent=traceparent,
        session_id=session_id,
        branch_id=branch_id,
        input_payload=input_payload,
        metadata=metadata,
    )


@contextmanager
def span_scope(
    name: str,
    *,
    kind: SpanKind = SpanKind.TOOL,
    input_payload: Any = None,
    attributes: dict[str, Any] | None = None,
    tracer: HierarchicalTracer | None = None,
) -> Iterator[SpanContext]:
    """Open a child span inside the active trace (no-op if no trace is active)."""
    eff_tracer = tracer or get_tracer()
    with eff_tracer.span_scope(
        name=name,
        kind=kind,
        input_payload=input_payload,
        attributes=attributes,
    ) as sp:
        yield sp


def traced_span(
    name: str | None = None,
    *,
    kind: SpanKind = SpanKind.TOOL,
) -> Callable[[F], F]:
    """
    Decorator wrapping sync or async functions in a child `span_scope`.
    """

    def decorator(func: F) -> F:
        span_name = name or func.__name__

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if _current_trace_var.get() is None:
                    return await func(*args, **kwargs)
                with span_scope(span_name, kind=kind) as sp:
                    res = await func(*args, **kwargs)
                    sp.set_output(res)
                    return res

            return async_wrapper  # type: ignore[return-value]

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if _current_trace_var.get() is None:
                return func(*args, **kwargs)
            with span_scope(span_name, kind=kind) as sp:
                res = func(*args, **kwargs)
                sp.set_output(res)
                return res

        return sync_wrapper  # type: ignore[return-value]

    return decorator


__all__ = [
    "AsyncTraceExporter",
    "ErrorCategory",
    "HierarchicalTracer",
    "SpanContext",
    "SpanKind",
    "SpanRecord",
    "SpanStatus",
    "TraceContext",
    "TraceParent",
    "TraceRecord",
    "classify_trace_error",
    "estimate_llm_cost_usd",
    "format_traceparent",
    "generate_span_id",
    "generate_trace_id",
    "get_current_span",
    "get_current_span_id",
    "get_current_trace",
    "get_current_trace_id",
    "get_tracer",
    "inject_trace_headers",
    "parse_traceparent",
    "span_scope",
    "trace_scope",
    "traced_span",
]
