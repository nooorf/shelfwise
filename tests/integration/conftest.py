"""Integration fixtures: a throwaway `shelfwise_test` database migrated with Alembic.

Requires `make up`. Tests are skipped (not failed) when Postgres is unreachable.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError

from shelfwise.config import get_settings

ROOT = Path(__file__).resolve().parents[2]
TEST_DB = "shelfwise_test"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in str(item.path):
            item.add_marker(pytest.mark.integration)


def alembic_config(url: URL) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    config.attributes["configure_logger"] = False
    return config


def _recreate_database(admin_url: URL) -> None:
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    except OperationalError as exc:
        pytest.skip(f"Postgres not reachable (run `make up`): {exc.orig}")
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def test_db_url() -> URL:
    base = make_url(get_settings().sqlalchemy_url)
    _recreate_database(base.set(database="postgres"))
    url = base.set(database=TEST_DB)
    config = alembic_config(url)
    # Round-trip proves the downgrade works too.
    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return url


@pytest.fixture(scope="session")
def engine(test_db_url: URL) -> Iterator[Engine]:
    eng = create_engine(test_db_url)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    """A connection whose work is rolled back after each test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        yield connection
        transaction.rollback()
