"""
Configuration Management for Voice Agent.

Loads settings from environment variables and .env file using Pydantic Settings.
Provides type safety, default values, and credential validation.
"""

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

VALID_CLINIC_CATEGORIES: frozenset[str] = frozenset(
    {
        "general",
        "specialties",
        "doctors",
        "pricing",
        "lab_radiology",
        "insurance",
        "booking_queue",
        "safety_guardrails",
        "faqs",
    }
)


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
    llm_stage_model: str = Field(
        default="llama-3.1-8b-instant",
        description="Groq model identifier for lightweight stages (classification, extraction)",
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

    # --- LLM Fallback - Google Gemini ---
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini API Key for fallback inference",
    )
    gemini_fallback_model: str = Field(
        default="gemini-2.0-flash",
        description="Google Gemini fallback model identifier",
    )

    # --- Model Gateway & Circuit Breaker ---
    llm_ttft_timeout_s: float = Field(
        default=3.5,
        ge=0.01,
        le=30.0,
        description="Time-to-first-token timeout on primary provider before failover",
    )
    llm_request_timeout_s: float = Field(
        default=10.0,
        ge=1.0,
        le=60.0,
        description="Total timeout for an individual LLM request attempt",
    )
    voice_max_tokens: int = Field(
        default=150,
        ge=16,
        le=1024,
        description="Hard token cap for caller-facing voice turns",
    )
    stage_max_tokens: int = Field(
        default=256,
        ge=16,
        le=1024,
        description="Token cap for non-dialogue stages (classification, extraction)",
    )
    circuit_breaker_failure_threshold: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Consecutive retryable failures before circuit breaker trips OPEN",
    )
    circuit_breaker_window_s: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description="Rolling window in seconds to count consecutive circuit breaker failures",
    )
    circuit_breaker_cooldown_s: float = Field(
        default=60.0,
        ge=5.0,
        le=600.0,
        description="Cooldown time in seconds while circuit breaker is OPEN before testing HALF_OPEN",
    )

    # --- 3-Tier Caching Ladder (Feature 4.2) ---
    cache_enabled: bool = Field(
        default=True,
        description="Global master kill switch for 3-tier caching ladder",
    )
    cache_exact_enabled: bool = Field(
        default=True,
        description="Toggle switch for Tier 1 Exact Hash Cache",
    )
    cache_semantic_enabled: bool = Field(
        default=True,
        description="Toggle switch for Tier 2 Semantic Cache",
    )
    cache_semantic_threshold: float = Field(
        default=0.97,
        ge=0.90,
        le=1.0,
        description="Strict minimum cosine similarity threshold for Tier 2 semantic cache hit",
    )
    cache_semantic_timeout_ms: int = Field(
        default=50,
        ge=5,
        le=500,
        description="Max timeout in milliseconds for Tier 2 embedding and vector search",
    )
    cache_semantic_collection: str = Field(
        default="semantic_cache",
        description="Dedicated Qdrant collection name for Tier 2 semantic cache",
    )
    cache_max_entries: int = Field(
        default=2000,
        ge=10,
        le=50000,
        description="Maximum entries stored in Tier 1 in-memory LRU cache",
    )
    cache_allowed_categories: list[str] = Field(
        default_factory=lambda: [
            "general",
            "specialties",
            "pricing",
            "lab_radiology",
            "insurance",
            "faqs",
        ],
        description="Allowlist of public categories eligible for caching",
    )
    cache_ttl_by_category: dict[str, int] = Field(
        default_factory=lambda: {
            "pricing": 21600,  # 6 hours
            "insurance": 21600,  # 6 hours
            "general": 86400,  # 24 hours
            "specialties": 86400,  # 24 hours
            "lab_radiology": 86400,  # 24 hours
            "faqs": 86400,  # 24 hours
        },
        description="TTL in seconds partitioned per clinic category",
    )
    cache_default_ttl_s: int = Field(
        default=86400,
        ge=60,
        le=604800,
        description="Default TTL in seconds if category is not explicitly mapped",
    )
    cache_kb_path: str = Field(
        default="knowledge_base/clinic_kb.md",
        description="Path to clinic knowledge base markdown document for kb_version calculation",
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
    reception_open_time: str = Field(
        default="09:00",
        description="Reception desk opening time (Cairo time, HH:MM)",
    )
    reception_close_time: str = Field(
        default="22:00",
        description="Reception desk closing time (Cairo time, HH:MM)",
    )
    reception_friday_open_time: str = Field(
        default="14:00",
        description="Reception desk Friday opening time (Cairo time, HH:MM)",
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
            if "restaurant_name" in data and (
                "clinic_name" not in data or data.get("clinic_name") == "مجمع عيادات النور التخصصي"
            ):
                data["clinic_name"] = data["restaurant_name"]
            if "restaurant_phone" in data and (
                "clinic_phone" not in data or data.get("clinic_phone") == "+20 2 3345 6789"
            ):
                data["clinic_phone"] = data["restaurant_phone"]
            if "restaurant_address" in data and (
                "clinic_address" not in data
                or data.get("clinic_address") == "شارع النصر، المعادي، القاهرة، مصر"
            ):
                data["clinic_address"] = data["restaurant_address"]
            if "restaurant_hours" in data and (
                "clinic_working_hours" not in data
                or "السبت" in str(data.get("clinic_working_hours", ""))
            ):
                data["clinic_working_hours"] = data["restaurant_hours"]
        return data

    @field_validator("cache_allowed_categories")
    @classmethod
    def validate_cache_allowed_categories(cls, v: list[str]) -> list[str]:
        """Ensure all allowed categories exist within recognized clinic categories."""
        invalid = set(v) - set(VALID_CLINIC_CATEGORIES)
        if invalid:
            raise ValueError(
                f"Invalid categories in cache_allowed_categories: {invalid}. Must be in {set(VALID_CLINIC_CATEGORIES)}"
            )
        return v

    @field_validator("cache_ttl_by_category")
    @classmethod
    def validate_cache_ttl_categories(cls, v: dict[str, int]) -> dict[str, int]:
        """Ensure all TTL category keys exist within recognized clinic categories."""
        invalid = set(v.keys()) - set(VALID_CLINIC_CATEGORIES)
        if invalid:
            raise ValueError(
                f"Invalid categories in cache_ttl_by_category: {invalid}. Must be in {set(VALID_CLINIC_CATEGORIES)}"
            )
        return v

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

    def is_gemini_configured(self) -> bool:
        """Check if Google Gemini fallback credentials are provided."""
        return bool(self.gemini_api_key and "your_" not in self.gemini_api_key)

    def is_tts_configured(self) -> bool:
        """Check if TTS credentials are provided."""
        return bool(self.eleven_api_key and "your_" not in self.eleven_api_key)

    def is_qdrant_cloud(self) -> bool:
        """Check if using Qdrant Cloud or local in-memory."""
        if not self.qdrant_url or not self.qdrant_api_key:
            return False
        return not ("your-cluster-id" in self.qdrant_url or "your_" in self.qdrant_api_key)

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


def get_settings() -> Settings:
    """Return the global Settings instance."""
    return settings
