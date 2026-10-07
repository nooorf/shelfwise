import pytest

from shelfwise.evaluation.agreement import accuracy, cohen_kappa, within_one


def test_unweighted_kappa_by_hand() -> None:
    # 20 yes/yes, 5 yes/no, 10 no/yes, 15 no/no: p_o = 0.7, p_e = 0.5*0.6 + 0.5*0.4 = 0.5
    a = ["yes"] * 25 + ["no"] * 25
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15

    assert accuracy(a, b) == pytest.approx(0.7)
    assert cohen_kappa(a, b, ["yes", "no"]) == pytest.approx(0.4)


def test_quadratic_kappa_by_hand() -> None:
    # weights (i-j)^2/4. Observed: one pair 1 step apart -> 1/4 over 3 pairs = 1/12.
    # Expected: 2/9 + 1/12 + 1/9 = 5/12. Kappa = 1 - (1/12)/(5/12) = 0.8
    assert cohen_kappa(["0", "1", "2"], ["0", "2", "2"], ["0", "1", "2"], "quadratic") == (
        pytest.approx(0.8)
    )


def test_quadratic_weights_forgive_near_misses_more_than_far_ones() -> None:
    truth = ["0", "1", "2", "3"] * 5
    near = ["1", "1", "2", "3"] * 5
    far = ["3", "1", "2", "3"] * 5
    scale = ["0", "1", "2", "3"]

    near_kappa = cohen_kappa(truth, near, scale, "quadratic")
    far_kappa = cohen_kappa(truth, far, scale, "quadratic")

    assert near_kappa is not None and far_kappa is not None
    assert near_kappa > far_kappa
    assert accuracy(truth, near) == accuracy(truth, far)


def test_always_answering_the_majority_value_has_zero_kappa() -> None:
    truth = ["no"] * 9 + ["yes"]

    assert accuracy(truth, ["no"] * 10) == pytest.approx(0.9)
    assert cohen_kappa(truth, ["no"] * 10, ["yes", "no"]) == pytest.approx(0.0)


def test_kappa_is_undefined_when_both_use_a_single_category() -> None:
    assert cohen_kappa(["no", "no"], ["no", "no"], ["yes", "no"]) is None


def test_within_one_counts_neighbouring_steps() -> None:
    assert within_one(["0", "0", "0"], ["0", "1", "2"], ["0", "1", "2", "3"]) == pytest.approx(
        2 / 3
    )


def test_unequal_or_empty_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        accuracy([], [])
    with pytest.raises(ValueError):
        cohen_kappa(["a"], ["a", "b"], ["a", "b"])
