from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

from shelfwise.config import get_settings
from shelfwise.conversation.merge import apply_turn
from shelfwise.conversation.state import new_state
from shelfwise.conversation.store import RedisSessionStore, new_session_id
from shelfwise.query.request import ParsedRequest

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


@pytest.fixture
def store() -> Iterator[RedisSessionStore]:
    import redis

    store = RedisSessionStore(get_settings().redis_url, ttl_s=120)
    try:
        store._redis.ping()
    except redis.ConnectionError:
        pytest.skip("Redis not reachable (run `make up`)")
    yield store


def test_state_survives_a_round_trip_with_a_ttl(store: RedisSessionStore) -> None:
    session = new_session_id()
    state = apply_turn(
        new_state(session, NOW), "dark fantasy", ParsedRequest(intent="discover",
                                                               semantic_query="dark fantasy"), NOW
    ).state  # fmt: skip
    try:
        store.put(state)

        assert store.get(session) == state
        assert 0 < store._redis.ttl(f"shelfwise:session:{session}") <= 120
        store.delete(session)
        assert store.get(session) is None
    finally:
        store.delete(session)


def test_unknown_sessions_are_none(store: RedisSessionStore) -> None:
    assert store.get(new_session_id()) is None
