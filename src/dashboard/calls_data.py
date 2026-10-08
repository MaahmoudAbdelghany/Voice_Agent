"""
Call Data Access, Synthetic Seeding & Audio Resolution Services.

Provides session persistence scanning, realistic demo call seeding (Arabic & English),
in-memory / disk session merging, multi-criteria filtering, and resilient audio retrieval.
"""

from datetime import datetime, timezone, timedelta
import io
import json
import logging
import math
from pathlib import Path
import struct
from typing import Any, Dict, List, Optional, Tuple, Union
import wave

from src.agent.session_manager import (
    CallSession,
    CallStatus,
    ExtractedContext,
    MessageRole,
    SessionManager,
    TurnMessage,
    session_manager as global_session_manager,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Synthetic Audio Generation (Resilient Browser Fallback)
# ==============================================================================

def generate_demo_tone_wav(duration_seconds: float = 2.0, sample_rate: int = 16000) -> bytes:
    """
    Generate a lightweight, pleasant sine wave audio chime in standard PCM 16-bit mono.
    Ensures the audio player never encounters missing files or corrupt media errors.
    """
    num_samples = int(duration_seconds * sample_rate)
    buffer = io.BytesIO()
    
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)
        
        frames = bytearray()
        for i in range(num_samples):
            t = float(i) / sample_rate
            # Harmonic chime: 440 Hz (A4) blended with 880 Hz (A5), soft envelope decay
            decay = math.exp(-3.0 * t / duration_seconds)
            amplitude = 12000.0 * decay
            value = int(amplitude * (0.7 * math.sin(2.0 * math.pi * 440.0 * t) + 0.3 * math.sin(2.0 * math.pi * 880.0 * t)))
            # Clamp to 16-bit signed integer range
            value = max(-32768, min(32767, value))
            frames.extend(struct.pack("<h", value))
            
        wav_file.writeframes(frames)
        
    return buffer.getvalue()


def resolve_call_audio(
    session_id: str,
    storage_dir: Optional[Union[str, Path]] = None,
) -> Tuple[Union[Path, bytes], bool]:
    """
    Locate physical audio recording file for a session, or supply synthetic demo audio.
    
    Args:
        session_id: Target session identifier.
        storage_dir: Base directory containing 'audio/' subfolder.
        
    Returns:
        Tuple of (audio_source, is_demo_fallback) where audio_source is either
        a Path object pointing to a real file, or raw bytes of demo synthesized audio.
    """
    base_dir = Path(storage_dir) if storage_dir else Path("data/calls")
    audio_dir = base_dir / "audio"
    
    # Check potential audio formats
    for ext in [".wav", ".mp3", ".ogg", ".webm"]:
        target_path = audio_dir / f"{session_id}{ext}"
        if target_path.exists() and target_path.stat().st_size > 0:
            return target_path, False
            
    # Return synthetic demo audio bytes if no physical recording exists
    return generate_demo_tone_wav(), True


# ==============================================================================
# 2. Demo Seed Call Generator (Realistic Restaurant Domain Scenarios)
# ==============================================================================

