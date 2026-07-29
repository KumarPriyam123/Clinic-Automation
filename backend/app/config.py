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

    def assert_wa_secret_valid(self) -> None:
        """Fail loudly at startup if WA_APP_SECRET is set but looks wrong.
        A Meta app secret is exactly 32 lowercase hex chars.
        """
        import logging

        log = logging.getLogger("clinicq.config")
        if self.WA_APP_SECRET and len(self.WA_APP_SECRET) != 32:
            log.error(
                "WA_APP_SECRET looks wrong: expected 32 hex chars, got len=%d — "
                "signature verification will fail every webhook",
                len(self.WA_APP_SECRET),
            )

    # LLM (provider-agnostic: gemini-flash | claude-haiku)
    LLM_PROVIDER: str = "gemini-flash"
    LLM_API_KEY: str = ""
    # Model ID — changing a retired model is a config change, not a code change.
    # gemini-3.1-flash-lite: 500 RPD / 15 RPM on free tier (intent parsing is easy).
    LLM_MODEL: str = "gemini-3.1-flash-lite"

    # Auth / runtime
    JWT_SECRET: str = "dev-secret-change-me"
    ENV: str = "dev"

    # Panel (Next.js) origins allowed to call the API (CORS). Comma-separated in env.
    PANEL_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Scheduler single-instance guard (DEPLOY.md §single-instance). APScheduler
    # runs in-process; it must be ACTIVE in exactly ONE process. If uvicorn ever
    # runs --workers >1, every job double-fires -> duplicate WhatsApp sends to
    # real patients. Keep --workers 1, or run web + scheduler as separate
    # processes with RUN_SCHEDULER=false on the web ones.
    RUN_SCHEDULER: bool = True

    # Database connection tuning. Supabase's pooler (pgBouncer, transaction mode)
    # cannot use prepared statements, so asyncpg needs statement_cache_size=0
    # when the DSN targets the pooler; SSL is required for Supabase. Both are
    # auto-detected from the DSN (see db._connect_kwargs) but overridable here:
    #   DB_STATEMENT_CACHE_SIZE=0   force-disable the prepared-statement cache
    #   DB_SSL=true                 force SSL ('require')
    DB_STATEMENT_CACHE_SIZE: int | None = None
    DB_SSL: bool | None = None


settings = Settings()
