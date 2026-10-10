"""Cross-encoder reranking (design doc §14.2).

A bi-encoder embeds the query and the book separately; a cross-encoder reads them together, so it
can tell "a mystery that isn't violent" from "a violent mystery". Far more accurate per pair and
far too slow for the whole catalog, so it reorders only the top N retrieved books. N is chosen by
a sweep (NDCG@10 against latency), not guessed.

Scores are probabilities (sigmoid of the logit): comparable across queries, usable as a ranker
feature. Pairs are sorted by length inside sentence-transformers to cut padding, and an LRU cache
keyed by (model, query, work) means a refinement that only changes filters reuses every score.
"""

import math
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from shelfwise.embed.encoder import own_memory, pick_device

CACHE_SIZE = 50_000  # (query, book) pairs; a few MB


@dataclass(frozen=True)
class RerankModel:
    name: str
    hf_id: str
    max_length: int = 384  # query + book text, in tokens: covers title, genres and the blurb

    @property
    def available(self) -> bool:
        """Hub models download on first use; a local checkpoint exists only once trained."""
        return not self.hf_id.startswith("models/") or Path(self.hf_id).is_dir()


MODELS: dict[str, RerankModel] = {
    m.name: m
    for m in (
        # Primary: multilingual, strong on short-query relevance. Wants a GPU for N > 50.
        RerankModel("bge-v2-m3", "BAAI/bge-reranker-v2-m3"),
        # Middle ground: half the size, English and Chinese.
        RerankModel("bge-base", "BAAI/bge-reranker-base"),
        # Fallback and fast baseline: 22M parameters, fine on CPU.
        RerankModel("minilm", "cross-encoder/ms-marco-MiniLM-L6-v2", max_length=256),
        # Fine-tuned on this catalog (scripts/train_reranker.py).
        RerankModel("bge-base-ft", "models/bge-base-rerank-ft"),
        RerankModel("minilm-ft", "models/minilm-rerank-ft", max_length=256),
    )
}


class Reranker(Protocol):
    name: str

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        """Relevance of each document to the query, in input order, 0-1."""
        ...


class CrossEncoderReranker:
    def __init__(
        self,
        model: RerankModel,
        device: str | None = None,
        batch_size: int = 32,
        encoder: Any = None,  # a loaded CrossEncoder (or a test double with .predict)
    ) -> None:
        self.name = model.name
        self._batch_size = batch_size
        if encoder is None:
            import torch
            from sentence_transformers import CrossEncoder  # heavy import, only when used

            device = device or pick_device()
            dtype = torch.float16 if device in ("cuda", "mps") else torch.float32
            encoder = CrossEncoder(
                model.hf_id,
                device=device,
                max_length=model.max_length,
                model_kwargs={"torch_dtype": dtype},
                # Probabilities for every model: some configs default to raw logits.
                activation_fn=torch.nn.Sigmoid(),
            )
            own_memory(encoder)
        self._encoder = encoder

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        scores = self._encoder.predict(
            [(query, doc) for doc in documents],
            batch_size=self._batch_size,
            show_progress_bar=False,
        )
        result = [float(s) for s in scores]
        if any(math.isnan(s) for s in result):
            # A broken numeric backend must fail loudly, not rank books by NaN.
            raise RuntimeError(f"reranker {self.name!r} returned NaN scores")
        return result


class CachedReranker:
    """Remembers scores per (query, document key); only unseen pairs reach the model."""

    def __init__(self, inner: Reranker, size: int = CACHE_SIZE) -> None:
        self.name = inner.name
        self._inner = inner
        self._size = size
        self._cache: OrderedDict[tuple[str, int], float] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def clear(self) -> None:
        """Forget every score (latency measurements must not reuse earlier runs' work)."""
        self._cache.clear()
        self.hits = self.misses = 0

    def score_keyed(self, query: str, documents: Mapping[int, str]) -> dict[int, float]:
        missing = [key for key in documents if (query, key) not in self._cache]
        self.hits += len(documents) - len(missing)
        self.misses += len(missing)
        for key, score in zip(
            missing, self._inner.score(query, [documents[k] for k in missing]), strict=True
        ):
            self._cache[(query, key)] = score
        result = {}
        for key in documents:
            self._cache.move_to_end((query, key))
            result[key] = self._cache[(query, key)]
        while len(self._cache) > self._size:
            self._cache.popitem(last=False)
        return result


def rerank(
    reranker: CachedReranker,
    query: str,
    ranked: Sequence[int],
    texts: Mapping[int, str],
    depth: int,
) -> list[tuple[int, float]]:
    """Reorder the first `depth` work ids by cross-encoder score; the rest keep their order after
    them (with no score). Works without text are scored on nothing and sink."""
    head, tail = list(ranked[:depth]), ranked[depth:]
    scores = reranker.score_keyed(query, {w: texts.get(w, "") for w in head})
    reordered = sorted(head, key=lambda w: -scores[w])  # stable: ties keep retrieval order
    return [(w, scores[w]) for w in reordered] + [(w, float("nan")) for w in tail]


def load_reranker(name: str) -> CachedReranker:
    if name not in MODELS:
        raise ValueError(f"unknown reranker {name!r}; choose from {sorted(MODELS)}")
    if not MODELS[name].available:
        raise LookupError(f"{name!r} isn't trained yet: no {MODELS[name].hf_id}/ (Phase 7)")
    return CachedReranker(CrossEncoderReranker(MODELS[name]))
