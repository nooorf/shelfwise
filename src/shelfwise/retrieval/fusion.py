"""Rank fusion (design doc §14.1).

Reciprocal Rank Fusion combines ranked lists without comparing their raw scores, which live on
different scales (BM25 is unbounded, cosine is -1..1):

    RRF(d) = sum_i  w_i / (k + rank_i(d))

k = 60 and equal weights are the literature default (Cormack et al., 2009) and our untuned
baseline; tuned weights come from the dev split.
"""

from collections.abc import Sequence

DEFAULT_K = 60


def rrf(
    rankings: Sequence[Sequence[int]],
    k: int = DEFAULT_K,
    weights: Sequence[float] | None = None,
) -> list[tuple[int, float]]:
    """Fuse ranked lists of ids (best first); returns (id, score) best first, ties by id."""
    weights = weights or [1.0] * len(rankings)
    if len(weights) != len(rankings):
        raise ValueError("one weight per ranking")
    scores: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights, strict=True):
        for rank, doc in enumerate(ranking, start=1):
            scores[doc] = scores.get(doc, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
