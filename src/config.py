"""
Configuration Management for Voice Agent.

Loads settings from environment variables and .env file using Pydantic Settings.
Provides type safety, default values, and credential validation.
"""

import os
from typing import Optional
from pydantic import Field
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
        default="en-US",
        description="Speech recognition language code",
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
    qdrant_url: Optional[str] = Field(
        default=None,
        description="Qdrant Cloud URL (or None for local in-memory storage)",
    )
    qdrant_api_key: Optional[str] = Field(
        default=None,
        description="Qdrant Cloud API Key",
    )
    qdrant_collection: str = Field(
        default="restaurant_kb",
        description="Target Qdrant collection name for knowledge base",
    )
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="FastEmbed model for generating dense text vectors",
    )

    # --- Restaurant Business Domain Settings ---
    restaurant_name: str = Field(
        default="السوري",
        description="Name of the restaurant",
    )
    agent_name: str = Field(
        default="السوري",
        description="Name of the voice AI assistant persona",
    )
    restaurant_phone: str = Field(
        default="+1 (555) 234-5678",
        description="Contact phone number",
    )
    restaurant_address: str = Field(
        default="123 Culinary Boulevard, Downtown",
        description="Physical location of restaurant",
    )
    restaurant_hours: str = Field(
        default="Monday-Sunday: 11:00 AM - 10:00 PM",
        description="Operating hours",
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

    def is_livekit_configured(self) -> bool:
        """Check if LiveKit credentials are provided."""
        return bool(self.livekit_url and self.livekit_api_key and self.livekit_api_secret)

    def is_stt_configured(self) -> bool:
        """Check if STT credentials are provided."""
        return bool(self.deepgram_api_key)

    def is_llm_configured(self) -> bool:
        """Check if LLM credentials are provided."""
        return bool(self.groq_api_key)

    def is_tts_configured(self) -> bool:
        """Check if TTS credentials are provided."""
        return bool(self.eleven_api_key)

    def is_qdrant_cloud(self) -> bool:
        """Check if using Qdrant Cloud or local in-memory."""
        return bool(self.qdrant_url and self.qdrant_api_key)


# Global singleton settings instance
settings = Settings()
