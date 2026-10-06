import math

import pytest

from shelfwise.evaluation.metrics import (
    bootstrap_ci,
    dcg,
    hit_at_k,
    judged_at_k,
    mean,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

QRELS = {"a": 3, "b": 2, "c": 1, "d": 0}


def test_dcg_by_hand() -> None:
    # (2^3-1)/log2(2) + (2^2-1)/log2(3) + (2^1-1)/log2(4)
    assert dcg([3, 2, 1]) == pytest.approx(7 + 3 / math.log2(3) + 1 / 2)


def test_ndcg_is_one_for_the_ideal_order() -> None:
    assert ndcg_at_k(["a", "b", "c"], QRELS, 10) == pytest.approx(1.0)


def test_ndcg_by_hand_for_a_worse_order() -> None:
    actual = dcg([1, 0, 3])  # c, x (unjudged), a
    ideal = dcg([3, 2, 1])
    assert ndcg_at_k(["c", "x", "a"], QRELS, 3) == pytest.approx(actual / ideal)


def test_ndcg_without_any_positive_grade_is_zero() -> None:
    assert ndcg_at_k(["a"], {"a": 0}, 10) == 0.0


def test_recall_precision_hit_use_grade_two_or_more() -> None:
    ranked = ["c", "b", "x"]  # c is grade 1: not "relevant"

    assert recall_at_k(ranked, QRELS, 10) == pytest.approx(1 / 2)  # b of {a, b}
    assert precision_at_k(ranked, QRELS, 2) == pytest.approx(1 / 2)
    assert hit_at_k(ranked, QRELS, 1) == 0.0
    assert hit_at_k(ranked, QRELS, 2) == 1.0


def test_reciprocal_rank() -> None:
    assert reciprocal_rank(["x", "c", "b"], QRELS) == pytest.approx(1 / 3)
    assert reciprocal_rank(["x"], QRELS) == 0.0


def test_judged_at_k() -> None:
    assert judged_at_k(["a", "x", "d", "y"], QRELS, 4) == 0.5
    assert judged_at_k([], QRELS, 10) == 1.0


def test_bootstrap_ci_brackets_the_mean_and_is_deterministic() -> None:
    values = [0.1, 0.4, 0.5, 0.9, 0.3, 0.7]

    low, high = bootstrap_ci(values, seed=1)

    assert low <= mean(values) <= high
    assert bootstrap_ci(values, seed=1) == (low, high)
    assert bootstrap_ci([0.5] * 5) == (0.5, 0.5)
