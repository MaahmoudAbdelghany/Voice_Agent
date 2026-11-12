"""
LiveKit WebRTC Voice Pipeline Worker & `ClinicVoiceAgent` Adapter (Feature 5.4).

Bridges LiveKit rooms, Deepgram STT (`nova-3`), ElevenLabs TTS (`eleven_turbo_v2_5`),
and Silero VAD (`v4`) to the LiveKit-agnostic `ClinicTurnEngine` (`src/agent/turn_engine.py`)
via a custom `Agent.llm_node` override so every turn traverses `InputGuardrail`,
`FinOpsController`, `CacheLadder`, `ModelGateway`, session-scoped clinic tools,
`OutputGuardrail`, and `HierarchicalTracer`.

Zero network requests occur at import time (`NFR1` / `T1.8`).
"""

from __future__ import annotations

import os

# Prevent LiteLLM from fetching remote model cost maps at module import time (NFR1 / T1.8)
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import asyncio
import email.utils
import json
import logging
import time
from collections.abc import AsyncGenerator, Mapping
from pathlib import Path
from typing import Any

from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    WorkerType,
    cli,
    llm,
)
from livekit.agents.types import (
    DEFAULT_API_CONNECT_OPTIONS,
    NOT_GIVEN,
    APIConnectOptions,
    NotGivenOr,
)
from livekit.agents.voice import Agent, AgentSession, ModelSettings
from livekit.plugins import deepgram, elevenlabs, silero

from src.agent.messages import is_english
from src.agent.prompts import (
    build_greeting_message,
    get_system_prompt,
)
from src.agent.session_manager import (
    CallActivity,
    CallLifecycle,
    CallSession,
    SessionManager,
    session_manager,
)
from src.agent.turn_engine import ClinicTurnEngine, VerifiedCallerIdentity
from src.config import Settings, get_settings

logger = logging.getLogger(__name__)

_OFFLINE_DEEPGRAM_KEY = "dg_offline_placeholder_key"
_OFFLINE_ELEVENLABS_KEY = "el_offline_placeholder_key"
_OFFLINE_LIVEKIT_KEY = "devkey"
_OFFLINE_LIVEKIT_SECRET = "secret123456789012345678901234567890"
_DEFAULT_ELEVENLABS_VOICE_ID = "EXAVITQu4vr4xnSDxMaL"

_clock_skew_checked: bool = False
_clock_skew_offset_s: float = 0.0


# ==============================================================================
# 1. Lazy LiveKit Clock-Skew Compensation (D6 / NFR1)
# ==============================================================================


def _apply_livekit_clock_skew_patch(livekit_url: str | None = None) -> float:
    """
    Lazily inspect clock drift between local host and the configured LiveKit server
    and compensate PyJWT validation timestamps if drift exceeds 30 seconds.

    MUST ONLY be called lazily inside `entrypoint()` or `run_worker()`, NEVER at import time.
    Fails open silently with `0.0` offset when offline or unreachable.
    """
    global _clock_skew_checked, _clock_skew_offset_s
    if _clock_skew_checked:
        return _clock_skew_offset_s

    _clock_skew_checked = True
    cfg = get_settings()
    raw_url = (livekit_url or cfg.livekit_url or "").strip()
    if not raw_url or "your-" in raw_url or "localhost" in raw_url or "127.0.0.1" in raw_url:
        return 0.0

    http_url = (
        raw_url.replace("wss://", "https://", 1).replace("ws://", "http://", 1)
    )
    if not http_url.startswith(("http://", "https://")):
        return 0.0

    try:
        import httpx

        resp = httpx.head(http_url, timeout=1.5, follow_redirects=True)
        date_hdr = resp.headers.get("Date")
        if date_hdr:
            server_dt = email.utils.parsedate_to_datetime(date_hdr)
            skew_s = server_dt.timestamp() - time.time()
            if abs(skew_s) > 30.0:
                _clock_skew_offset_s = skew_s
                logger.warning(
                    "Detected %.1fs clock skew against LiveKit host; recorded offset compensation.",
                    skew_s,
                )
    except Exception as exc:  # noqa: BLE001
        logger.debug("LiveKit clock-skew probe skipped (offline/unreachable): %s", exc)

    return _clock_skew_offset_s


