"""
Real-Time LiveKit Voice Agent Pipeline.

Integrates:
- Speech-to-Text (STT): Deepgram (nova-3 streaming transcription, Arabic/English)
- LLM Reasoning: Groq Cloud (Llama 3.3 70B fast inference + function calling)
- Text-to-Speech (TTS): ElevenLabs (eleven_turbo_v2_5 natural voice synthesis)
- Voice Activity Detection (VAD) & Barge-in: Silero VAD
- Real-Time Tool Calling: Menu/Policies RAG, Order Status, Table Reservation, Human Handoff
- Session & Analytics Management: Thread-safe CallSession tracking & JSON persistence
"""

import asyncio
import logging
from typing import Any, List, Optional, Tuple

# LiveKit Agents Core & Voice components
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    WorkerType,
    cli,
)
from livekit.agents.llm import function_tool
from livekit.agents.voice import Agent, AgentSession
from livekit import rtc

# LiveKit Plugins
import livekit.plugins.deepgram as dg
import livekit.plugins.elevenlabs as el
import livekit.plugins.groq as gq
import livekit.plugins.silero as sil

# Project configurations, prompts, session manager, and tools
from src.config import settings
from src.agent.prompts import (
    build_error_fallback_message,
    build_greeting_message,
    build_handoff_message,
    get_system_prompt,
)
from src.agent.session_manager import (
    CallSession,
    CallStatus,
    MessageRole,
    session_manager,
)
from src.tools.human_handoff import async_escalate_to_human
from src.tools.knowledge_search import async_search_restaurant_knowledge
from src.tools.order_status import async_get_order_status
from src.tools.reservation import async_book_reservation

logger = logging.getLogger("voice_agent")


# ==============================================================================
# Plugin Component Factories
# ==============================================================================

def create_stt(language: Optional[str] = None, api_key: Optional[str] = None) -> dg.STT:
    """
    Initialize Deepgram STT client for streaming transcription.
    
    Args:
        language: Language code (e.g. 'ar' for Arabic, 'en-US' for English).
                  Defaults to settings.deepgram_language.
        api_key: Optional API key override (defaults to settings.deepgram_api_key).
    """
    lang = language or settings.deepgram_language
    key = api_key or settings.deepgram_api_key
    if not key:
        logger.warning("Deepgram API key not found in settings. Using placeholder key for offline/mock mode.")
        key = "mock_deepgram_key"

    return dg.STT(
        model=settings.deepgram_model,
        language=lang,
        interim_results=True,
        punctuate=True,
        smart_format=True,
        api_key=key,
    )


def create_llm(api_key: Optional[str] = None) -> gq.LLM:
    """
    Initialize Groq LLM client for fast token generation & tool calling.
    
    Args:
        api_key: Optional API key override (defaults to settings.groq_api_key).
    """
    key = api_key or settings.groq_api_key
    if not key:
        logger.warning("Groq API key not found in settings. Using placeholder key for offline/mock mode.")
        key = "mock_groq_key"

    return gq.LLM(
        model=settings.groq_model,
        temperature=settings.llm_temperature,
        api_key=key,
    )


def create_tts(api_key: Optional[str] = None) -> el.TTS:
    """
    Initialize ElevenLabs TTS client for low-latency voice synthesis.
    
    Args:
        api_key: Optional API key override (defaults to settings.eleven_api_key).
    """
    key = api_key or settings.eleven_api_key
    if not key:
        logger.warning("ElevenLabs API key not found in settings. Using placeholder key for offline/mock mode.")
        key = "mock_elevenlabs_key"

    return el.TTS(
        model=settings.eleven_model,
        voice_id=settings.eleven_voice_id,
        sync_alignment=True,
        api_key=key,
    )


def create_vad() -> sil.VAD:
    """
    Initialize Silero Voice Activity Detector for low-latency barge-in and turn detection.
    """
    return sil.VAD.load(
        min_speech_duration=0.05,
        min_silence_duration=0.45,
        prefix_padding_duration=0.3,
    )


# ==============================================================================
# LiveKit Function Tools Factory
# ==============================================================================

