from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# The secrets live in the repo-root .env (one level above backend/). Resolve it by
# absolute path so the API, worker, and CLI all load it regardless of their CWD.
_ROOT_ENV = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ROOT_ENV, ".env"), env_file_encoding="utf-8", extra="ignore"
    )

    environment: str = "local"
    database_url: str = "postgresql+asyncpg://blackoak:blackoak@localhost:5434/blackoak"
    cors_origins: list[str] = ["http://localhost:3000"]

    # "yfinance" (no key) or "alpaca" (uses the paper keys' free IEX feed).
    market_data_provider: str = "yfinance"

    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
