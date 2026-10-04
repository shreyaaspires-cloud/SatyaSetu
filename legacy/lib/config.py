"""
lib/config.py
─────────────
Centralised settings loaded from .env via pydantic-settings v2.
Never import os.getenv() elsewhere — always import `settings` from here.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """All application settings pulled from environment variables / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # ignore unknown env vars — safe for shared .env files
    )

    # ── Twilio ────────────────────────────────────────────────────────────────
    twilio_account_sid: str = Field(..., description="Twilio Account SID (starts with AC)")
    twilio_auth_token: str = Field(..., description="Twilio Auth Token")
    twilio_whatsapp_number: str = Field(
        default="whatsapp:+14155238886",
        description="Twilio sandbox WhatsApp number",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    port: int = Field(default=8000, description="Uvicorn port")
    frontend_url: str = Field(default="http://localhost:3000", description="Admin dashboard URL for CORS")
    env: str = Field(default="development", description="'development' | 'production'")

    # ── Google / Gemini ───────────────────────────────────────────────────────
    gemini_api_key: str = Field(default="", description="Gemini Flash API key")
    google_fact_check_api_key: str = Field(default="", description="Google Fact Check Tools API key")

    # ── Bing ──────────────────────────────────────────────────────────────────
    bing_search_api_key: str = Field(default="", description="Bing Web Search API key")

    # ── Redis (Upstash) ───────────────────────────────────────────────────────
    upstash_redis_url: str = Field(default="", description="Upstash Redis REST URL")
    upstash_redis_token: str = Field(default="", description="Upstash Redis REST token")

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="sqlite:///./claims.db",
        description="SQLAlchemy DB URL — SQLite for hackathon, PostgreSQL for prod",
    )

    # ── ML Model config ───────────────────────────────────────────────────────
    whisper_model_size: str = Field(default="base", description="Whisper model size: tiny | base | medium")


# Singleton — import this everywhere
settings = Settings()
