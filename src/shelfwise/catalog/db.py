from sqlalchemy import Engine, create_engine

from shelfwise.config import get_settings


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_settings().sqlalchemy_url, pool_pre_ping=True)