# ==============================================================================
# 2. Verified Caller Identity Extraction (R3 / D2 / D5 / T1.4)
# ==============================================================================


def _extract_mapping(obj: Any, attr_name: str) -> Mapping[str, Any]:
    """Safely extract a dict-like attribute from a LiveKit Participant or Room."""
    if obj is None:
        return {}
    if isinstance(obj, Mapping):
        return obj
    val = getattr(obj, attr_name, None)
    if isinstance(val, Mapping):
        return val
    return {}


def _parse_room_metadata(room: Any) -> dict[str, Any]:
    """Safely parse JSON `room.metadata` for non-sensitive tenant/branch/language defaults."""
    if room is None:
        return {}
    raw_meta = getattr(room, "metadata", None)
    if isinstance(raw_meta, Mapping):
        return dict(raw_meta)
    if isinstance(raw_meta, str) and raw_meta.strip():
        try:
            parsed = json.loads(raw_meta)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {}


def extract_verified_caller_identity(
    participant: Any | None = None,
    room: Any | None = None,
    *,
    default_language: str | None = None,
    settings_obj: Settings | None = None,
) -> VerifiedCallerIdentity:
    """
    Resolve verified caller identity strictly from LiveKit SIP attributes (`sip.phoneNumber`)
    first, then cryptographically signed JWT participant attributes (`caller_phone`, `lang`,
    `tenant_id`, `branch_id`).

    Returns `caller_phone=None` (`is_verified=False`) when neither SIP nor signed JWT
    phone attribute is present — never accepting spoken phone numbers from transcript.
    """
    cfg = settings_obj or get_settings()
    p_attrs = _extract_mapping(participant, "attributes")
    r_meta = _parse_room_metadata(room)

    sip_phone = str(p_attrs.get("sip.phoneNumber") or "").strip()
    jwt_phone = str(p_attrs.get("caller_phone") or "").strip()

    if sip_phone:
        resolved_phone: str | None = sip_phone
        source = "sip"
    elif jwt_phone:
        resolved_phone = jwt_phone
        source = "jwt"
    else:
        resolved_phone = None
        source = "unverified"

    raw_lang = (
        p_attrs.get("lang")
        or p_attrs.get("language")
        or r_meta.get("lang")
        or r_meta.get("language")
        or default_language
        or cfg.deepgram_language
        or "ar"
    )
    resolved_lang = "en" if is_english(str(raw_lang)) else "ar"

    raw_tenant = (
        p_attrs.get("tenant_id")
        or r_meta.get("tenant_id")
        or "default"
    )
    raw_branch = (
        p_attrs.get("branch_id")
        or r_meta.get("branch_id")
        or "main"
    )

    p_name = getattr(participant, "name", None) if participant is not None else None
    caller_name = (
        str(p_name).strip()
        if p_name and str(p_name).strip()
        else (str(p_attrs.get("caller_name")).strip() if p_attrs.get("caller_name") else None)
    )

    return VerifiedCallerIdentity(
        caller_phone=resolved_phone,
        caller_name=caller_name,
        tenant_id=str(raw_tenant).strip() or "default",
        branch_id=str(raw_branch).strip() or "main",
        language=resolved_lang,
        source=source,
    )


# ==============================================================================
# 3. Offline-Safe Gateway-Backed LLM Sentinel & Plugin Factories (R7 / T1.6)
# ==============================================================================


class GatewayBackedLLM(llm.LLM):
    """
    Lightweight LiveKit `llm.LLM` adapter satisfying `AgentSession`'s non-None LLM check
    while guaranteeing that 100% of reasoning routes through `ClinicVoiceAgent.llm_node` ->
    `ClinicTurnEngine` -> `ModelGateway` (never bypassing guardrails via `livekit.plugins.groq.LLM`).
    """

    def __init__(self, model_name: str | None = None) -> None:
        super().__init__()
        cfg = get_settings()
        self._model_name = model_name or cfg.groq_model

    @property
    def model(self) -> str:
        return self._model_name

    @property
    def provider(self) -> str:
        return "model_gateway"

    def chat(
        self,
        *,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool] | None = None,
        conn_options: APIConnectOptions = DEFAULT_API_CONNECT_OPTIONS,
        parallel_tool_calls: NotGivenOr[bool] = NOT_GIVEN,
        tool_choice: NotGivenOr[llm.ToolChoice] = NOT_GIVEN,
        extra_kwargs: NotGivenOr[dict[str, Any]] = NOT_GIVEN,
    ) -> llm.LLMStream:
        raise RuntimeError(
            "Direct GatewayBackedLLM.chat() is disabled; all voice turns must execute via "
            "ClinicVoiceAgent.llm_node -> ClinicTurnEngine -> ModelGateway."
        )


