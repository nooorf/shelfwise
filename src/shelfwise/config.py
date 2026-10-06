"""Runtime settings, read from environment variables prefixed SHELFWISE_ (or a .env file)."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Profile = Literal["mac", "cuda", "cpu"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SHELFWISE_", env_file=".env", extra="ignore")

    profile: Profile = "mac"
    database_url: str = "postgresql://shelfwise:shelfwise@localhost:5432/shelfwise"
    redis_url: str = "redis://localhost:6379/0"
    ollama_url: str = "http://localhost:11434"
    log_level: str = "INFO"
    log_json: bool = True

    @property
    def sqlalchemy_url(self) -> str:
        """database_url with the psycopg 3 driver, as SQLAlchemy and Alembic expect."""
        prefix = "postgresql://"
        if self.database_url.startswith(prefix):
            return "postgresql+psycopg://" + self.database_url.removeprefix(prefix)
        return self.database_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
