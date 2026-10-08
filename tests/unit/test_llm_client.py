import json
from typing import Any, Literal

import httpx2
import pytest
from pydantic import BaseModel

from shelfwise.llm.client import LLMInvalidOutput, LLMUnavailable, OllamaClient


class Facets(BaseModel):
    darkness: int
    supernatural: Literal["yes", "no", "unclear"]


def ollama_reply(content: str, **counts: int) -> dict[str, Any]:
    return {
        "message": {"role": "assistant", "content": content},
        "done": True,
        "prompt_eval_count": counts.get("prompt", 40),
        "eval_count": counts.get("completion", 12),
        "load_duration": counts.get("load_ns", 0),
    }


def client_with(*replies: dict[str, Any] | int) -> tuple[OllamaClient, list[dict[str, Any]]]:
    """A client whose server answers with `replies` in order (an int is an HTTP status)."""
    requests: list[dict[str, Any]] = []
    queue = list(replies)

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        reply = queue.pop(0)
        if isinstance(reply, int):
            return httpx2.Response(reply, json={"error": "nope"})
        return httpx2.Response(200, json=reply)

    http = httpx2.Client(base_url="http://ollama", transport=httpx2.MockTransport(handler))
    return OllamaClient(model="qwen3:4b", http=http), requests


MESSAGES = [{"role": "user", "content": "Tag this book."}]


def test_structured_call_sends_schema_and_disables_thinking() -> None:
    client, requests = client_with(ollama_reply('{"darkness": 3, "supernatural": "no"}'))

    result = client.chat_structured(MESSAGES, Facets, num_ctx=2048)

    assert result.value == Facets(darkness=3, supernatural="no")
    sent = requests[0]
    assert sent["model"] == "qwen3:4b"
    assert sent["stream"] is False
    assert sent["think"] is False
    assert sent["format"] == Facets.model_json_schema()
    assert sent["options"]["temperature"] == 0.0
    assert sent["options"]["num_ctx"] == 2048


def test_stats_report_tokens_and_load_time() -> None:
    client, _ = client_with(
        ollama_reply(
            '{"darkness": 1, "supernatural": "unclear"}',
            prompt=100,
            completion=20,
            load_ns=2_000_000,
        )
    )

    stats = client.chat_structured(MESSAGES, Facets).stats

    assert (stats.prompt_tokens, stats.completion_tokens, stats.attempts) == (100, 20, 1)
    assert stats.load_ms == pytest.approx(2.0)


def test_invalid_output_is_retried_once_with_the_error() -> None:
    client, requests = client_with(
        ollama_reply('{"darkness": "very", "supernatural": "no"}'),
        ollama_reply('{"darkness": 2, "supernatural": "no"}'),
    )

    result = client.chat_structured(MESSAGES, Facets)

    assert result.value.darkness == 2
    assert result.stats.attempts == 2
    retry_messages = requests[1]["messages"]
    assert retry_messages[-2]["role"] == "assistant"
    assert "invalid" in retry_messages[-1]["content"]


def test_two_invalid_outputs_raise() -> None:
    client, _ = client_with(ollama_reply("not json"), ollama_reply('{"darkness": 9}'))

    with pytest.raises(LLMInvalidOutput):
        client.chat_structured(MESSAGES, Facets)


def test_missing_model_and_unreachable_server_are_reported_clearly() -> None:
    client, _ = client_with(404)
    with pytest.raises(LLMUnavailable, match="ollama pull qwen3:4b"):
        client.chat_structured(MESSAGES, Facets)

    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    down = OllamaClient(
        model="x",
        http=httpx2.Client(base_url="http://ollama", transport=httpx2.MockTransport(refuse)),
    )
    with pytest.raises(LLMUnavailable, match="ollama serve"):
        down.chat_structured(MESSAGES, Facets)


def test_server_errors_are_unavailable_so_callers_fall_back() -> None:
    client, _ = client_with(500)

    with pytest.raises(LLMUnavailable, match="Ollama error 500"):
        client.chat_structured(MESSAGES, Facets)
