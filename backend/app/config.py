"""Application configuration — pydantic-settings, reads .env.

Every value has a local-friendly default so the app boots without a full
.env (tests, smoke checks). Production supplies real values via environment.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database / Supabase
    DATABASE_URL: str = "postgresql://localhost:5432/clinicq"
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_KEY: str = ""

    # WhatsApp Cloud API
    WA_TOKEN: str = ""
    WA_PHONE_NUMBER_ID: str = ""
    WA_VERIFY_TOKEN: str = ""
    WA_APP_SECRET: str = ""

    # LLM (provider-agnostic: gemini-flash | claude-haiku)
    LLM_PROVIDER: str = "gemini-flash"
    LLM_API_KEY: str = ""

    # Auth / runtime
    JWT_SECRET: str = "dev-secret-change-me"
    ENV: str = "dev"

    # Panel (Next.js) origins allowed to call the API (CORS). Comma-separated in env.
    PANEL_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]


settings = Settings()