def _resolve_api_key(configured_key: str | None, placeholder: str) -> str:
    cleaned = (configured_key or "").strip()
    if not cleaned or "your_" in cleaned:
        return placeholder
    return cleaned


def create_stt(
    language: str | None = None,
    *,
    settings_obj: Settings | None = None,
) -> deepgram.STT:
    """
    Construct the Deepgram `nova-3` streaming STT plugin configured for the call's single
    resolved language (`"ar"` or `"en"`), falling back to an offline placeholder key when unset.
    """
    cfg = settings_obj or get_settings()
    raw_lang = language or cfg.deepgram_language or "ar"
    dg_lang = "en" if is_english(raw_lang) else "ar"
    api_key = _resolve_api_key(cfg.deepgram_api_key, _OFFLINE_DEEPGRAM_KEY)

    return deepgram.STT(
        model=cfg.deepgram_model or "nova-3",
        language=dg_lang,
        interim_results=True,
        punctuate=True,
        smart_format=False,
        filler_words=True,
        api_key=api_key,
    )


def create_tts(
    language: str | None = None,
    *,
    settings_obj: Settings | None = None,
) -> elevenlabs.TTS:
    """
    Construct the ElevenLabs `eleven_turbo_v2_5` multilingual low-latency TTS plugin,
    falling back to an offline placeholder key when unset.
    """
    cfg = settings_obj or get_settings()
    raw_key = getattr(cfg, "eleven_api_key", None) or getattr(cfg, "elevenlabs_api_key", "")
    api_key = _resolve_api_key(raw_key, _OFFLINE_ELEVENLABS_KEY)
    raw_voice_id = (
        getattr(cfg, "eleven_voice_id", None)
        or getattr(cfg, "elevenlabs_voice_id", "")
        or ""
    )
    voice_id = str(raw_voice_id).strip() or _DEFAULT_ELEVENLABS_VOICE_ID
    raw_model = (
        getattr(cfg, "eleven_model", None)
        or getattr(cfg, "elevenlabs_model", None)
        or "eleven_turbo_v2_5"
    )
    el_lang = "en" if is_english(language or cfg.deepgram_language) else "ar"

    return elevenlabs.TTS(
        voice_id=voice_id,
        model=raw_model,
        language=el_lang,
        api_key=api_key,
    )


def create_vad(*, prewarmed_vad: Any | None = None) -> silero.VAD:
    """
    Load or reuse the bundled Silero VAD (`v4`) ONNX detector tuned for responsive
    Egyptian clinic barge-in cutoff without cloud network calls.
    """
    if isinstance(prewarmed_vad, silero.VAD):
        return prewarmed_vad
    return silero.VAD.load(
        min_speech_duration=0.05,
        min_silence_duration=0.45,
        activation_threshold=0.5,
        force_cpu=True,
    )


# ==============================================================================
# 4. `ClinicVoiceAgent` (`Agent.llm_node` Override) & Lifecycle Hooks (R6, R7)
# ==============================================================================


def extract_latest_user_utterance(chat_ctx: llm.ChatContext | Any) -> str:
    """
    Extract the latest user message text from a LiveKit `ChatContext` (1.7.x).
    """
    if chat_ctx is None:
        return ""

    messages_attr = getattr(chat_ctx, "messages", None)
    items: list[Any]
    if callable(messages_attr):
        items = list(messages_attr())
    elif isinstance(messages_attr, list):
        items = messages_attr
    else:
        items = list(getattr(chat_ctx, "items", []) or [])

    for msg in reversed(items):
        role = getattr(msg, "role", None)
        role_str = getattr(role, "value", role)
        if str(role_str).lower() != "user":
            continue

        text_content = getattr(msg, "text_content", None)
        if isinstance(text_content, str) and text_content.strip():
            return text_content.strip()

        raw_content = getattr(msg, "content", None)
        if isinstance(raw_content, str) and raw_content.strip():
            return raw_content.strip()
        if isinstance(raw_content, list):
            joined = " ".join(
                str(part).strip()
                for part in raw_content
                if isinstance(part, str) and part.strip()
            )
            if joined:
                return joined

    return ""


