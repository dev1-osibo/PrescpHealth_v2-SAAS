"""
PrescpHealth Backend — Application Configuration.

Centralizes all environment-based configuration using pydantic-settings.
Every setting is loaded from environment variables (or .env file in development).
Settings are grouped by concern for readability and maintainability.

This module is the SINGLE SOURCE OF TRUTH for configuration — no other module
should read environment variables directly. Import get_settings() instead.

Security note: Secrets (API keys, DB passwords, JWT secret) are loaded from
environment variables only — never hardcoded, never logged, never exposed in
API responses.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.

    All fields map to environment variables. Pydantic-settings handles
    type coercion, validation, and default values automatically.

    Usage:
        from app.config import get_settings
        settings = get_settings()
        print(settings.app_env)
    """

    model_config = SettingsConfigDict(
        # Load from .env file in development (ignored if file doesn't exist)
        env_file=".env",
        env_file_encoding="utf-8",
        # Don't fail if .env is missing (production uses real env vars)
        env_ignore_empty=True,
        # Allow extra fields from env without raising validation errors
        extra="ignore",
    )

    # -------------------------------------------------------------------------
    # Application Settings
    # -------------------------------------------------------------------------

    # Environment: development | staging | production
    # Controls debug mode, log verbosity, and feature flags
    app_env: str = "development"
    app_name: str = "PrescpHealth"
    api_version: str = "v1"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    uvicorn_workers: int = 1

    # OpenAPI docs — disabled in production to avoid exposing API surface
    enable_docs: bool = True

    # -------------------------------------------------------------------------
    # Database — PostgreSQL with async driver
    # -------------------------------------------------------------------------

    # Async URL for application queries (asyncpg driver)
    database_url: str = "postgresql+asyncpg://prescphealth:password@localhost:5432/prescphealth"

    # Sync URL for Alembic migrations only
    database_url_sync: str = "postgresql://prescphealth:password@localhost:5432/prescphealth"

    # Connection pool tuning
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30

    # -------------------------------------------------------------------------
    # Redis — Cache, rate limiting, Celery broker
    # -------------------------------------------------------------------------

    redis_url: str = "redis://localhost:6379/0"
    redis_cache_db: int = 0
    redis_session_db: int = 1
    redis_celery_db: int = 2
    redis_rate_limit_db: int = 3
    redis_default_ttl: int = 300  # 5 minutes

    # -------------------------------------------------------------------------
    # JWT Authentication
    # -------------------------------------------------------------------------

    # MUST be a strong random string (min 64 chars) in production
    jwt_secret_key: str = "CHANGE_ME_IN_PRODUCTION"
    jwt_algorithm: str = "HS256"

    # Short-lived access tokens per HIPAA session requirements
    jwt_access_token_expire_minutes: int = 15

    # Refresh tokens with rotation for session continuity
    jwt_refresh_token_expire_days: int = 7

    # bcrypt cost factor — 12 gives ~250ms per hash (good security/performance balance)
    bcrypt_cost_factor: int = 12

    # -------------------------------------------------------------------------
    # External AI Services
    # -------------------------------------------------------------------------

    # OpenAI GPT-4o — primary LLM provider
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_timeout_seconds: int = 8  # Failover to Claude after this

    # Anthropic Claude — fallback LLM provider
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-3-5-sonnet-20241022"
    anthropic_timeout_seconds: int = 12

    # -------------------------------------------------------------------------
    # Email — SendGrid
    # -------------------------------------------------------------------------

    sendgrid_api_key: str = ""
    sendgrid_from_email: str = "alerts@prescphealth.com"
    sendgrid_from_name: str = "PrescpHealth Alerts"

    # -------------------------------------------------------------------------
    # SMS/WhatsApp — Twilio
    # -------------------------------------------------------------------------

    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from_phone: str = ""
    twilio_whatsapp_from: str = ""

    # -------------------------------------------------------------------------
    # Celery — Background task processing
    # -------------------------------------------------------------------------

    celery_broker_url: str = "redis://localhost:6379/2"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_time_limit: int = 300
    celery_task_soft_time_limit: int = 270
    celery_max_retries: int = 3

    # -------------------------------------------------------------------------
    # ML Model Storage
    # -------------------------------------------------------------------------

    model_storage_type: str = "local"  # "s3" in production
    model_storage_s3_bucket: str = "prescphealth-models"
    model_storage_s3_region: str = "us-east-1"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    model_storage_local_path: str = "./ml/artifacts"

    # -------------------------------------------------------------------------
    # CORS
    # -------------------------------------------------------------------------

    # Comma-separated allowed origins (parsed into list in property)
    cors_allowed_origins: str = "http://localhost:5173,http://localhost:3000"

    # -------------------------------------------------------------------------
    # Rate Limiting
    # -------------------------------------------------------------------------

    rate_limit_clinician: int = 1000  # req/min for Doctor, Nurse, Clinic_Admin
    rate_limit_patient: int = 100  # req/min for Patient_User

    # -------------------------------------------------------------------------
    # Logging
    # -------------------------------------------------------------------------

    log_level: str = "INFO"
    log_format: str = "console"  # "json" in production

    # -------------------------------------------------------------------------
    # Encryption
    # -------------------------------------------------------------------------

    # Fernet key for application-layer encryption of cached PHI
    encryption_key: str = ""

    # -------------------------------------------------------------------------
    # Tenant Defaults
    # -------------------------------------------------------------------------

    default_data_residency_region: str = "af-south-1"
    default_tenant_language: str = "en"

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",")]

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return self.app_env == "development"


@lru_cache()
def get_settings() -> Settings:
    """
    Get cached application settings singleton.

    Uses lru_cache to ensure settings are loaded from environment only once.
    This avoids re-reading .env file on every request.

    Returns:
        Settings: The application configuration instance.
    """
    return Settings()