def seed_demo_calls(storage_dir: Optional[Union[str, Path]] = None) -> List[CallSession]:
    """
    Generate and persist 4 realistic restaurant voice call sessions:
    1. Arabic Delivery Inquiry (Order lookup & live courier tracking)
    2. English Table Booking (Reservation for 4 with confirmed table number)
    3. Arabic Dietary & Allergen Inquiry (RAG menu knowledge search)
    4. Escalated Complaint (Cold food & delivery delay requiring human handoff)
    """
    mgr = SessionManager(storage_dir=storage_dir or "data/calls")
    now = datetime.now(timezone.utc)
    seeded: List[CallSession] = []

    # --------------------------------------------------------------------------
    # Scenario 1: Arabic Shawarma Delivery Status
    # --------------------------------------------------------------------------
    s1 = mgr.create_session(
        session_id="call-ar-ord-7821",
        room_name="restaurant-room-ar-01",
        participant_identity="caller-ahmed",
        language="ar",
        customer_phone="+966501234567",
    )
    s1.start_time = now - timedelta(minutes=45)
    s1.context.customer_name = "أحمد منصور"
    s1.context.order_id = "ORD-7821"
    s1.context.sentiment = "positive"
    
    s1.add_turn(
        role=MessageRole.USER,
        content="السلام عليكم، بدي أستفسر عن طلبي رقم 7821 متى يوصل؟",
        stt_latency_ms=175.0,
    )
    s1.add_turn(
        role=MessageRole.ASSISTANT,
        content="أهلاً بك يا أحمد! سأتحقق من حالة طلبك 7821 في النظام حالاً.",
        latency_ms=610.0,
        llm_latency_ms=230.0,
        tts_latency_ms=205.0,
    )
    s1.add_turn(
        role=MessageRole.TOOL,
        content="تم العثور على الطلب وحالته قيد التوصيل مع الكابتن خالد.",
        tool_name="check_order_status",
        tool_arguments={"order_id": "ORD-7821"},
        tool_result={
            "order_id": "ORD-7821",
            "status": "out_for_delivery",
            "estimated_minutes": 12,
            "courier_name": "خالد العتيبي",
            "items": ["شاورما دجاج صاروخ", "بطاطس مقلية", "عصير مانجو طازج"],
        },
    )
    s1.add_turn(
        role=MessageRole.ASSISTANT,
        content="طلبك رقم 7821 خرج مع الكابتن خالد وهو في الطريق إليك حالياً، ومتوقع وصوله خلال 12 دقيقة تقريباً.",
        latency_ms=590.0,
        llm_latency_ms=210.0,
        tts_latency_ms=205.0,
    )
    s1.add_turn(
        role=MessageRole.USER,
        content="شكراً جزيلاً، الله يعطيك العافية.",
        stt_latency_ms=160.0,
    )
    s1.add_turn(
        role=MessageRole.ASSISTANT,
        content="الله يعافيك يا أحمد، في خدمتك دائماً! يومك سعيد وبالعافية مقدماً.",
        latency_ms=540.0,
        llm_latency_ms=180.0,
        tts_latency_ms=200.0,
    )
    s1.end_time = s1.start_time + timedelta(seconds=78)
    s1.status = CallStatus.ENDED
    s1.metrics.duration_seconds = 78.0
    mgr.save_session(s1.session_id)
    seeded.append(s1)

    # --------------------------------------------------------------------------
    # Scenario 2: English Table Reservation
    # --------------------------------------------------------------------------
    s2 = mgr.create_session(
        session_id="call-en-res-4092",
        room_name="restaurant-room-en-02",
        participant_identity="caller-sarah",
        language="en",
        customer_phone="+14155552671",
    )
    s2.start_time = now - timedelta(hours=2, minutes=15)
    s2.context.customer_name = "Sarah Jenkins"
    s2.context.sentiment = "positive"
    s2.context.reservation_draft = {
        "reservation_id": "RES-4092",
        "guests": 4,
        "date": "2026-10-10",
        "time": "20:00",
        "table": "Indoor Booth #7",
    }
    
    s2.add_turn(
        role=MessageRole.USER,
        content="Hello! I would like to book a table for 4 people this Friday evening around 8 PM.",
        stt_latency_ms=185.0,
    )
    s2.add_turn(
        role=MessageRole.ASSISTANT,
        content="Hello Sarah! Let me check table availability for 4 guests this Friday at 8:00 PM.",
        latency_ms=640.0,
        llm_latency_ms=240.0,
        tts_latency_ms=215.0,
    )
    s2.add_turn(
        role=MessageRole.TOOL,
        content="Table booked successfully.",
        tool_name="book_reservation",
        tool_arguments={"date": "2026-10-10", "time": "20:00", "party_size": 4, "customer_name": "Sarah Jenkins"},
        tool_result={"reservation_id": "RES-4092", "status": "confirmed", "table": "Indoor Booth #7", "party_size": 4},
    )
    s2.add_turn(
        role=MessageRole.ASSISTANT,
        content="Great news! Your table for 4 this Friday at 8:00 PM is confirmed. Your reference number is RES-4092.",
        latency_ms=620.0,
        llm_latency_ms=215.0,
        tts_latency_ms=220.0,
    )
    s2.add_turn(
        role=MessageRole.USER,
        content="Awesome, thank you so much for the quick confirmation!",
        stt_latency_ms=170.0,
    )
    s2.add_turn(
        role=MessageRole.ASSISTANT,
        content="You're very welcome, Sarah! We look forward to hosting you at Gourmet Oasis.",
        latency_ms=530.0,
        llm_latency_ms=175.0,
        tts_latency_ms=185.0,
    )
    s2.end_time = s2.start_time + timedelta(seconds=92)
    s2.status = CallStatus.ENDED
    s2.metrics.duration_seconds = 92.0
    mgr.save_session(s2.session_id)
    seeded.append(s2)

    # --------------------------------------------------------------------------
    # Scenario 3: Arabic Allergy & Dietary Inquiry (RAG)
    # --------------------------------------------------------------------------
    s3 = mgr.create_session(
        session_id="call-ar-rag-1033",
        room_name="restaurant-room-ar-03",
        participant_identity="caller-maryam",
        language="ar",
        customer_phone="+966559876543",
    )
    s3.start_time = now - timedelta(hours=4, minutes=10)
    s3.context.customer_name = "مريم العتيبي"
    s3.context.allergies = ["جلوتين", "قمح"]
    s3.context.dietary_preferences = ["Gluten-Free"]
    s3.context.sentiment = "neutral"
    
    s3.add_turn(
        role=MessageRole.USER,
        content="مرحباً، هل عندكم في المنيو خيارات خالية من الجلوتين؟ لأني أعاني من حساسية قمح شديدة.",
        stt_latency_ms=190.0,
    )
    s3.add_turn(
        role=MessageRole.ASSISTANT,
        content="أهلاً بكِ يا مريم، سلامتكِ أولاً! سأبحث في قائمة المكونات ومسببات الحساسية لدينا فوراً.",
        latency_ms=670.0,
        llm_latency_ms=260.0,
        tts_latency_ms=220.0,
    )
    s3.add_turn(
        role=MessageRole.TOOL,
        content="نتائج الاسترجاع لقائمة الأطباق الخالية من الجلوتين.",
        tool_name="search_knowledge_base",
        tool_arguments={"query": "gluten free options allergy cross contamination"},
        tool_result={
            "matched_items": [
                "سلطة الكينوا العضوية مع الأفوكادو (خالية تماماً من الجلوتين)",
                "ستيك الدجاج المشوي بالأعشاب مع الخضار المطهوة على البخار",
            ],
            "allergy_protocol": "محضرة في قسم معقم مخصص لمنع التلوث التبادلي للقمح.",
        },
    )
    s3.add_turn(
        role=MessageRole.ASSISTANT,
        content="نعم يا مريم! يتوفر لدينا سلطة الكينوا مع الأفوكادو، وصحن ستيك الدجاج المشوي بالأعشاب، وكلاهما يُحضّر في قسم مخصص ومعقم لضمان عدم وجود أي أثر للجلوتين.",
        latency_ms=710.0,
        llm_latency_ms=280.0,
        tts_latency_ms=240.0,
    )
    s3.add_turn(
        role=MessageRole.USER,
        content="ممتاز ومطمئن جداً، شكراً لتوضيحكم الدقيق.",
        stt_latency_ms=165.0,
    )
    s3.add_turn(
        role=MessageRole.ASSISTANT,
        content="على الرحب والسعة يا مريم، صحتك تهمنا دائماً ونتشرف بطلبك في أي وقت!",
        latency_ms=560.0,
        llm_latency_ms=190.0,
        tts_latency_ms=205.0,
    )
    s3.end_time = s3.start_time + timedelta(seconds=85)
    s3.status = CallStatus.ENDED
    s3.metrics.duration_seconds = 85.0
    mgr.save_session(s3.session_id)
    seeded.append(s3)

    # --------------------------------------------------------------------------
    # Scenario 4: Escalated Human Complaint
    # --------------------------------------------------------------------------
    s4 = mgr.create_session(
        session_id="call-ar-esc-9930",
        room_name="restaurant-room-ar-04",
        participant_identity="caller-tariq",
        language="ar",
        customer_phone="+966543219876",
    )
    s4.start_time = now - timedelta(hours=6, minutes=30)
    s4.context.customer_name = "طارق الدوسري"
    s4.context.order_id = "ORD-9930"
    s4.context.sentiment = "negative"
    s4.context.escalated = True
    s4.context.escalation_reason = "تأخر توصيل الطلب أكثر من ساعة ووصول الطعام بارداً"
    s4.context.escalation_department = "إدارة خدمة العملاء والجودة"
    
    s4.add_turn(
        role=MessageRole.USER,
        content="الطلب رقم 9930 متأخر أكثر من ساعة والأكل وصل بارد تماماً! بدي أكلم المسؤول حالاً!",
        stt_latency_ms=210.0,
    )
    s4.add_turn(
        role=MessageRole.ASSISTANT,
        content="أنا أعتذر بشدة يا أستاذ طارق عن هذا التأخير غير المقبول وعن برودة الطعام، حقك علينا.",
        latency_ms=630.0,
        llm_latency_ms=230.0,
        tts_latency_ms=210.0,
        interrupted=True,
    )
    s4.add_turn(
        role=MessageRole.USER,
        content="ما بدي كلام آلي، حولني على المشرف المباشر الآن لحل المشكلة!",
        stt_latency_ms=180.0,
    )
    s4.add_turn(
        role=MessageRole.TOOL,
        content="تم تحويل المكالمة إلى المشرف البشري.",
        tool_name="escalate_to_human",
        tool_arguments={"reason": "تأخر الطلب أكثر من ساعة وبرودة الأكل", "customer_name": "طارق الدوسري", "order_id": "ORD-9930"},
        tool_result={"escalation_id": "ESC-104", "department": "Customer Care", "status": "transferred", "agent_available": True},
    )
    s4.add_turn(
        role=MessageRole.ASSISTANT,
        content="أقدر غضبك تماماً يا سيد طارق. قمت بتحويل مكالمتك الآن إلى المشرف في إدارة الجودة وسيكون معك خلال ثوانٍ.",
        latency_ms=590.0,
        llm_latency_ms=200.0,
        tts_latency_ms=210.0,
    )
    s4.end_time = s4.start_time + timedelta(seconds=64)
    s4.status = CallStatus.ESCALATED
    s4.metrics.duration_seconds = 64.0
    mgr.save_session(s4.session_id)
    seeded.append(s4)

    logger.info(f"Successfully seeded {len(seeded)} demo call sessions to {mgr.storage_dir}")
    return seeded


