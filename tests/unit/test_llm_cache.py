from datetime import date
from pathlib import Path

import pytest

from shelfwise.llm.cache import CachedLLM
from shelfwise.llm.client import LLMUnavailable
from shelfwise.query.cascade import CascadeParser, Link
from shelfwise.query.extract import QueryLLM
from tests.fakes import FakeLLM

MESSAGES = [{"role": "system", "content": "fill the form"}, {"role": "user", "content": "q"}]


def test_answers_are_stored_and_reused_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    llm = FakeLLM({"intent": "discover", "genres": ["mystery"]})

    first = CachedLLM(llm, path).chat_structured(MESSAGES, QueryLLM)
    again = CachedLLM(FakeLLM(LLMUnavailable("not running")), path)
    second = again.chat_structured(MESSAGES, QueryLLM)

    assert len(llm.calls) == 1
    assert second.value == first.value
    assert second.stats.attempts == 0
    assert (again.hits, again.misses) == (1, 0)


@pytest.mark.parametrize(
    "change",
    [
        lambda m: [m[0], {"role": "user", "content": "another query"}],
        lambda m: [{"role": "system", "content": "a new prompt"}, m[1]],
    ],
)
def test_any_change_to_the_messages_misses(tmp_path: Path, change) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "cache.jsonl"
    CachedLLM(FakeLLM({"intent": "discover"}), path).chat_structured(MESSAGES, QueryLLM)
    llm = FakeLLM({"intent": "other"})

    result = CachedLLM(llm, path).chat_structured(change(MESSAGES), QueryLLM)

    assert len(llm.calls) == 1
    assert result.value.intent == "other"


def test_other_models_miss(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    CachedLLM(FakeLLM({"intent": "discover"}, model="a"), path).chat_structured(MESSAGES, QueryLLM)
    llm = FakeLLM({"intent": "other"}, model="b")

    CachedLLM(llm, path).chat_structured(MESSAGES, QueryLLM)

    assert len(llm.calls) == 1


def test_errors_are_not_cached(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    with pytest.raises(LLMUnavailable):
        CachedLLM(FakeLLM(LLMUnavailable("down")), path).chat_structured(MESSAGES, QueryLLM)

    assert not path.exists()


class NoLinks:
    def title(self, text: str) -> Link | None:
        return None

    def author(self, text: str) -> Link | None:
        return None

    def author_in(self, text: str) -> Link | None:
        return None


def test_the_cascade_reports_cached_answers_without_latency(tmp_path: Path) -> None:
    path = tmp_path / "cache.jsonl"
    form = {"intent": "discover", "genres": ["horror"]}
    today = date(2026, 10, 8)
    fresh = CascadeParser(CachedLLM(FakeLLM(form), path), NoLinks()).parse("horror", today)
    cached = CascadeParser(CachedLLM(FakeLLM(form), path), NoLinks()).parse("horror", today)

    assert not fresh.cached and cached.cached
    assert cached.llm_ms == 0.0
    assert cached.request == fresh.request
