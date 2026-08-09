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

    def is_production(self) -> bool:
        """True only for values that unambiguously mean production.

        Deliberately narrow. An unrecognised ENV must NOT be treated as
        production, because the only caller of this raises at boot — a typo
        like ENV=prodution would otherwise take the pilot backend dark.
        """
        return self.ENV.strip().lower() in {"prod", "production"}

    def assert_panel_origins_configured(self) -> None:
        """In production, refuse to boot on an unset PANEL_ORIGINS.

        Falling back to the localhost defaults in production means the panel
        fails CORS in the browser, before any request is sent — no server log,
        no status code, nothing to debug against. Quietly substituting a
        development value for missing production config is the same
        silent-wrong-success this codebase keeps getting bitten by.

        Scope is deliberately narrow: it fires only when ENV is definitively
        production AND the variable is absent from the environment. It does not
        second-guess a list that IS set — the live droplet legitimately carries
        http://localhost:3000 alongside its real origins.
        """
        import logging
        import os

        log = logging.getLogger("clinicq.config")
        if not self.is_production():
            return
        if "PANEL_ORIGINS" not in os.environ:
            raise RuntimeError(
                "PANEL_ORIGINS is not set and ENV is production. Refusing to start "
                "on the localhost CORS defaults: the panel would fail to log in "
                "with no server-side symptom. Set it as a JSON array, e.g. "
                'PANEL_ORIGINS=["https://app.clinicq.kpriyam.me"]'
            )
        if not any(
            o.strip() and "localhost" not in o and "127.0.0.1" not in o for o in self.PANEL_ORIGINS
        ):
            # Suspicious, not fatal — a deliberate localhost-only production
            # box is odd but legal, and this must not be able to take prod down.
            log.error(
                "PANEL_ORIGINS resolves to localhost-only in production: %s — "
                "the deployed panel will fail CORS",
                self.PANEL_ORIGINS,
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

    # Bearer token guarding /metrics. Unset => the endpoint 404s and is simply
    # not exposed; it fails CLOSED rather than serving cross-tenant counts to
    # anyone who finds the URL. /healthz stays open for uptime monitors.
    METRICS_TOKEN: str = ""

    # Panel (Next.js) origins allowed to call the API (CORS).
    # MUST be a JSON array in env, not a comma-separated string — this is a
    # complex type, so pydantic-settings json-decodes it and a bare
    # "a.example,b.example" raises SettingsError at import time and the app
    # never starts:
    #     PANEL_ORIGINS=["https://app.clinicq.kpriyam.me"]
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
