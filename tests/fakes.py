"""Test doubles shared by unit and integration tests."""

import hashlib
import re

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
