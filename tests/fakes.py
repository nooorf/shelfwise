"""Test doubles shared by unit and integration tests."""

import hashlib
import re
from collections.abc import Sequence

import numpy as np


class FakeEmbedder:
    """Deterministic hashed bag-of-words vectors: texts sharing words point the same way.

    Lets tests exercise dense retrieval without downloading a model.
    """

    def __init__(self, name: str = "fake", dim: int = 64) -> None:
        self.name = name
        self.dim = dim
        self.queries: list[str] = []

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        for word in re.findall(r"[a-z]+", text.lower()):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vector(t) for t in texts]) if texts else np.zeros((0, self.dim))

    def encode_query(self, query: str) -> np.ndarray:
        self.queries.append(query)
        return self._vector(query)


class FakeLLM:
    """Returns canned structured outputs in order; raises the ones that are exceptions."""

    def __init__(self, *outputs: object, model: str = "fake-llm") -> None:
        self.model = model
        self.outputs = list(outputs)
        self.calls: list[list[dict[str, str]]] = []

    def chat_structured(self, messages, schema, **kwargs):  # type: ignore[no-untyped-def]
        from shelfwise.llm.client import GenerationStats, StructuredResult

        self.calls.append(messages)
        output = self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]
        if isinstance(output, Exception):
            raise output
        stats = GenerationStats(self.model, 100, 40, 50.0, 0.0, 1)
        return StructuredResult(schema.model_validate(output), stats)


class FakeReranker:
    """Scores a document by the share of query words it contains; records every call."""

    def __init__(self, name: str = "fake-reranker") -> None:
        self.name = name
        self.calls: list[tuple[str, list[str]]] = []

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls.append((query, list(documents)))
        words = set(re.findall(r"[a-z]+", query.lower()))
        return [
            len(words & set(re.findall(r"[a-z]+", doc.lower()))) / max(len(words), 1)
            for doc in documents
        ]