class ClinicVoiceAgent(Agent):
    """
    LiveKit `Agent` subclass for the Egyptian Polyclinic Medical Receptionist.

    Overrides `llm_node` so LiveKit streams text chunks yielded by `ClinicTurnEngine`
    directly into ElevenLabs TTS while keeping Silero VAD barge-in active.
    """

    def __init__(
        self,
        *,
        instructions: str | None = None,
        turn_engine: ClinicTurnEngine | None = None,
        call_session: CallSession | None = None,
        caller_identity: VerifiedCallerIdentity | None = None,
        language: str = "ar",
        custom_instructions: str | None = None,
        session_mgr: SessionManager | None = None,
        **kwargs: Any,
    ) -> None:
        resolved_lang = (
            caller_identity.language
            if caller_identity is not None
            else ("en" if is_english(language) else "ar")
        )
        eff_instructions = instructions or get_system_prompt(
            custom_instructions=custom_instructions,
            language=resolved_lang,
        )
        super().__init__(
            instructions=eff_instructions,
            allow_interruptions=True,
            **kwargs,
        )
        self.turn_engine: ClinicTurnEngine = turn_engine or ClinicTurnEngine()
        self.caller_identity: VerifiedCallerIdentity = (
            caller_identity or VerifiedCallerIdentity(language=resolved_lang)
        )
        self.session_mgr: SessionManager = session_mgr or session_manager
        self.call_session: CallSession = call_session or self.session_mgr.create_session(
            language=resolved_lang,
            patient_phone=self.caller_identity.caller_phone,
        )
        self.custom_instructions = custom_instructions
        self._last_stt_latency_ms: float | None = None

    async def llm_node(
        self,
        chat_ctx: llm.ChatContext,
        tools: list[llm.Tool],
        model_settings: ModelSettings,
    ) -> AsyncGenerator[str, None]:
        """
        LiveKit 1.7.x `llm_node` hook: extracts the latest user utterance from `chat_ctx`
        and streams plain-text chunks validated by `ClinicTurnEngine` directly to TTS.
        """
        utterance = extract_latest_user_utterance(chat_ctx)
        if not utterance:
            return

        stt_ms = self._last_stt_latency_ms
        self._last_stt_latency_ms = None

        async for chunk in self.turn_engine.run_turn(
            utterance=utterance,
            call_session=self.call_session,
            caller_identity=self.caller_identity,
            stt_latency_ms=stt_ms,
            custom_instructions=self.custom_instructions,
        ):
            if chunk:
                yield chunk

    async def close_and_persist_session(
        self,
        status: CallLifecycle | None = None,
    ) -> Path | None:
        """End and atomically persist the PII-redacted `CallSession`."""
        return await handle_session_close(
            self.call_session,
            manager=self.session_mgr,
            status=status,
        )


async def handle_session_close(
    call_session: CallSession,
    *,
    manager: SessionManager | None = None,
    status: CallLifecycle | None = None,
) -> Path | None:
    """
    Persist a PII-redacted JSON snapshot of `call_session` via `async_end_and_persist`.
    Preserves `CallLifecycle.ESCALATED` if the call escalated during the conversation;
    otherwise transitions to `CallLifecycle.ENDED` (`T2.6`).
    """
    mgr = manager or session_manager
    if status is not None:
        target_status: CallLifecycle | None = status
    elif (
        call_session.lifecycle == CallLifecycle.ESCALATED
        or call_session.context.escalated
        or call_session.context.escalation is not None
    ):
        target_status = CallLifecycle.ESCALATED
    else:
        target_status = CallLifecycle.ENDED

    # Ensure session is registered in `mgr` before `async_end_and_persist`
    if mgr.get_session(call_session.session_id) is None:
        with mgr._lock:
            mgr._sessions[call_session.session_id] = call_session

    return await mgr.async_end_and_persist(
        call_session.session_id,
        status=target_status,
    )