def create_voice_tools(session: Optional[CallSession] = None) -> List[Any]:
    """
    Create LiveKit function tools bound to the active voice session.
    
    When invoked by the LLM during a live call, these tools execute the domain logic
    and log arguments, execution results, and context updates to CallSession.
    
    Args:
        session: Active CallSession instance (if available).
        
    Returns:
        List of decorated LiveKit FunctionTool instances.
    """

    @function_tool
    async def search_restaurant_knowledge(query: str) -> str:
        """Search restaurant menu items, ingredients, prices, allergens, operating hours, delivery areas, and branch policies.

        Args:
            query: The customer's inquiry or keyword regarding food items, ingredients, allergens, prices, opening hours, or policies.
        """
        logger.info(f"Tool invoked: search_restaurant_knowledge(query='{query}')")
        try:
            res = await async_search_restaurant_knowledge(query=query)
            payload = res.model_dump()
            if session:
                session.record_tool_call("search_restaurant_knowledge", {"query": query}, payload)

            # Return concise factual text for speech synthesis
            if res.formatted_context:
                return res.formatted_context
            return res.message
        except Exception as e:
            logger.exception(f"Error in search_restaurant_knowledge: {e}")
            return build_error_fallback_message(language=session.context.language if session else "ar")

    @function_tool
    async def get_order_status(order_id: str = "", phone: str = "") -> str:
        """Look up real-time status, driver details, and estimated delivery time for an order.

        Args:
            order_id: The unique order identifier (e.g. ORD-1001).
            phone: Registered customer phone number if order ID is not provided.
        """
        clean_order_id = order_id.strip() if order_id else None
        clean_phone = phone.strip() if phone else None
        logger.info(f"Tool invoked: get_order_status(order_id='{clean_order_id}', phone='{clean_phone}')")

        try:
            res = await async_get_order_status(order_id=clean_order_id, phone=clean_phone)
            payload = res.model_dump()
            if session:
                session.record_tool_call(
                    "get_order_status",
                    {"order_id": clean_order_id, "phone": clean_phone},
                    payload,
                )
            return res.message
        except Exception as e:
            logger.exception(f"Error in get_order_status: {e}")
            return build_error_fallback_message(language=session.context.language if session else "ar")

    @function_tool
    async def book_reservation(
        customer_name: str,
        phone_number: str,
        party_size: int,
        date: str,
        time: str,
        branch: str = "الفرع الرئيسي",
        special_requests: str = "",
    ) -> str:
        """Check table availability and book a dining reservation for a customer.

        Args:
            customer_name: Full name of the primary guest.
            phone_number: Mobile phone number for reservation confirmation and SMS reminders.
            party_size: Number of guests (1 to 30).
            date: Date of dining in YYYY-MM-DD format (or 'today', 'tomorrow').
            time: Time slot in HH:MM format (e.g. 19:30 or 20:00).
            branch: Target restaurant branch name. Defaults to 'الفرع الرئيسي'.
            special_requests: Optional seating requests, celebrations, high chair, or outdoor seating.
        """
        logger.info(
            f"Tool invoked: book_reservation(name='{customer_name}', guests={party_size}, date={date}, time={time})"
        )
        try:
            res = await async_book_reservation(
                customer_name=customer_name,
                phone_number=phone_number,
                party_size=party_size,
                date=date,
                time=time,
                branch=branch,
                special_requests=special_requests or None,
            )
            payload = res.model_dump()
            if session:
                session.record_tool_call(
                    "book_reservation",
                    {
                        "customer_name": customer_name,
                        "phone_number": phone_number,
                        "party_size": party_size,
                        "date": date,
                        "time": time,
                        "branch": branch,
                        "special_requests": special_requests,
                    },
                    payload,
                )
            return res.message
        except Exception as e:
            logger.exception(f"Error in book_reservation: {e}")
            return build_error_fallback_message(language=session.context.language if session else "ar")

    @function_tool
    async def escalate_to_human(
        reason: str,
        department: str = "customer_support",
        customer_name: str = "",
        customer_phone: str = "",
        urgency: str = "medium",
    ) -> str:
        """Escalate the live phone call to a human supervisor or specialist department.

        Args:
            reason: Explanation of why the caller needs a human agent or manager.
            department: Target department: 'customer_support', 'kitchen_manager', 'delivery_dispatch', 'billing'.
            customer_name: Customer's name if known.
            customer_phone: Customer's phone number for callback if disconnected.
            urgency: Urgency level: 'low', 'medium', 'high', or 'critical'.
        """
        logger.info(f"Tool invoked: escalate_to_human(reason='{reason}', dept='{department}', urgency='{urgency}')")
        try:
            res = await async_escalate_to_human(
                reason=reason,
                department=department,
                customer_name=customer_name or None,
                customer_phone=customer_phone or None,
                urgency=urgency,
            )
            payload = res.model_dump()
            if session:
                session.record_tool_call(
                    "escalate_to_human",
                    {
                        "reason": reason,
                        "department": department,
                        "customer_name": customer_name,
                        "customer_phone": customer_phone,
                        "urgency": urgency,
                    },
                    payload,
                )
            # Spoken confirmation before handoff transfer
            spoken_handoff = build_handoff_message(
                department_name=res.department.value,
                estimated_wait_seconds=res.estimated_wait_seconds,
                language=session.context.language if session else "ar",
            )
            return f"{spoken_handoff} {res.message}"
        except Exception as e:
            logger.exception(f"Error in escalate_to_human: {e}")
            return build_error_fallback_message(language=session.context.language if session else "ar")

    return [search_restaurant_knowledge, get_order_status, book_reservation, escalate_to_human]


# ==============================================================================
# Voice Pipeline Assembler
# ==============================================================================