# ==============================================================================
# 3. Session Query, Merging & Filtering Services
# ==============================================================================

def load_all_call_sessions(
    storage_dir: Optional[Union[str, Path]] = None,
    auto_seed: bool = True,
) -> List[CallSession]:
    """
    Retrieve all persisted and live in-memory call sessions.
    Automatically seeds demo data if storage is empty.
    
    Returns:
        List of CallSession objects sorted descending by start_time.
    """
    mgr = SessionManager(storage_dir=storage_dir or "data/calls")
    persisted = mgr.load_all_persisted_sessions()
    
    if not persisted and auto_seed:
        persisted = seed_demo_calls(storage_dir=mgr.storage_dir)
        
    # Merge with active in-memory sessions from global singleton
    sessions_dict: Dict[str, CallSession] = {s.session_id: s for s in persisted}
    for active_sess in global_session_manager.list_all_sessions():
        # In-memory session overwrites or adds new
        sessions_dict[active_sess.session_id] = active_sess
        
    all_sessions = list(sessions_dict.values())
    all_sessions.sort(key=lambda s: s.start_time, reverse=True)
    return all_sessions


def filter_call_sessions(
    sessions: List[CallSession],
    status: Optional[str] = None,
    language: Optional[str] = None,
    search_query: Optional[str] = None,
) -> List[CallSession]:
    """
    Filter call sessions by lifecycle status, language, and search string.
    
    Args:
        sessions: Source list of sessions.
        status: Target status ('all', 'active', 'ended', 'escalated').
        language: Target language ('all', 'ar', 'en').
        search_query: Free-text search term for session ID, phone, customer, or order ID.
        
    Returns:
        Filtered list of CallSession objects.
    """
    filtered = sessions
    
    # 1. Filter by status
    if status and status.lower() != "all":
        target_status = status.lower()
        if target_status == "escalated":
            filtered = [s for s in filtered if s.context.escalated or s.status == CallStatus.ESCALATED]
        elif target_status == "active":
            filtered = [s for s in filtered if s.status not in (CallStatus.ENDED, CallStatus.ESCALATED)]
        elif target_status == "ended":
            filtered = [s for s in filtered if s.status == CallStatus.ENDED and not s.context.escalated]
            
    # 2. Filter by language
    if language and language.lower() != "all":
        target_lang = language.lower()
        filtered = [s for s in filtered if (s.context.language or "en").lower() == target_lang]
        
    # 3. Search query filter
    if search_query and search_query.strip():
        q = search_query.strip().lower()
        matches: List[CallSession] = []
        for s in filtered:
            sid = s.session_id.lower()
            name = (s.context.customer_name or "").lower()
            phone = (s.context.customer_phone or "").lower()
            order = (s.context.order_id or "").lower()
            room = s.room_name.lower()
            
            # Check conversation text match as well
            text_match = any(q in m.content.lower() for m in s.messages)
            
            if q in sid or q in name or q in phone or q in order or q in room or text_match:
                matches.append(s)
        filtered = matches
        
    return filtered
