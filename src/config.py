"""
Configuration Management for Voice Agent.

Loads settings from environment variables and .env file using Pydantic Settings.
Provides type safety, default values, and credential validation.
"""

from pathlib import Path
from typing import Any

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings and API credentials."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LiveKit Real-time Voice Infrastructure ---
    livekit_url: str = Field(
        default="wss://demo.livekit.cloud",
        description="LiveKit WebSocket server URL",
    )
    livekit_api_key: str = Field(
        default="",
        description="LiveKit API Key for room/token management",
    )
    livekit_api_secret: str = Field(
        default="",
        description="LiveKit API Secret",
    )

    # --- Speech-to-Text (STT) - Deepgram ---
    deepgram_api_key: str = Field(
        default="",
        description="Deepgram API Key for streaming speech transcription",
    )
    deepgram_model: str = Field(
        default="nova-3",
        description="Deepgram transcription model (e.g., nova-3, nova-2)",
    )
    deepgram_language: str = Field(
        default="ar",
        description="Speech recognition language code (e.g. 'ar' for Arabic, 'en-US' for English)",
    )

    # --- LLM Reasoning - Groq Cloud ---
    groq_api_key: str = Field(
        default="",
        description="Groq Cloud API Key for ultra-fast Llama 3.3 inference",
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq hosted model identifier",
    )
    llm_temperature: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="LLM sampling temperature",
    )
    llm_max_tokens: int = Field(
        default=512,
        ge=64,
        le=2048,
        description="Maximum tokens generated per voice turn",
    )

    # --- Text-to-Speech (TTS) - ElevenLabs ---
    eleven_api_key: str = Field(
        default="",
        description="ElevenLabs API Key for vocal synthesis",
    )
    eleven_voice_id: str = Field(
        default="21m00Tcm4TlvDq8ikWAM",  # Rachel voice
        description="ElevenLabs Voice ID",
    )
    eleven_model: str = Field(
        default="eleven_turbo_v2_5",
        description="ElevenLabs low-latency voice model",
    )

    # --- Vector Database & RAG - Qdrant ---
    qdrant_url: str | None = Field(
        default=None,
        description="Qdrant Cloud URL (or None for local in-memory storage)",
    )
    qdrant_api_key: str | None = Field(
        default=None,
        description="Qdrant Cloud API Key",
    )
    qdrant_collection: str = Field(
        default="clinic_kb",
        description="Target Qdrant collection name for knowledge base",
    )
    embedding_model: str = Field(
        default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        description="FastEmbed multilingual model for generating dense text vectors (supports Arabic)",
    )

    # --- Egyptian Polyclinic Domain Settings ---
    clinic_name: str = Field(
        default="مجمع عيادات النور التخصصي",
        description="Name of the polyclinic / medical center",
    )
    clinic_tagline: str = Field(
        default="رعايتكم أولويتنا",
        description="Tagline or slogan of the clinic",
    )
    clinic_phone: str = Field(
        default="+20 2 3345 6789",
        description="Contact phone number of the clinic",
    )
    clinic_address: str = Field(
        default="شارع النصر، المعادي، القاهرة، مصر",
        description="Physical location of the clinic",
    )
    clinic_working_hours: str = Field(
        default="السبت - الخميس: 9:00 ص - 10:00 م | الجمعة: 2:00 م - 10:00 م",
        description="Clinic shift and operating hours",
    )
    agent_name: str = Field(
        default="نور",
        description="Name of the voice AI assistant persona",
    )
    emergency_phone: str = Field(
        default="123",
        description="Egyptian emergency ambulance hotline number",
    )

    # --- Relational Database Settings (Async SQLAlchemy) ---
    database_url: str = Field(
        default="sqlite+aiosqlite:///./data/clinic.db",
        description="Async database connection URL (SQLite or PostgreSQL)",
    )
    database_echo: bool = Field(
        default=False,
        description="Echo SQL queries to logger for debugging",
    )

    # --- App & Observability ---
    dashboard_port: int = Field(
        default=8501,
        description="Port for Streamlit dashboard",
    )
    log_level: str = Field(
        default="INFO",
        description="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    @model_validator(mode="before")
    @classmethod
    def handle_legacy_fields(cls, data: Any) -> Any:
        """Map legacy restaurant keys to clinic fields if clinic keys are absent or overridden."""
        if isinstance(data, dict):
            if "restaurant_name" in data and ("clinic_name" not in data or data.get("clinic_name") == "مجمع عيادات النور التخصصي"):
                data["clinic_name"] = data["restaurant_name"]
            if "restaurant_phone" in data and ("clinic_phone" not in data or data.get("clinic_phone") == "+20 2 3345 6789"):
                data["clinic_phone"] = data["restaurant_phone"]
            if "restaurant_address" in data and ("clinic_address" not in data or data.get("clinic_address") == "شارع النصر، المعادي، القاهرة، مصر"):
                data["clinic_address"] = data["restaurant_address"]
            if "restaurant_hours" in data and ("clinic_working_hours" not in data or "السبت" in str(data.get("clinic_working_hours", ""))):
                data["clinic_working_hours"] = data["restaurant_hours"]
        return data

    # --- Backward-Compatibility Aliases ---
    @property
    def restaurant_name(self) -> str:
        """Legacy alias delegating to clinic_name."""
        return self.clinic_name

    @property
    def restaurant_phone(self) -> str:
        """Legacy alias delegating to clinic_phone."""
        return self.clinic_phone

    @property
    def restaurant_address(self) -> str:
        """Legacy alias delegating to clinic_address."""
        return self.clinic_address

    @property
    def restaurant_hours(self) -> str:
        """Legacy alias delegating to clinic_working_hours."""
        return self.clinic_working_hours

    def is_livekit_configured(self) -> bool:
        """Check if LiveKit credentials are provided."""
        return bool(
            self.livekit_url
            and self.livekit_api_key
            and self.livekit_api_secret
            and "your_" not in self.livekit_api_key
        )

    def is_stt_configured(self) -> bool:
        """Check if STT credentials are provided."""
        return bool(self.deepgram_api_key and "your_" not in self.deepgram_api_key)

    def is_llm_configured(self) -> bool:
        """Check if LLM credentials are provided."""
        return bool(self.groq_api_key and "your_" not in self.groq_api_key)

    def is_tts_configured(self) -> bool:
        """Check if TTS credentials are provided."""
        return bool(self.eleven_api_key and "your_" not in self.eleven_api_key)

    def is_qdrant_cloud(self) -> bool:
        """Check if using Qdrant Cloud or local in-memory."""
        if not self.qdrant_url or not self.qdrant_api_key:
            return False
        return not (
            "your-cluster-id" in self.qdrant_url or "your_" in self.qdrant_api_key
        )

    def is_database_configured(self) -> bool:
        """Check if relational database URL is configured."""
        return bool(self.database_url)

    def get_sqlite_db_path(self) -> str | None:
        """Extract SQLite file path from URL and guarantee parent directory exists."""
        if not self.database_url or "sqlite" not in self.database_url:
            return None
        url = self.database_url
        if ":///" in url:
            path_part = url.split(":///", 1)[1]
        elif "://" in url:
            path_part = url.split("://", 1)[1]
        else:
            return None

        clean_path = path_part.split("?", 1)[0]
        if clean_path in (":memory:", ""):
            return None

        db_path = Path(clean_path).resolve()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return str(db_path)


# Global singleton settings instance
settings = Settings()
