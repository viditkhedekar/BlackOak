from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql+asyncpg://blackoak:blackoak@localhost:5434/blackoak"
    cors_origins: list[str] = ["http://localhost:3000"]

    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
