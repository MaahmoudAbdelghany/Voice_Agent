"""
Call Data Access & Audio Resolution Services.

Provides clinic session persistence scanning, in-memory / disk session merging,
multi-criteria clinic filtering, and resilient audio retrieval.
"""

import io
import logging
import math
import struct
import wave
from pathlib import Path

from src.agent.session_manager import (
    CallSession,
    CallStatus,
    SessionManager,
)
from src.agent.session_manager import (
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
            t_sec = float(i) / sample_rate
            # Harmonic chime: 440 Hz (A4) blended with 880 Hz (A5), soft envelope decay
            decay = math.exp(-3.0 * t_sec / duration_seconds)
            amplitude = 12000.0 * decay
            value = int(
                amplitude
                * (
                    0.7 * math.sin(2.0 * math.pi * 440.0 * t_sec)
                    + 0.3 * math.sin(2.0 * math.pi * 880.0 * t_sec)
                )
            )
            # Clamp to 16-bit signed integer range
            value = max(-32768, min(32767, value))
            frames.extend(struct.pack("<h", value))

        wav_file.writeframes(frames)

    return buffer.getvalue()


def resolve_call_audio(
    session_id: str,
    storage_dir: str | Path | None = None,
) -> tuple[Path | bytes, bool]:
    """
    Locate physical audio recording file for a session, or supply synthetic fallback audio.

    Args:
        session_id: Target session identifier.
        storage_dir: Base directory containing 'audio/' subfolder.

    Returns:
        Tuple of (audio_source, is_demo_fallback) where audio_source is either
        a Path object pointing to a real file, or raw bytes of synthesized fallback audio.
    """
    base_dir = Path(storage_dir) if storage_dir else Path("data/calls")
    audio_dir = base_dir / "audio"

    # Check potential audio formats
    for ext in [".wav", ".mp3", ".ogg", ".webm"]:
        target_path = audio_dir / f"{session_id}{ext}"
        if target_path.exists() and target_path.stat().st_size > 0:
            return target_path, False

    # Return synthetic fallback audio bytes if no physical recording exists
    return generate_demo_tone_wav(), True


# ==============================================================================
# 2. Session Query, Merging & Filtering Services
# ==============================================================================

def load_all_call_sessions(
    storage_dir: str | Path | None = None,
) -> list[CallSession]:
    """
    Retrieve persisted call sessions (and live in-memory sessions when using default storage).
    Returns an empty list when no sessions exist on disk (no synthetic demo seeds).

    Returns:
        List of CallSession objects sorted descending by start_time.
    """
    mgr = SessionManager(storage_dir=storage_dir or "data/calls")
    persisted = mgr.load_all_persisted_sessions()

    sessions_dict: dict[str, CallSession] = {s.session_id: s for s in persisted}

    # Merge active in-memory sessions from global singleton only for default runtime storage
    if storage_dir is None:
        for active_sess in global_session_manager.list_all_sessions():
            sessions_dict[active_sess.session_id] = active_sess

    all_sessions = list(sessions_dict.values())
    all_sessions.sort(key=lambda s: s.start_time, reverse=True)
    return all_sessions


# Canonical alias used by dashboard and tests
load_call_sessions = load_all_call_sessions


def filter_call_sessions(
    sessions: list[CallSession],
    status: str | None = None,
    language: str | None = None,
    search_query: str | None = None,
) -> list[CallSession]:
    """
    Filter clinic call sessions by lifecycle status, language, and search string.

    Args:
        sessions: Source list of sessions.
        status: Target status ('all', 'active', 'ended', 'escalated').
        language: Target language ('all', 'ar', 'en').
        search_query: Free-text search term for session ID, phone, patient, doctor, specialty, or booking code.

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
        matches: list[CallSession] = []
        for s in filtered:
            sid = s.session_id.lower()
            name = (s.context.patient_name or s.context.customer_name or "").lower()
            phone = (s.context.patient_phone or s.context.customer_phone or "").lower()
            specialty = (s.context.requested_specialty or "").lower()
            doctor = (s.context.requested_doctor_name or "").lower()
            room = s.room_name.lower()
            booking_tokens = " ".join(
                f"{b.booking_code} {b.doctor_name or ''} {b.specialty_name or ''}"
                for b in s.context.bookings
            ).lower()

            # Check conversation text match as well
            text_match = any(q in m.content.lower() for m in s.messages)

            if (
                q in sid
                or q in name
                or q in phone
                or q in specialty
                or q in doctor
                or q in booking_tokens
                or q in room
                or text_match
            ):
                matches.append(s)
        filtered = matches

    return filtered
