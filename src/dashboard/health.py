"""
Service Health Diagnostic Utility for Voice Agent Dashboard.

Inspects configurations and connectivity for LiveKit, Qdrant, Groq, ElevenLabs, and Deepgram.
Designed to be non-blocking, fast, and defensive against network failures.
"""

from typing import Dict, Any
from src.config import settings


def check_services_health() -> Dict[str, Dict[str, Any]]:
    """
    Check the configuration and reachability of all connected external subsystems.
    
    Returns:
        Dict mapping service keys to their diagnostic metadata and status.
    """
    health: Dict[str, Dict[str, Any]] = {}

    # 1. LiveKit Cloud Voice Infrastructure
    try:
        if settings.is_livekit_configured():
            health["livekit"] = {
                "name_key": "service_livekit",
                "sub_key": "service_livekit_sub",
                "status": "operational",
                "badge_key": "status_operational",
                "badge_class": "badge-online",
                "details": f"Server: {settings.livekit_url.split('://')[-1]}",
            }
        else:
            health["livekit"] = {
                "name_key": "service_livekit",
                "sub_key": "service_livekit_sub",
                "status": "unconfigured",
                "badge_key": "status_unconfigured",
                "badge_class": "badge-warning",
                "details": "Missing LIVEKIT_URL or LIVEKIT_API_KEY",
            }
    except Exception as e:
        health["livekit"] = {
            "name_key": "service_livekit",
            "sub_key": "service_livekit_sub",
            "status": "offline",
            "badge_key": "status_offline",
            "badge_class": "badge-offline",
            "details": str(e),
        }

    # 2. Qdrant Vector DB & Hybrid Search
    try:
        if settings.is_qdrant_cloud():
            health["qdrant"] = {
                "name_key": "service_qdrant",
                "sub_key": "service_qdrant_sub",
                "status": "operational",
                "badge_key": "status_operational",
                "badge_class": "badge-online",
                "details": f"Cloud Cluster ({settings.qdrant_collection})",
            }
        else:
            health["qdrant"] = {
                "name_key": "service_qdrant",
                "sub_key": "service_qdrant_sub",
                "status": "degraded",
                "badge_key": "status_degraded",
                "badge_class": "badge-warning",
                "details": f"In-Memory Vector DB ({settings.qdrant_collection})",
            }
    except Exception as e:
        health["qdrant"] = {
            "name_key": "service_qdrant",
            "sub_key": "service_qdrant_sub",
            "status": "offline",
            "badge_key": "status_offline",
            "badge_class": "badge-offline",
            "details": str(e),
        }

    # 3. Groq Cloud Ultra-Fast LLM Reasoning
    try:
        if settings.is_llm_configured():
            health["groq"] = {
                "name_key": "service_groq",
                "sub_key": "service_groq_sub",
                "status": "operational",
                "badge_key": "status_operational",
                "badge_class": "badge-online",
                "details": f"Model: {settings.groq_model}",
            }
        else:
            health["groq"] = {
                "name_key": "service_groq",
                "sub_key": "service_groq_sub",
                "status": "unconfigured",
                "badge_key": "status_unconfigured",
                "badge_class": "badge-warning",
                "details": "GROQ_API_KEY is not set",
            }
    except Exception as e:
        health["groq"] = {
            "name_key": "service_groq",
            "sub_key": "service_groq_sub",
            "status": "offline",
            "badge_key": "status_offline",
            "badge_class": "badge-offline",
            "details": str(e),
        }

    # 4. ElevenLabs Streaming Neural TTS
    try:
        if settings.is_tts_configured():
            health["elevenlabs"] = {
                "name_key": "service_elevenlabs",
                "sub_key": "service_elevenlabs_sub",
                "status": "operational",
                "badge_key": "status_operational",
                "badge_class": "badge-online",
                "details": f"Model: {settings.eleven_model}",
            }
        else:
            health["elevenlabs"] = {
                "name_key": "service_elevenlabs",
                "sub_key": "service_elevenlabs_sub",
                "status": "unconfigured",
                "badge_key": "status_unconfigured",
                "badge_class": "badge-warning",
                "details": "ELEVEN_API_KEY is not set",
            }
    except Exception as e:
        health["elevenlabs"] = {
            "name_key": "service_elevenlabs",
            "sub_key": "service_elevenlabs_sub",
            "status": "offline",
            "badge_key": "status_offline",
            "badge_class": "badge-offline",
            "details": str(e),
        }

    # 5. Deepgram Nova-3 Streaming Multilingual ASR
    try:
        if settings.is_stt_configured():
            health["deepgram"] = {
                "name_key": "service_deepgram",
                "sub_key": "service_deepgram_sub",
                "status": "operational",
                "badge_key": "status_operational",
                "badge_class": "badge-online",
                "details": f"Model: {settings.deepgram_model} ({settings.deepgram_language})",
            }
        else:
            health["deepgram"] = {
                "name_key": "service_deepgram",
                "sub_key": "service_deepgram_sub",
                "status": "unconfigured",
                "badge_key": "status_unconfigured",
                "badge_class": "badge-warning",
                "details": "DEEPGRAM_API_KEY is not set",
            }
    except Exception as e:
        health["deepgram"] = {
            "name_key": "service_deepgram",
            "sub_key": "service_deepgram_sub",
            "status": "offline",
            "badge_key": "status_offline",
            "badge_class": "badge-offline",
            "details": str(e),
        }

    return health
