from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Absolute, not ".env" — a relative path resolves against cwd, and this
# needs to find the repo-root .env regardless of whether the app is
# launched from repo root, from backend/, or anywhere else. Docker
# containers don't hit this (compose injects real env vars directly), but
# host-based dev run from backend/ (see CLAUDE.md) silently got an empty
# key before this fix.
_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://envelops:envelops@localhost:5432/envelops"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expires_minutes: int = 60 * 24
    gemini_api_key: str = ""  # covers both generation and embeddings
    # REQUIREMENTS.md §3 step 8: how long a conversation has to sit with no
    # reply after our last outbound message before follow_up_check treats
    # it as "gone quiet". A single platform-wide default, not yet
    # tenant-configurable (same "fixed pipeline" reasoning as the rest of
    # the pipeline's business-rule constants).
    follow_up_delay_hours: int = 24
    # Public, read-only showcase mode: every mutating endpoint (knowledge
    # source CRUD, settings, escalation resolve/trigger-phrases, the
    # channel AI toggle, inbound channel webhooks) rejects with a 403
    # instead of writing anything, and the Celery follow_up_check job
    # no-ops entirely. Also opens a no-password tenant switch (GET
    # /auth/demo-tenants + POST /auth/demo-login, surfaced as the
    # Dashboard's own tenant dropdown) -- safe specifically BECAUSE
    # nothing can be mutated once this is on. This used to be a separate
    # dev_auth_bypass_enabled flag/login-screen widget; removed (decided
    # 2026-08-04) once demo mode covered the same need, so there's now
    # exactly one no-password-login mechanism, not two overlapping ones.
    # MUST stay false outside a local/throwaway environment or an actual
    # public demo deployment.
    demo_mode_enabled: bool = False

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_prefix="ENVELOPS_")


settings = Settings()
