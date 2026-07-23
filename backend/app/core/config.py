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
    gemini_api_key: str = ""  # covers both generation and embeddings

    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_prefix="ENVELOPS_")


settings = Settings()
