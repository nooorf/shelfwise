"""Runs against a real Ollama when one is up (`make test-all` with `ollama serve` running)."""

from typing import Literal

import pytest
from pydantic import BaseModel

from shelfwise.llm.client import LLMUnavailable, OllamaClient

pytestmark = pytest.mark.llm


class Answer(BaseModel):
    genre: Literal["mystery", "romance", "science fiction", "other"]


@pytest.fixture(scope="module")
def client() -> OllamaClient:
    client = OllamaClient()
    try:
        models = client.available_models()
    except LLMUnavailable:
        pytest.skip("Ollama is not running")
    if client.model not in models:
        pytest.skip(f"model {client.model} not pulled")
    return client


def test_real_model_returns_schema_valid_json(client: OllamaClient) -> None:
    result = client.chat_structured(
        [{"role": "user", "content": "Detective Poirot solves a murder on a train. Genre?"}],
        Answer,
        max_tokens=32,
    )

    assert result.value.genre == "mystery"
    assert result.stats.completion_tokens > 0


class NoCatalog:
    def title(self, text: str) -> None:
        return None

    def author(self, text: str) -> None:
        return None


def test_cascade_parses_a_negation_with_the_real_model(client: OllamaClient) -> None:
    from shelfwise.query.cascade import CascadeParser

    result = CascadeParser(client, NoCatalog()).parse("fantasy under 300 pages without romance")
    found = {(c.field, c.op, c.strength) for c in result.request.constraints}

    assert result.used_llm
    assert ("pages", "lt", "hard") in found
    assert ("genre", "in", "soft") in found
    assert ("facet.romance", "lte", "hard") in found
    assert "romance" not in result.request.semantic_query
