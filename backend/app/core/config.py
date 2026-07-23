from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://envelops:envelops@localhost:5432/envelops"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    embedding_api_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="ENVELOPS_")


settings = Settings()
