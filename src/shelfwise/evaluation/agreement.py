"""Agreement between two sets of labels: LLM vs human, or human vs human.

Cohen's kappa corrects raw accuracy for agreement by chance: a tagger that answers "no
supernatural" for every book scores high accuracy on a realistic shelf and kappa 0. Ordered scales
(darkness 0-3, pace) use quadratic weights, so answering 2 when the truth is 3 costs less than
answering 0.
"""

from collections import Counter
from collections.abc import Sequence
from typing import Literal


def accuracy(a: Sequence[str], b: Sequence[str]) -> float:
    _check(a, b)
    return sum(x == y for x, y in zip(a, b, strict=True)) / len(a)


def within_one(a: Sequence[str], b: Sequence[str], categories: Sequence[str]) -> float:
    """Share of pairs at most one step apart on an ordered scale."""
    _check(a, b)
    rank = {c: i for i, c in enumerate(categories)}
    return sum(abs(rank[x] - rank[y]) <= 1 for x, y in zip(a, b, strict=True)) / len(a)


def cohen_kappa(
    a: Sequence[str],
    b: Sequence[str],
    categories: Sequence[str],
    weights: Literal["none", "quadratic"] = "none",
) -> float | None:
    """Cohen's kappa, unweighted or quadratic-weighted over `categories` in order.

    None when chance agreement is already perfect (both raters used one and the same category),
    where kappa is undefined.
    """
    _check(a, b)
    n, k = len(a), len(categories)
    rank = {c: i for i, c in enumerate(categories)}

    def disagreement(i: int, j: int) -> float:
        if weights == "quadratic":
            return (i - j) ** 2 / (k - 1) ** 2 if k > 1 else 0.0
        return 0.0 if i == j else 1.0

    observed = sum(disagreement(rank[x], rank[y]) for x, y in zip(a, b, strict=True)) / n
    count_a, count_b = Counter(rank[x] for x in a), Counter(rank[y] for y in b)
    expected = sum(
        count_a[i] * count_b[j] * disagreement(i, j) for i in range(k) for j in range(k)
    ) / (n * n)
    if expected == 0:
        return None
    return 1 - observed / expected


def _check(a: Sequence[str], b: Sequence[str]) -> None:
    if len(a) != len(b) or not a:
        raise ValueError("need two equally long, non-empty label lists")
