import math

import numpy as np
import pytest

from shelfwise.ranking.rerank import (
    MODELS,
    CachedReranker,
    CrossEncoderReranker,
    rerank,
)

from ..fakes import FakeReranker

TEXTS = {
    1: "a cozy village mystery",
    2: "a dark psychological thriller with a twist",
    3: "a space opera",
    4: "a dark thriller",
}


def test_head_is_reordered_by_score_and_tail_keeps_its_order() -> None:
    reranker = CachedReranker(FakeReranker())

    result = rerank(reranker, "dark psychological thriller", [1, 4, 2, 3], TEXTS, depth=3)

    assert [w for w, _ in result] == [2, 4, 1, 3]
    assert math.isnan(result[-1][1])  # beyond the depth: not scored
    assert reranker.misses == 3


def test_ties_keep_retrieval_order() -> None:
    result = rerank(CachedReranker(FakeReranker()), "unrelated words", [3, 1, 4], TEXTS, depth=3)

    assert [w for w, _ in result] == [3, 1, 4]


def test_repeated_pairs_come_from_the_cache() -> None:
    inner = FakeReranker()
    reranker = CachedReranker(inner)

    rerank(reranker, "dark thriller", [1, 2, 4], TEXTS, depth=3)
    rerank(reranker, "dark thriller", [2, 4, 3], TEXTS, depth=3)  # e.g. a filter was added

    assert (reranker.hits, reranker.misses) == (2, 4)
    assert inner.calls[-1][1] == [TEXTS[3]]  # only the new book reached the model


def test_clear_makes_every_pair_score_again() -> None:
    inner = FakeReranker()
    reranker = CachedReranker(inner)
    rerank(reranker, "dark thriller", [1, 2], TEXTS, depth=2)

    reranker.clear()
    rerank(reranker, "dark thriller", [1, 2], TEXTS, depth=2)

    assert (reranker.hits, reranker.misses) == (0, 2)
    assert len(inner.calls) == 2


def test_cache_is_bounded() -> None:
    reranker = CachedReranker(FakeReranker(), size=2)

    reranker.score_keyed("q", {1: "a", 2: "b", 3: "c"})

    assert len(reranker._cache) == 2


class _Encoder:
    def __init__(self) -> None:
        self.pairs: list[tuple[str, str]] = []

    def predict(self, pairs: list[tuple[str, str]], **_: object) -> np.ndarray:
        self.pairs = pairs
        return np.array([0.9, 0.1], dtype=np.float32)


def test_cross_encoder_sends_query_document_pairs_and_returns_floats() -> None:
    encoder = _Encoder()
    reranker = CrossEncoderReranker(MODELS["minilm"], encoder=encoder)

    scores = reranker.score("dark thriller", ["book a", "book b"])

    assert encoder.pairs == [("dark thriller", "book a"), ("dark thriller", "book b")]
    assert scores == [np.float32(0.9), np.float32(0.1)] and all(type(s) is float for s in scores)
    assert reranker.score("q", []) == []


def test_nan_scores_fail_loudly() -> None:
    class NaNEncoder:
        def predict(self, pairs: list[tuple[str, str]], **_: object) -> np.ndarray:
            return np.full(len(pairs), np.nan)

    reranker = CrossEncoderReranker(MODELS["minilm"], encoder=NaNEncoder())

    with pytest.raises(RuntimeError, match="NaN"):
        reranker.score("q", ["a"])
