"""Local LLM access through Ollama (design doc §18).

The one call the rest of the system needs: messages in, a validated Pydantic object out.
Ollama constrains decoding to the JSON schema, so output is almost always well-formed; Pydantic
then checks it. On a validation failure we retry once, telling the model what was wrong; a
second failure raises `LLMInvalidOutput`, and callers fall back (design doc §44).

Qwen3's "thinking" mode is off by default: it adds seconds of hidden reasoning tokens before every
answer, which structured extraction doesn't need.
"""

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx2
from pydantic import BaseModel, ValidationError

from shelfwise.config import get_settings


class LLMUnavailable(RuntimeError):
    """Ollama isn't running or the model isn't pulled."""


class LLMInvalidOutput(RuntimeError):
    """The model's output failed schema validation twice."""


@dataclass(frozen=True)
class GenerationStats:
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_ms: float  # wall clock, including any model load
    load_ms: float  # time Ollama spent loading the model into memory (0 when already warm)
    attempts: int

    @property
    def tokens_per_second(self) -> float:
        generate_ms = self.total_ms - self.load_ms
        return self.completion_tokens / (generate_ms / 1000) if generate_ms > 0 else 0.0


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    stats: GenerationStats


Message = dict[str, str]


class OllamaClient:
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        http: httpx2.Client | None = None,
        timeout: float = 120.0,
        keep_alive: str = "10m",
    ) -> None:
        settings = get_settings()
        self.model = model or settings.llm_model
        self._http = http or httpx2.Client(
            base_url=base_url or settings.ollama_url, timeout=timeout
        )
        self._keep_alive = keep_alive

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._http.post(path, json=payload)
        except httpx2.TransportError as exc:
            raise LLMUnavailable(
                f"Ollama not reachable ({exc}); start it with `ollama serve`"
            ) from exc
        if response.status_code == 404:
            raise LLMUnavailable(f"model {self.model!r} not found; run `ollama pull {self.model}`")
        response.raise_for_status()
        return response.json()

    def available_models(self) -> list[str]:
        try:
            response = self._http.get("/api/tags")
        except httpx2.TransportError as exc:
            raise LLMUnavailable(f"Ollama not reachable ({exc})") from exc
        return [m["name"] for m in response.json().get("models", [])]

    def chat_structured[T: BaseModel](
        self,
        messages: list[Message],
        schema: type[T],
        temperature: float = 0.0,
        num_ctx: int = 4096,
        max_tokens: int = 512,
        seed: int = 0,
        think: bool = False,
    ) -> StructuredResult[T]:
        conversation = list(messages)
        totals = {"prompt": 0, "completion": 0, "load_ns": 0}
        start = time.perf_counter()
        for attempt in (1, 2):
            data = self._post(
                "/api/chat",
                {
                    "model": self.model,
                    "messages": conversation,
                    "stream": False,
                    "format": schema.model_json_schema(),
                    "think": think,
                    "keep_alive": self._keep_alive,
                    "options": {
                        "temperature": temperature,
                        "num_ctx": num_ctx,
                        "num_predict": max_tokens,
                        "seed": seed,
                    },
                },
            )
            totals["prompt"] += data.get("prompt_eval_count", 0)
            totals["completion"] += data.get("eval_count", 0)
            totals["load_ns"] += data.get("load_duration", 0)
            content = data.get("message", {}).get("content", "")
            try:
                value = schema.model_validate(json.loads(content))
            except (json.JSONDecodeError, ValidationError) as exc:
                if attempt == 2:
                    raise LLMInvalidOutput(f"invalid output after retry: {exc}") from exc
                conversation += [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": f"That output was invalid: {exc}. Reply again with JSON that "
                        "matches the schema exactly.",
                    },
                ]
                continue
            stats = GenerationStats(
                model=self.model,
                prompt_tokens=totals["prompt"],
                completion_tokens=totals["completion"],
                total_ms=(time.perf_counter() - start) * 1000,
                load_ms=totals["load_ns"] / 1e6,
                attempts=attempt,
            )
            return StructuredResult(value, stats)
        raise AssertionError("unreachable")