def create_voice_pipeline(
    session: Optional[CallSession] = None,
    custom_instructions: Optional[str] = None,
    language: Optional[str] = None,
) -> Tuple[AgentSession, Agent]:
    """
    Assemble and configure the AgentSession and Agent components.
    
    Args:
        session: Active CallSession instance for state/metric tracking.
        custom_instructions: Optional system prompt overrides.
        language: Conversational language code ('ar' or 'en').
        
    Returns:
        Tuple of (AgentSession, Agent).
    """
    lang = language or (session.context.language if session else settings.deepgram_language)
    
    # 1. Initialize components
    stt = create_stt(language=lang)
    llm = create_llm()
    tts = create_tts()
    vad = create_vad()
    
    # 2. Build domain tools bound to this session
    tools = create_voice_tools(session=session)
    
    # 3. Dynamic system prompt
    prompt = get_system_prompt(
        custom_instructions=custom_instructions,
        language=lang,
    )
    
    # 4. Construct Agent and AgentSession
    agent = Agent(
        instructions=prompt,
        tools=tools,
    )

    agent_session = AgentSession(
        stt=stt,
        llm=llm,
        tts=tts,
        vad=vad,
    )
    
    return agent_session, agent


# ==============================================================================
# LiveKit Worker Entrypoint
# ==============================================================================

async def entrypoint(ctx: JobContext) -> None:
    """
    LiveKit room worker entrypoint.
    
    Invoked automatically by the LiveKit Agents runtime when a customer joins
    a WebRTC room (via telephony SIP bridge or web playground).
    
    Args:
        ctx: LiveKit JobContext containing room and connection metadata.
    """
    logger.info(f"Starting Voice Agent worker for room: '{ctx.room.name}' (Job ID: {ctx.job.id})")
    
    # 1. Connect to WebRTC room (audio only)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    
    # 2. Wait for customer / caller to join
    participant = await ctx.wait_for_participant()
    logger.info(f"Caller connected: identity='{participant.identity}', name='{participant.name}'")
    
    # 3. Initialize or retrieve session state
    session_id = ctx.room.name or ctx.job.id
    call_session = session_manager.get_or_create_session(
        session_id=session_id,
        room_name=ctx.room.name,
        participant_identity=participant.identity,
    )
    call_session.status = CallStatus.ACTIVE
    
    # 4. Create Voice Pipeline
    agent_session, agent = create_voice_pipeline(session=call_session)
    
    # 5. Wire up event listeners for observability & metrics
    @agent_session.on("user_input_transcribed")
    def on_user_transcribed(event: Any) -> None:
        text = getattr(event, "text", "") or getattr(event, "content", "")
        if text and text.strip():
            logger.info(f"[User Speech] {text}")
            call_session.add_user_message(content=text.strip())

    @agent_session.on("speech_created")
    def on_speech_created(event: Any) -> None:
        logger.debug("Assistant speech synthesis started")
        call_session.status = CallStatus.SPEAKING

    @agent_session.on("agent_state_changed")
    def on_state_changed(event: Any) -> None:
        state_val = getattr(event, "new_state", None) or getattr(event, "state", None)
        logger.debug(f"Agent state changed to: {state_val}")

    @agent_session.on("close")
    def on_close(event: Any) -> None:
        logger.info(f"Agent session closed for room '{ctx.room.name}'")
        call_session.end_call()
        session_manager.save_session(call_session.session_id)

    # 6. Start the AgentSession in the room
    logger.info("Starting AgentSession in room...")
    await agent_session.start(agent, room=ctx.room)
    
    # 7. Speak initial welcoming greeting
    greeting = build_greeting_message(language=call_session.context.language)
    logger.info(f"[Agent Spoken Greeting] {greeting}")
    call_session.add_assistant_message(content=greeting)
    
    # Non-blocking voice greeting
    asyncio.create_task(agent_session.say(greeting))
    
    logger.info(f"Voice Agent pipeline running actively for room '{ctx.room.name}'")


# ==============================================================================
# Worker Process Prewarm & Lifecycle
# ==============================================================================

def prewarm(proc: JobProcess) -> None:
    """
    Prewarm worker processes before receiving calls.
    Loads Silero VAD into memory to avoid startup latency on the first call.
    """
    logger.info("Prewarming worker process: Loading Silero VAD model...")
    try:
        proc.userdata["vad"] = sil.VAD.load()
        logger.info("Silero VAD model prewarmed successfully.")
    except Exception as e:
        logger.warning(f"VAD prewarm failed (will lazy-load on call): {e}")


def get_worker_options() -> WorkerOptions:
    """
    Construct WorkerOptions for the LiveKit CLI runner.
    """
    kwargs: dict[str, Any] = {
        "entrypoint_fnc": entrypoint,
        "prewarm_fnc": prewarm,
        "worker_type": WorkerType.ROOM,
    }
    if settings.livekit_url:
        kwargs["ws_url"] = settings.livekit_url
    if settings.livekit_api_key:
        kwargs["api_key"] = settings.livekit_api_key
    if settings.livekit_api_secret:
        kwargs["api_secret"] = settings.livekit_api_secret

    return WorkerOptions(**kwargs)


def run_worker() -> None:
    """
    CLI runner entry point for the LiveKit Voice Agent service.
    
    Usage:
        python -m src.agent.voice_agent start
        python -m src.agent.voice_agent console
        python -m src.agent.voice_agent dev
    """
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("Starting Voice AI Agent worker daemon...")
    cli.run_app(get_worker_options())


if __name__ == "__main__":
    run_worker()