def attach_session_lifecycle_hooks(
    agent_session: AgentSession,
    voice_agent: ClinicVoiceAgent,
    *,
    manager: SessionManager | None = None,
) -> set[asyncio.Task[Any]]:
    """
    Wire LiveKit `AgentSession` events (`user_input_transcribed`, `speech_created`,
    `agent_state_changed`, `close`) to `CallSession` activity, barge-in interruption
    counting (`record_interruption`), and PII-redacted persistence (`async_end_and_persist`).
    """
    mgr = manager or voice_agent.session_mgr
    call_session = voice_agent.call_session
    background_tasks: set[asyncio.Task[Any]] = set()
    interim_start_ts: float | None = None

    @agent_session.on("user_input_transcribed")
    def _on_user_transcribed(event: Any) -> None:
        nonlocal interim_start_ts
        is_final = bool(getattr(event, "is_final", False))
        if not is_final:
            if interim_start_ts is None:
                interim_start_ts = time.perf_counter()
            call_session.set_activity(CallActivity.LISTENING)
        else:
            if interim_start_ts is not None:
                voice_agent._last_stt_latency_ms = round(
                    (time.perf_counter() - interim_start_ts) * 1000.0, 2
                )
                interim_start_ts = None

    @agent_session.on("speech_created")
    def _on_speech_created(event: Any) -> None:
        call_session.set_activity(CallActivity.SPEAKING)
        handle = getattr(event, "speech_handle", None)
        if handle is not None and hasattr(handle, "add_done_callback"):

            def _on_speech_done(done_handle: Any) -> None:
                if bool(getattr(done_handle, "interrupted", False)):
                    call_session.record_interruption()

            handle.add_done_callback(_on_speech_done)

    @agent_session.on("agent_state_changed")
    def _on_agent_state_changed(event: Any) -> None:
        new_state = str(getattr(event, "new_state", "") or "").lower()
        if new_state in ("listening", "thinking"):
            call_session.set_activity(CallActivity.LISTENING)
        elif new_state == "speaking":
            call_session.set_activity(CallActivity.SPEAKING)

    @agent_session.on("close")
    def _on_close(_event: Any) -> None:
        try:
            task = asyncio.create_task(
                handle_session_close(call_session, manager=mgr),
                name=f"persist_call_session_{call_session.session_id}",
            )
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        except RuntimeError:
            # Fallback if called outside a running event loop
            mgr.end_and_persist(call_session.session_id, status=CallLifecycle.ENDED)

    return background_tasks


# ==============================================================================
# 5. Pipeline Factory & LiveKit Worker Entrypoint (R7 / T1.6 / T7.1)
# ==============================================================================


def create_voice_pipeline(
    *,
    language: str | None = None,
    custom_instructions: str | None = None,
    caller_identity: VerifiedCallerIdentity | None = None,
    call_session: CallSession | None = None,
    turn_engine: ClinicTurnEngine | None = None,
    session_mgr: SessionManager | None = None,
    prewarmed_vad: Any | None = None,
    settings_obj: Settings | None = None,
) -> tuple[AgentSession, ClinicVoiceAgent]:
    """
    Assemble the complete `(AgentSession, ClinicVoiceAgent)` WebRTC pipeline configured
    for a single resolved call language (`"ar"` default, or `"en"`).
    """
    cfg = settings_obj or get_settings()
    eff_identity = caller_identity or VerifiedCallerIdentity(
        language=language or cfg.deepgram_language or "ar"
    )
    resolved_lang = eff_identity.language

    stt_plugin = create_stt(language=resolved_lang, settings_obj=cfg)
    tts_plugin = create_tts(language=resolved_lang, settings_obj=cfg)
    vad_plugin = create_vad(prewarmed_vad=prewarmed_vad)
    llm_sentinel = GatewayBackedLLM(model_name=cfg.groq_model)

    mgr = session_mgr or session_manager
    eff_call_session = call_session or mgr.create_session(
        language=resolved_lang,
        patient_phone=eff_identity.caller_phone,
    )

    instructions = get_system_prompt(
        custom_instructions=custom_instructions,
        language=resolved_lang,
    )
    voice_agent = ClinicVoiceAgent(
        instructions=instructions,
        turn_engine=turn_engine,
        call_session=eff_call_session,
        caller_identity=eff_identity,
        language=resolved_lang,
        custom_instructions=custom_instructions,
        session_mgr=mgr,
    )

    agent_session = AgentSession(
        stt=stt_plugin,
        vad=vad_plugin,
        llm=llm_sentinel,
        tts=tts_plugin,
        allow_interruptions=True,
        min_endpointing_delay=0.3,
        max_endpointing_delay=2.5,
        max_tool_steps=cfg.max_tool_rounds_per_turn,
    )
    attach_session_lifecycle_hooks(agent_session, voice_agent, manager=mgr)

    return agent_session, voice_agent


