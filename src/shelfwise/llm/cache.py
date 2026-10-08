"""A disk cache in front of a `StructuredLLM`, so evaluations don't need the model running.

The key is the model, the schema and the exact messages: changing the prompt, the schema's name
or the model misses the cache by itself, with no version to bump. What's cached is the model's
validated answer, not anything computed from it, so code that post-processes the answer (the
cascade's merge and evidence check) still runs on every call and fixes apply to old answers.

One JSON line per answer, appended as answers arrive; the file is meant to be committed so a
benchmark run can be reproduced without the LLM.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from shelfwise.llm.client import GenerationStats, Message, StructuredLLM, StructuredResult


def cache_key(model: str, schema: type[BaseModel], messages: list[Message]) -> str:
    payload = json.dumps([model, schema.__name__, messages], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


class CachedLLM:
    """Wraps an LLM; answers already on disk come back with `attempts == 0` and no timing."""

    def __init__(self, llm: StructuredLLM, path: Path) -> None:
        self.llm = llm
        self.model = llm.model
        self.path = path
        self.hits = 0
        self.misses = 0
        self._answers: dict[str, dict[str, Any]] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._answers[row["key"]] = row["value"]

    def chat_structured[T: BaseModel](
        self, messages: list[Message], schema: type[T], **kwargs: Any
    ) -> StructuredResult[T]:
        key = cache_key(self.model, schema, messages)
        if key in self._answers:
            self.hits += 1
            stats = GenerationStats(self.model, 0, 0, 0.0, 0.0, attempts=0)
            return StructuredResult(schema.model_validate(self._answers[key]), stats)
        result = self.llm.chat_structured(messages, schema, **kwargs)  # errors aren't cached
        self.misses += 1
        value = result.value.model_dump(mode="json")
        self._answers[key] = value
        row = {"key": key, "model": self.model, "message": messages[-1]["content"], "value": value}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return result
