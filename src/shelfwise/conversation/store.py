"""Where conversation state lives between turns.

Redis with a TTL: a web session expires after 30 idle minutes, a kiosk's after 2
(`SHELFWISE_SESSION_TTL_S=120`), so a shared kiosk never shows the previous person's
conversation. Every write renews the TTL. The in-memory store is for tests and for running
without Redis; it expires the same way.
"""

import secrets
import time
from collections.abc import Callable
from typing import Protocol

from shelfwise.conversation.state import ConversationState

_PREFIX = "shelfwise:session:"


def new_session_id() -> str:
    return secrets.token_urlsafe(16)


class SessionStore(Protocol):
    def get(self, session_id: str) -> ConversationState | None: ...
    def put(self, state: ConversationState) -> None: ...
    def delete(self, session_id: str) -> None: ...


class MemorySessionStore:
    def __init__(self, ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl_s = ttl_s
        self.clock = clock
        self._states: dict[str, tuple[float, str]] = {}

    def get(self, session_id: str) -> ConversationState | None:
        entry = self._states.get(session_id)
        if entry is None or entry[0] <= self.clock():
            self._states.pop(session_id, None)
            return None
        return ConversationState.model_validate_json(entry[1])

    def put(self, state: ConversationState) -> None:
        self._states[state.session_id] = (self.clock() + self.ttl_s, state.model_dump_json())

    def delete(self, session_id: str) -> None:
        self._states.pop(session_id, None)


class RedisSessionStore:
    def __init__(self, url: str, ttl_s: int) -> None:
        import redis

        self.ttl_s = ttl_s
        self._redis = redis.Redis.from_url(url)

    def get(self, session_id: str) -> ConversationState | None:
        raw = self._redis.get(_PREFIX + session_id)
        return ConversationState.model_validate_json(raw) if raw else None

    def put(self, state: ConversationState) -> None:
        self._redis.set(_PREFIX + state.session_id, state.model_dump_json(), ex=self.ttl_s)

    def delete(self, session_id: str) -> None:
        self._redis.delete(_PREFIX + session_id)