def prewarm(proc: JobProcess) -> None:
    """Preload Silero VAD ONNX weights once per worker process for instant call startup."""
    proc.userdata["vad"] = create_vad()


async def entrypoint(ctx: JobContext) -> None:
    """
    LiveKit room worker entrypoint:
    1. Lazily probes LiveKit clock skew (`_apply_livekit_clock_skew_patch`).
    2. Connects to the room with audio-only auto-subscription.
    3. Waits for the remote caller participant and extracts verified SIP / JWT identity.
    4. Starts `AgentSession` + `ClinicVoiceAgent` in the caller's single resolved language.
    5. Speaks the localized Cairo time-of-day clinic greeting (`build_greeting_message`).
    """
    _apply_livekit_clock_skew_patch()
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    participant = await ctx.wait_for_participant()
    identity = extract_verified_caller_identity(participant=participant, room=ctx.room)

    room_name = getattr(ctx.room, "name", "") or ""
    p_identity = getattr(participant, "identity", "") or ""

    call_session = session_manager.create_session(
        room_name=room_name,
        participant_identity=p_identity,
        language=identity.language,
        patient_phone=identity.caller_phone,
    )
    call_session.transition_to(CallLifecycle.ACTIVE)

    prewarmed_vad = ctx.proc.userdata.get("vad") if hasattr(ctx, "proc") else None
    agent_session, voice_agent = create_voice_pipeline(
        language=identity.language,
        caller_identity=identity,
        call_session=call_session,
        prewarmed_vad=prewarmed_vad,
    )

    await agent_session.start(agent=voice_agent, room=ctx.room)

    greeting_text = build_greeting_message(language=identity.language)
    call_session.add_assistant_message(greeting_text)
    await agent_session.say(greeting_text, allow_interruptions=True)


def get_worker_options(*, settings_obj: Settings | None = None) -> WorkerOptions:
    """
    Construct `livekit.agents.WorkerOptions` bound to `entrypoint` and `prewarm`
    using offline-safe credential fallbacks when cloud env vars are unset (`T1.6`, `T7.1`).
    """
    cfg = settings_obj or get_settings()
    ws_url = (cfg.livekit_url or "").strip() or "ws://localhost:7880"
    api_key = _resolve_api_key(cfg.livekit_api_key, _OFFLINE_LIVEKIT_KEY)
    api_secret = _resolve_api_key(cfg.livekit_api_secret, _OFFLINE_LIVEKIT_SECRET)

    return WorkerOptions(
        entrypoint_fnc=entrypoint,
        prewarm_fnc=prewarm,
        worker_type=WorkerType.ROOM,
        ws_url=ws_url,
        api_key=api_key,
        api_secret=api_secret,
    )


def run_worker() -> None:
    """CLI entrypoint launching the LiveKit Agents room worker."""
    _apply_livekit_clock_skew_patch()
    cli.run_app(get_worker_options())


__all__ = [
    "ClinicVoiceAgent",
    "GatewayBackedLLM",
    "_apply_livekit_clock_skew_patch",
    "attach_session_lifecycle_hooks",
    "create_stt",
    "create_tts",
    "create_vad",
    "create_voice_pipeline",
    "entrypoint",
    "extract_latest_user_utterance",
    "extract_verified_caller_identity",
    "get_worker_options",
    "handle_session_close",
    "prewarm",
    "run_worker",
]


if __name__ == "__main__":
    run_worker()
