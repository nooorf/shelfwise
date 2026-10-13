"""Embedders: turn book texts and queries into unit-length vectors (cosine = dot product)."""

from collections import OrderedDict
from typing import Any, Protocol

import numpy as np

from shelfwise.embed.models import MODELS, EmbeddingModel

_QUERY_CACHE_SIZE = 1024


class Embedder(Protocol):
    name: str

    def encode_documents(self, texts: list[str]) -> np.ndarray: ...

    def encode_query(self, query: str) -> np.ndarray: ...


def pick_device() -> str:
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def own_memory(module: Any) -> None:
    """Copy a model's weights out of the memory-mapped model file.

    Some safetensors files place tensors at addresses not even 4-byte aligned, and Apple's
    Accelerate BLAS then silently returns NaN on CPU (seen with ms-marco-MiniLM-L6-v2 on
    torch 2.14). A copy is aligned. Cheap: once per load.
    """
    for parameter in module.parameters():
        parameter.data = parameter.data.clone()


class SentenceTransformerEmbedder:
    def __init__(self, model: EmbeddingModel, device: str | None = None, batch_size: int = 16):
        from sentence_transformers import SentenceTransformer  # heavy import, only when used

        self.name = model.name
        self._model = model
        self._batch_size = batch_size
        self._st = SentenceTransformer(model.hf_id, device=device or pick_device())
        own_memory(self._st)
        self._st.max_seq_length = model.max_seq_length
        self._query_cache: OrderedDict[str, np.ndarray] = OrderedDict()

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        vectors = self._st.encode(
            texts, batch_size=self._batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        return np.asarray(vectors, dtype=np.float32)

    def encode_query(self, query: str) -> np.ndarray:
        if query in self._query_cache:
            self._query_cache.move_to_end(query)
            return self._query_cache[query]
        vector = np.asarray(
            self._st.encode([self._model.query_prefix + query], normalize_embeddings=True)[0],
            dtype=np.float32,
        )
        self._query_cache[query] = vector
        if len(self._query_cache) > _QUERY_CACHE_SIZE:
            self._query_cache.popitem(last=False)
        return vector


def load_embedder(name: str) -> SentenceTransformerEmbedder:
    if name not in MODELS:
        raise ValueError(f"unknown embedding model {name!r}; choose from {sorted(MODELS)}")
    return SentenceTransformerEmbedder(MODELS[name])
