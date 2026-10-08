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
    embedding_model: str = "bge-base"  # see shelfwise.embed.models.MODELS
    # Hybrid (keyword + embedding) search in the API. Off: keyword-only, no model in memory.
    search_dense: bool = True
    # Cross-encoder reranker for the API (shelfwise.ranking.rerank.MODELS), off until the
    # benchmark shows it helps: e.g. SHELFWISE_RERANK_MODEL=minilm
    rerank_model: str | None = None
    # Local LLM served by Ollama. Mac (8 GB): qwen3:4b; RTX 4090: qwen3:8b or qwen3:14b.
    llm_model: str = "qwen3:4b"
    # How the API reads queries: "cascade" (rules + the LLM, falling back to the rules when
    # Ollama is down) or "rules" (no LLM at all).
    query_parser: Literal["cascade", "rules"] = "cascade"
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
