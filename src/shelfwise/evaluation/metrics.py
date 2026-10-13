"""IR metrics for graded relevance. Grades: 0 not relevant ... 3 perfect.

A book counts as *relevant* at grade >= 2. NDCG uses graded gains (2^grade - 1). Unjudged books
count as grade 0, so `judged_at_k` is reported alongside to show how much that matters.
"""

import math
import random
from collections.abc import Mapping, Sequence

RELEVANT_GRADE = 2


def dcg(grades: Sequence[int]) -> float:
    return sum((2**g - 1) / math.log2(i + 2) for i, g in enumerate(grades))


def ndcg_at_k(ranked: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    ideal = dcg(sorted(qrels.values(), reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return dcg([qrels.get(doc, 0) for doc in ranked[:k]]) / ideal


def _relevant(qrels: Mapping[str, int]) -> set[str]:
    return {doc for doc, grade in qrels.items() if grade >= RELEVANT_GRADE}


def recall_at_k(ranked: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    relevant = _relevant(qrels)
    return len(relevant & set(ranked[:k])) / len(relevant) if relevant else 0.0


def precision_at_k(ranked: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    relevant = _relevant(qrels)
    return len(relevant & set(ranked[:k])) / k


def hit_at_k(ranked: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    return 1.0 if _relevant(qrels) & set(ranked[:k]) else 0.0


def reciprocal_rank(ranked: Sequence[str], qrels: Mapping[str, int]) -> float:
    relevant = _relevant(qrels)
    return next((1.0 / (i + 1) for i, doc in enumerate(ranked) if doc in relevant), 0.0)


def judged_at_k(ranked: Sequence[str], qrels: Mapping[str, int], k: int) -> float:
    top = ranked[:k]
    return sum(doc in qrels for doc in top) / len(top) if top else 1.0


def query_metrics(ranked: Sequence[str], qrels: Mapping[str, int], k: int = 10) -> dict[str, float]:
    return {
        f"ndcg@{k}": ndcg_at_k(ranked, qrels, k),
        "ndcg@5": ndcg_at_k(ranked, qrels, 5),
        f"recall@{k}": recall_at_k(ranked, qrels, k),
        f"precision@{k}": precision_at_k(ranked, qrels, k),
        f"hit@{k}": hit_at_k(ranked, qrels, k),
        "mrr": reciprocal_rank(ranked, qrels),
        f"judged@{k}": judged_at_k(ranked, qrels, k),
    }


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def bootstrap_ci(
    values: Sequence[float], resamples: int = 2000, alpha: float = 0.05, seed: int = 0
) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for the mean over queries."""
    if not values:
        return 0.0, 0.0
    rng = random.Random(seed)
    n = len(values)
    means = sorted(mean([values[rng.randrange(n)] for _ in range(n)]) for _ in range(resamples))
    low = means[int((alpha / 2) * resamples)]
    high = means[min(resamples - 1, int((1 - alpha / 2) * resamples))]
    return low, high
