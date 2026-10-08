"""
Centralized application settings loaded from environment variables and .env file.
Uses Pydantic Settings v2.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application settings for SatyaSetu."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server Settings
    app_name: str = Field(default="Satyasetu", description="Application name")
    port: int = Field(default=8000, description="Uvicorn port")
    env: str = Field(default="development", description="'development' | 'production'")
    log_level: str = Field(default="INFO", description="Logging level")
    public_webhook_url: str = Field(
        default="http://localhost:8000",
        description="Publicly accessible webhook base URL (e.g. ngrok HTTPS URL)",
    )
    frontend_url: str = Field(
        default="http://localhost:3000",
        description="Optional frontend dashboard URL for CORS",
    )

    # Twilio Configuration
    require_twilio_signature: bool = Field(
        default=False,
        description="Whether to enforce Twilio X-Twilio-Signature validation",
    )
    twilio_account_sid: str = Field(
        default="",
        description="Twilio Account SID (starts with AC)",
    )
    twilio_auth_token: str = Field(
        default="",
        description="Twilio Auth Token",
    )
    twilio_whatsapp_number: str = Field(
        default="whatsapp:+14155238886",
        description="Twilio WhatsApp sender number",
    )
    twilio_sender_number: str = Field(
        default="",
        description="Twilio sender number override",
    )

    @property
    def account_sid(self) -> str:
        return self.twilio_account_sid

    @property
    def auth_token(self) -> str:
        return self.twilio_auth_token

    @property
    def sender_number(self) -> str:
        return self.twilio_sender_number or self.twilio_whatsapp_number

    # Google and Gemini APIs
    gemini_api_key: str = Field(
        default="",
        description="Google Gemini Flash API key",
    )
    gemini_model: str = Field(
        default="gemini-2.5-flash",
        description="Gemini model identifier",
    )
    google_fact_check_api_key: str = Field(
        default="",
        description="Google Fact Check Tools API key",
    )
    factcheck_min_match: float = Field(
        default=0.6,
        description="Minimum relevance match score for Google Fact Check reviews (0.0 to 1.0)",
    )

    # Web Search Provider (Brave or Tavily)
    search_provider: str = Field(
        default="brave",
        description="Web search engine provider: 'brave' or 'tavily'",
    )
    search_api_key: str = Field(
        default="",
        description="API key for selected web search engine",
    )

    # Local NLP and ML Models
    whisper_model_size: str = Field(
        default="base",
        description="Whisper ASR model size: tiny | base | small | medium",
    )
    ocr_extra_langs: str = Field(
        default="hi",
        description="Comma-separated extra languages for EasyOCR (e.g. 'hi,mr,ta,te,bn')",
    )
    nli_model_name: str = Field(
        default="roberta-large-mnli",
        description="HuggingFace model for NLI cross-encoder verification",
    )
    embedder_model_name: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="SentenceTransformer model for similarity and KeyBERT",
    )

    # Cache and Rate Limiting
    cache_backend: str = Field(
        default="memory",
        description="Cache backend: 'memory' or 'redis'",
    )
    rate_limit_per_minute: int = Field(
        default=20,
        description="Allowed requests per minute per phone number / IP",
    )
    max_claims_per_message: int = Field(
        default=3,
        description="Maximum claims extracted and verified per incoming message",
    )
    retrieval_budget_ms: int = Field(
        default=8000,
        description="Total time budget in milliseconds for retrieval and verification",
    )

    # Redis (Optional)
    upstash_redis_url: str = Field(default="", description="Upstash Redis REST URL")
    upstash_redis_token: str = Field(default="", description="Upstash Redis REST Token")


settings = Settings()
